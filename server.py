import html
import re
from pathlib import Path
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse, Response
from datetime import datetime, timedelta
from urllib.parse import urlparse
from fastapi.templating import Jinja2Templates
import glob
import logging

BASE_DIR = Path(__file__).resolve().parent
logging.info("Vercel deployment trace 2...")

app = FastAPI()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

def clean_text(text) -> str:
    if pd.isna(text) or not text: return ""
    # Ritholtz blurbs end with an empty "( )" where the source link was.
    t = re.sub(r"\s*\(\s*\)", "", html.unescape(str(text)))
    # Scraped text nodes get joined with spaces: "eudaemonia , which means “ good spirit .”"
    t = re.sub(r"\s+([,.;:!?”)])", r"\1", t)
    t = re.sub(r"([“(])\s+", r"\1", t)
    return t.strip()

def format_score(score: int) -> str:
    """Format large scores with 'k' suffix (e.g., 82450 -> 82.4k)"""
    if score >= 1000:
        return f"{score / 1000:.1f}k"
    return str(score)

def domain_of(url: str) -> str:
    """'https://www.wsj.com/x' -> 'wsj.com' (used for favicons + source label)."""
    try:
        host = urlparse(str(url)).netloc.lower()
    except Exception:
        return ""
    for pre in ("www.", "m.", "amp."):
        if host.startswith(pre):
            host = host[len(pre):]
    return host

