import html
import re
from pathlib import Path
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse, Response
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from fastapi.templating import Jinja2Templates
import glob
import logging
import math

BASE_DIR = Path(__file__).resolve().parent
# Warnings reach Vercel's runtime logs. A broken file used to vanish in a bare
# `except: pass`, leaving a tab silently empty with no trace anywhere.
log = logging.getLogger("daily-reader")

# Only subs the scrapers still track are shown. A dropped sub's old CSV stays in
# data/ and used to keep feeding the tabs (r/Fitness: March posts shown as "this
# month" until 26 Sep 2026). vercel.json bundles core/** for this import; if it
# ever fails, show everything rather than take the site down.
try:
    from core.reddit_common import SUBREDDITS as TRACKED_SUBS
except Exception as e:  # pragma: no cover - only on a broken deploy
    log.warning("core.reddit_common not importable (%s); showing every data/r_* list", e)
    TRACKED_SUBS = None
BROWSER_META = BASE_DIR / "data/reddit_browser.json"

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

NEWS_DAYS = 7


def is_tracked(sub: str) -> bool:
    return TRACKED_SUBS is None or sub.lower() in {t.lower() for t in TRACKED_SUBS}


def read_csv_safe(path):
    """A CSV as a DataFrame, or None (logged) when it is missing, empty or broken."""
    try:
        df = pd.read_csv(path)
    except Exception as e:
        log.warning("skipping %s: %s", path, e)
        return None
    return None if df.empty else df


def reddit_list_stamps(field: str = "lists") -> dict:
    """{list folder: ISO time} from data/reddit_browser.json, tracked subs only.
    The Mac mini's real-browser scrape writes, per list, when it last SAVED it
    ("lists") and when it last REACHED its real page, saved or not ("checked")."""
    try:
        lists = json.loads(BROWSER_META.read_text()).get(field, {})
    except Exception:
        return {}
    if not isinstance(lists, dict):
        return {}
    return {k: str(v) for k, v in lists.items()
            if isinstance(k, str) and k.startswith("r_") and is_tracked(k[2:].removesuffix("_yearly"))}


def load_reddit_frames() -> list:
    """One DataFrame per tracked data/r_<sub>[_yearly]/posts.csv, tagged with its
    sub, tab and rank (the post's place in that sub's own top list)."""
    dfs = []
    for f in sorted(glob.glob(str(BASE_DIR / "data/r_*/posts.csv"))):
        folder = Path(f).parent.name
        yearly = folder.endswith("_yearly")
        sub = folder[2:].removesuffix("_yearly")
        if not is_tracked(sub):
            continue
        df = read_csv_safe(f)
        if df is None or not {"id", "title"}.issubset(df.columns):
            continue
        df['subreddit'] = sub
        df['time_filter'] = 'yearly' if yearly else 'monthly'
        df['rank'] = range(1, len(df) + 1)
        dfs.append(df)
    return dfs


def shown_upvotes(row) -> str:
    """Reddit's own number, or "" (the card then shows the rank instead).
    `upvotes` column = real (Mac browser); else `score`, only if `score_real`
    (old JSON rows). Never the made-up tier number that orders the list."""
    up = pd.to_numeric(row.get('upvotes', ''), errors='coerce')
    if pd.notna(up) and math.isfinite(up):
        return format_score(int(up))
    return format_score(int(row['score'])) if row['score_real'] else ""


def reddit_item(row):
    """One Reddit CSV row -> a card, or None when it has no id/title or it's
    r/AskHistorians on Monthly (that sub lives in Yearly; dropped here, before
    the 50 cap, so Monthly still gets 50 posts)."""
    pid = str(row['id']).strip()
    if not pid or not str(row['title']).strip():
        return None
    if row['time_filter'] == 'monthly' and row['subreddit'].lower() == 'askhistorians':
        return None
    link = str(row.get('permalink', ''))
    url = link if link.startswith('http') else f"https://www.reddit.com{link}"
    url = url.replace("https://www.reddit.comhttps://", "https://")  # double-prefix guard
    selftext = str(row.get('selftext', ''))
    return {
        "id": pid,
        "title": clean_text(row['title']),
        "desc": short_text(selftext),
        "url": url,
        "meta": f"r/{row['subreddit']} • {row['time_filter'].upper()}",
        "source": f"r/{row['subreddit']}",
        "domain": "reddit.com",
        "mins": calculate_reading_time(selftext) if selftext.strip() else 0,
        "rank": int(row['rank']) if str(row['rank']).isdigit() else 0,
        "when": "month" if row['time_filter'] == 'monthly' else "year",
        # Shown only when it came from Reddit, never an invented number.
        "upvotes": shown_upvotes(row),
    }


