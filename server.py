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
    return re.sub(r"\s*\(\s*\)", "", html.unescape(str(text))).strip()

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
                dfs.append(df)
            except: pass
            
        yearly_files = glob.glob(str(BASE_DIR / "data/r_*_yearly/posts.csv"))
        for f in yearly_files:
            try:
                df = pd.read_csv(f)
                if df.empty or "id" not in df.columns: continue
                df['subreddit'] = Path(f).parent.name.replace('r_', '').replace('_yearly', '')
                df['time_filter'] = 'yearly'
                dfs.append(df)
            except: pass

        if dfs:
            combined = pd.concat(dfs, ignore_index=True).fillna("")
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
                
                item = {
                    "id": pid, 
                    "title": clean_text(row['title']), 
                    "desc": clean_text(selftext[:300]),
                    "url": clean_url,
                    "meta": f"r/{row['subreddit']} • {row['time_filter'].upper()} • {format_score(row['score'])} pts • ⏱️ {read_time} min",
                    "source": f"r/{row['subreddit']}",
                    "domain": "reddit.com",
                    "mins": read_time,
                }
                data[row['time_filter']].append(item)

    # Load Google News
    news_csv = BASE_DIR / "data/googlenews/articles.csv"
    if news_csv.exists():
        try:
            news_df = pd.read_csv(news_csv).fillna("")
            if not news_df.empty and "article_id" in news_df.columns:
                news_df = news_df.drop_duplicates(subset=["article_id", "category"], keep="first")
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
                        "mins": read_time,
                    })
        except: pass

    # Load Ritholtz
    ritholtz_csv = BASE_DIR / "data/ritholtz/articles.csv"
    if ritholtz_csv.exists():
        try:
            rith_df = pd.read_csv(ritholtz_csv).fillna("")
            if not rith_df.empty and "article_id" in rith_df.columns:
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

    for k in data: 
        data[k] = data[k][:50]
        
    return data