def short_text(text, limit: int = 500) -> str:
    """Trim to ~limit chars at a word boundary (the card can expand to show it all)."""
    t = clean_text(text)
    if len(t) <= limit:
        return t
    return t[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"

def title_key(title) -> str:
    """Same headline from two outlets -> same key ("PM's" == "PMs")."""
    return re.sub(r"[^a-z0-9]", "", clean_text(title).lower())[:70]

def newest_scrape(df) -> str:
    """Latest scraped_at in a CSV (UTC on the GitHub runner), as ISO with Z."""
    if "scraped_at" not in df.columns:
        return ""
    vals = [v for v in df["scraped_at"].astype(str) if v[:2] == "20"]
    return (max(vals)[:19] + "Z") if vals else ""

def calculate_reading_time(text: str) -> int:
    """Calculate estimated reading time in minutes based on word count."""
    if not text:
        return 0
    word_count = len(text.strip().split())
    reading_time = max(1, round(word_count / 200))  # ~200 words per minute
    return reading_time

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

# PWA files. vercel.json routes EVERYTHING to this app, so without these the
# manifest / service worker / icon all 404'd and "Add to Home Screen" was broken.
@app.get("/manifest.json")
def manifest():
    return FileResponse(BASE_DIR / "manifest.json", media_type="application/manifest+json")

@app.get("/sw.js")
def service_worker():
    return FileResponse(BASE_DIR / "sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

@app.get("/icon.png")
def icon():
    return FileResponse(BASE_DIR / "server_assets" / "icon.png", media_type="image/png",
                        headers={"Cache-Control": "public, max-age=604800"})

@app.get("/api/data")
def get_data():
    data = {"monthly": [], "yearly": [], "news": [], "ritholtz": []}
    updated = {"news": "", "ritholtz": ""}
    
    # Load Reddit
    posts_files = glob.glob(str(BASE_DIR / "data/r_*/posts.csv"))
    if posts_files:
        dfs = []
        for f in posts_files:
            if "_yearly" in f: continue
            try:
                df = pd.read_csv(f)
                if df.empty or "id" not in df.columns: continue
                df['subreddit'] = Path(f).parent.name.replace('r_', '')
                df['time_filter'] = 'monthly'
                df['rank'] = range(1, len(df) + 1)  # position in r/sub's own top list
                dfs.append(df)
            except: pass
            
        yearly_files = glob.glob(str(BASE_DIR / "data/r_*_yearly/posts.csv"))
        for f in yearly_files:
            try:
                df = pd.read_csv(f)
                if df.empty or "id" not in df.columns: continue
                df['subreddit'] = Path(f).parent.name.replace('r_', '').replace('_yearly', '')
                df['time_filter'] = 'yearly'
                df['rank'] = range(1, len(df) + 1)
                dfs.append(df)
            except: pass

        if dfs:
            combined = pd.concat(dfs, ignore_index=True)
            # Only scores read from Reddit itself are real. The RSS/HTML fallbacks
            # invent a decaying number just for ordering (older CSVs have no flag,
            # and every save since at least Sep 2026 came from RSS) -> not real.
            if 'score_real' not in combined.columns:
                combined['score_real'] = False
            combined['score_real'] = combined['score_real'].astype(str).str.lower().isin(['true', '1'])
            combined = combined.fillna("")
            combined['id'] = combined['id'].astype(str)
            combined = combined.drop_duplicates(subset=["id", "time_filter"], keep="first")
            combined['score'] = pd.to_numeric(combined['score'], errors='coerce').fillna(0).astype(int)
            combined = combined.sort_values("score", ascending=False)
            
            for _, row in combined.iterrows():
                pid = str(row['id']).strip()
                # Inside the Reddit loop in server.py:
                raw_url = f"https://www.reddit.com{row.get('permalink', '')}" if not str(row.get('permalink', '')).startswith('http') else row.get('permalink', '')
                # Safety check for double-prefixes
                clean_url = raw_url.replace("https://www.reddit.comhttps://", "https://")
                
                # Calculate reading time from selftext
                selftext = str(row.get('selftext', ''))
                read_time = calculate_reading_time(selftext)
                
                when = "month" if row['time_filter'] == 'monthly' else "year"
                item = {
                    "id": pid,
                    "title": clean_text(row['title']),
                    "desc": short_text(selftext),
                    "url": clean_url,
                    "meta": f"r/{row['subreddit']} • {row['time_filter'].upper()}",
                    "source": f"r/{row['subreddit']}",
                    "domain": "reddit.com",
                    "mins": read_time if selftext.strip() else 0,
                    "rank": int(row['rank']) if str(row['rank']).isdigit() else 0,
                    "when": when,
                    # Shown only when it came from Reddit, never an invented number.
                    "upvotes": format_score(row['score']) if row['score_real'] else "",
                }
                # Monthly hides r/AskHistorians (it lives in Yearly). Drop it
                # here, before the 50 cap, so Monthly still gets 50 posts.
                if row['time_filter'] == 'monthly' and row['subreddit'].lower() == 'askhistorians':
                    continue
                data[row['time_filter']].append(item)

    # Load Google News
    news_csv = BASE_DIR / "data/googlenews/articles.csv"
    if news_csv.exists():
        try:
            news_df = pd.read_csv(news_csv).fillna("")
            if not news_df.empty and "article_id" in news_df.columns:
                news_df = news_df.drop_duplicates(subset=["article_id", "category"], keep="first")
                updated["news"] = newest_scrape(news_df)
                # Google News often lists one story from 2-3 outlets, days apart.
                # Keep the EARLIEST copy: its id never changes, so a story already
                # marked read can't come back as "new" when a later copy lands.
                news_df = news_df.assign(_key=news_df["title"].map(title_key))
                news_df = news_df.sort_values("pub_date").drop_duplicates(subset=["_key"], keep="first")
                news_df = news_df.sort_values("pub_date", ascending=False)
                for _, row in news_df.iterrows():
                    pid = f"gn_{row['article_id']}"
                    publisher = str(row.get('author', 'NEWS')).upper()
                    description = str(row.get('description', ''))
                    read_time = calculate_reading_time(description)
                    
                    data["news"].append({
                        "id": pid, 
                        "title": clean_text(row['title']), 
                        "desc": clean_text(description[:300]),
                        "url": str(row['url']).replace("http://", "https://"), 
                        "meta": f"{publisher} • {row.get('category', '').upper()} • {str(row.get('pub_date', ''))[:10]} • ⏱️ {read_time} min",
                        "source": str(row.get('author', '')) or domain_of(row.get('url', '')),
                        "category": str(row.get('category', '')),
                        "domain": domain_of(row.get('url', '')),
                        "date": str(row.get('pub_date', ''))[:10],
                        "ts": str(row.get('pub_date', '')),
                        "mins": read_time,
                    })
        except: pass

    # Load Ritholtz
    ritholtz_csv = BASE_DIR / "data/ritholtz/articles.csv"
    if ritholtz_csv.exists():
        try:
            rith_df = pd.read_csv(ritholtz_csv).fillna("")
            if not rith_df.empty and "article_id" in rith_df.columns:
                updated["ritholtz"] = newest_scrape(rith_df)
                rith_df = rith_df.drop_duplicates(subset=["article_id"], keep="first")
                for _, row in rith_df.iterrows():
                    pid = f"rth_{row['article_id']}"
                    post_date = str(row.get('pub_date', ''))[:10]
                    label = "WEEKEND READS" if "weekend-reads" in str(row.get('source_post', '')) else "AM READS"
                    description = str(row.get('description', ''))
                    read_time = calculate_reading_time(description)
                    
                    data["ritholtz"].append({
                        "id": pid, 
                        "title": clean_text(row['title']), 
                        "desc": clean_text(description[:300]),
                        "url": row['url'], 
                        "meta": f"{label} • {post_date} • ⏱️ {read_time} min",
                        "source": str(row.get('author', '')) or domain_of(row['url']),
                        "domain": domain_of(row['url']),
                        # date = the day Ritholtz PUBLISHED the list (US/Eastern). The
                        # frontend shows only today's list; older ones stay hidden.
                        "date": post_date,
                        "kind": label,
                        "mins": read_time,
                    })
        except: pass

    # Load Read Trung (SatPost)
    trung_csv = BASE_DIR / "data/trung/articles.csv"
    if trung_csv.exists():
        try:
            trung_df = pd.read_csv(trung_csv).fillna("")
            if not trung_df.empty and "article_id" in trung_df.columns:
                trung_df = trung_df.drop_duplicates(subset=["article_id"], keep="first")
                # The RSS feed holds ~20 back issues (January onward). Only the last
                # week's issue belongs next to today's AM Reads.
                cutoff = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
                trung_df = trung_df[trung_df["pub_date"].astype(str).str[:10] >= cutoff]
                for _, row in trung_df.iterrows():
                    pid = f"trg_{row['article_id']}"
                    description = str(row.get('description', ''))
                    read_time = calculate_reading_time(description)
                    
                    data["ritholtz"].append({
                        "id": pid, 
                        "title": clean_text(row['title']), 
                        "desc": clean_text(description[:300]),
                        "url": row['url'], 
                        "meta": f"SATPOST • {str(row.get('pub_date', ''))[:10]} • ⏱️ {read_time} min",
                        "source": "SatPost",
                        "domain": domain_of(row['url']),
                        "date": str(row.get('pub_date', ''))[:10],
                        "kind": "SATPOST",
                        "mins": read_time,
                    })
        except: pass

    # Chronological sort for the merged AM Reads tab
    def extract_date_from_meta(item):
        match = re.search(r'\d{4}-\d{2}-\d{2}', item.get('meta', ''))
        return match.group(0) if match else "1970-01-01"
        
    if "ritholtz" in data and data["ritholtz"]:
        data["ritholtz"].sort(key=extract_date_from_meta, reverse=True)

    yearly_pool = list(data["yearly"])  # before the cap, so Yearly can backfill
    for k in data:
        data[k] = data[k][:50]

    # One of each across tabs: a post already in Monthly's list isn't repeated
    # in Yearly (Yearly backfills from further down instead).
    monthly_ids = {i["id"] for i in data["monthly"]}
    yearly_all = [i for i in yearly_pool if i["id"] not in monthly_ids]
    data["yearly"] = yearly_all[:50]

    data["updated"] = updated  # when each feed last landed (UTC ISO)
    return data