@app.get("/api/data")
def get_data():
    data = {"monthly": [], "yearly": [], "news": [], "ritholtz": []}
    updated = {"news": "", "ritholtz": "", "reddit": ""}
    
    # Load Reddit
    try:
        dfs = load_reddit_frames()
        if dfs:
            combined = pd.concat(dfs, ignore_index=True)
            # score_real = "is `score` a number Reddit gave?" Only the old JSON path's
            # were. The RSS/HTML fallbacks and the Mac browser put a made-up tier
            # number there for ORDERING (the Mac's real number is in `upvotes`).
            # CSVs without the flag count as not real.
            if 'score_real' not in combined.columns:
                combined['score_real'] = False
            combined['score_real'] = combined['score_real'].astype(str).str.lower().isin(['true', '1'])
            combined = combined.fillna("")
            combined['id'] = combined['id'].astype(str)
            combined = combined.drop_duplicates(subset=["id", "time_filter"], keep="first")
            score = pd.to_numeric(combined['score'], errors='coerce')
            combined['score'] = score.where(score.abs() < 1e12, 0).astype(int)  # junk/inf/NaN -> 0
            # Order by `score` (the tier mix). The Mac browser's CSVs carry the real
            # number separately in `upvotes`; old JSON rows have it in `score`.
            combined = combined.sort_values("score", ascending=False, kind="stable")
        
            bad_rows = 0
            for _, row in combined.iterrows():
                try:  # one odd row costs that row, not both tabs
                    item = reddit_item(row)
                except Exception as e:
                    bad_rows += 1
                    if bad_rows == 1:
                        log.warning("skipping bad Reddit row %r: %s", row.get('id'), e)
                    continue
                if item:
                    data[row['time_filter']].append(item)
            if bad_rows:
                log.warning("skipped %d bad Reddit rows", bad_rows)
    except Exception:
        log.exception("Reddit tabs failed to build")
        data["monthly"], data["yearly"] = [], []

    # Load Google News
    news_df = read_csv_safe(BASE_DIR / "data/googlenews/articles.csv")
    if news_df is not None:
        try:
            news_df = news_df.fillna("")
            if {"article_id", "title", "pub_date"}.issubset(news_df.columns):
                news_df = news_df.drop_duplicates(subset=["article_id", "category"], keep="first")
                updated["news"] = newest_scrape(news_df)
                # Google News often lists one story from 2-3 outlets, days apart.
                # Keep the EARLIEST copy: its id never changes, so a story already
                # marked read can't come back as "new" when a later copy lands.
                news_df = news_df.assign(_key=news_df["title"].map(title_key))
                news_df = news_df.sort_values("pub_date").drop_duplicates(subset=["_key"], keep="first")
                # News = every story from the last NEWS_DAYS days, no count cap, so
                # the tab's number is the real volume (it was a flat 50 until 26 Sep 2026).
                when = pd.to_datetime(news_df["pub_date"], utc=True, errors="coerce")
                news_df = news_df[when >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=NEWS_DAYS)]
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
                        "url": str(row.get('url', '')).replace("http://", "https://"),
                        "meta": f"{publisher} • {row.get('category', '').upper()} • {str(row.get('pub_date', ''))[:10]} • ⏱️ {read_time} min",
                        "source": str(row.get('author', '')) or domain_of(row.get('url', '')),
                        "category": str(row.get('category', '')),
                        "domain": domain_of(row.get('url', '')),
                        "date": str(row.get('pub_date', ''))[:10],
                        "ts": str(row.get('pub_date', '')),
                        "mins": read_time,
                    })
        except Exception:
            log.exception("News tab failed to build")
            data["news"] = []

    # Load Ritholtz
    rith_df = read_csv_safe(BASE_DIR / "data/ritholtz/articles.csv")
    if rith_df is not None:
        try:
            rith_df = rith_df.fillna("")
            if {"article_id", "title", "url"}.issubset(rith_df.columns):
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
        except Exception:
            log.exception("AM Reads (Ritholtz) failed to build")
            data["ritholtz"] = []

    # Load Read Trung (SatPost)
    trung_df = read_csv_safe(BASE_DIR / "data/trung/articles.csv")
    if trung_df is not None:
        try:
            trung_df = trung_df.fillna("")
            if {"article_id", "title", "url", "pub_date"}.issubset(trung_df.columns):
                trung_df = trung_df.drop_duplicates(subset=["article_id"], keep="first")
                # The RSS feed holds ~20 back issues (January onward). Only the last
                # week's issue belongs next to today's AM Reads.
                cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
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
        except Exception:
            log.exception("SatPost failed to build")
            data["ritholtz"] = [i for i in data["ritholtz"] if i.get("kind") != "SATPOST"]

    # Chronological sort for the merged AM Reads tab
    def extract_date_from_meta(item):
        match = re.search(r'\d{4}-\d{2}-\d{2}', item.get('meta', ''))
        return match.group(0) if match else "1970-01-01"
        
    if "ritholtz" in data and data["ritholtz"]:
        data["ritholtz"].sort(key=extract_date_from_meta, reverse=True)

    yearly_pool = list(data["yearly"])  # before the cap, so Yearly can backfill
    monthly_pool = len(data["monthly"])
    for k in ("monthly", "ritholtz"):   # News is capped by date instead (NEWS_DAYS)
        data[k] = data[k][:50]

    # One of each across tabs: a post already in Monthly's list isn't repeated
    # in Yearly (Yearly backfills from further down instead).
    monthly_ids = {i["id"] for i in data["monthly"]}
    yearly_all = [i for i in yearly_pool if i["id"] not in monthly_ids]
    data["yearly"] = yearly_all[:50]
    # How many posts the top 50 were picked from (the site says "top 50 of 582").
    data["totals"] = {"monthly": monthly_pool, "yearly": len(yearly_all), "news_days": NEWS_DAYS}

    stamps = reddit_list_stamps()
    updated["reddit"] = max(stamps.values()) if stamps else ""  # last Mac-browser save
    data["updated"] = updated  # when each feed last landed (UTC ISO)
    return data


@app.get("/api/status")
def status():
    """Health page for fleet-health and humans: when each Reddit list was last
    saved by the Mac mini (oldest first), and when each feed last landed."""
    saved, checked = reddit_list_stamps("lists"), reddit_list_stamps("checked")
    # checked = the Mac reached the list's real page (saved or, if too short, not);
    # fleet-health grades the oldest `checked`, so a quiet sub doesn't page.
    lists = sorted(({"list": k, "saved": saved.get(k, ""), "checked": checked.get(k, "")}
                    for k in saved.keys() | checked.keys()),
                   key=lambda r: r["checked"] or r["saved"])
    # Lists the Mac has never saved (GitHub's RSS backup is all they get). Named
    # here because a row without a stamp is invisible to an oldest-stamp check.
    expected = [f"r_{s}{y}" for s in (TRACKED_SUBS or []) for y in ("", "_yearly")]
    d = get_data()
    return {
        "reddit_lists": lists,
        "reddit_oldest": min(saved.values()) if saved else "",
        "reddit_missing": [k for k in expected if k not in saved],
        "tracked_subs": len(TRACKED_SUBS) if TRACKED_SUBS else None,
        "updated": d["updated"],
        "counts": {k: len(d[k]) for k in ("monthly", "yearly", "news", "ritholtz")},
    }
