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
GITHUB_META = BASE_DIR / "data/reddit_github.json"  # GitHub's RSS backup (core/scrape_top.py)

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
GITHUB_TOP = 10   # the GitHub tab = GitHub's own top 10 of today's trending page


def github_id(repo: str) -> str:
    """'NVIDIA/Model-Optimizer' -> 'gh_nvidia_model-optimizer'. Read state is a
    Firestore doc per id and '/' would split the path; owners never contain '_',
    so the first '_' after 'gh_' is unambiguous."""
    return "gh_" + repo.strip().lower().replace("/", "_")


def github_item(row) -> dict:
    """One data/github_trending/repos.csv row -> a card. Numbers only when the
    page gave them (never invented)."""
    repo = str(row["repo"]).strip()
    lang = str(row.get("language", "")).strip()
    num = lambda k: pd.to_numeric(row.get(k, ""), errors="coerce")
    stars, today, rank = num("stars"), num("stars_today"), int(row["rank"])
    return {
        "id": github_id(repo),
        "title": repo,
        "desc": short_text(row.get("description", "")),
        "url": f"https://github.com/{repo}",
        "meta": f"GITHUB • #{rank} • {lang}",
        "source": f"GitHub · {lang}" if lang else "GitHub",
        "domain": "github.com",
        "rank": rank,
        "stars": format_score(int(stars)) if pd.notna(stars) and math.isfinite(stars) else "",
        "stars_today": f"{int(today):,}" if pd.notna(today) and math.isfinite(today) else "",
        "language": lang,
    }


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


def reddit_list_stamps(field: str = "lists", path: Path = None) -> dict:
    """{list folder: value} from data/reddit_browser.json, tracked subs only.
    The Mac mini's real-browser scrape writes, per list, when it last SAVED it
    ("lists"), when it last REACHED its real page, saved or not ("checked"), and
    which method read it ("via": page, json or rss)."""
    try:
        lists = json.loads((path or BROWSER_META).read_text()).get(field, {})
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
    data = {"monthly": [], "yearly": [], "news": [], "ritholtz": [], "github": []}
    updated = {"news": "", "ritholtz": "", "reddit": "", "github": ""}
    github_pool = 0
    
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
                        "pub_ts": str(row.get('pub_date', '')),  # full publish time, for /api/freshness (not "ts": the card would show "3h ago")
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
                        "pub_ts": str(row.get('pub_date', '')),
                        "kind": "SATPOST",
                        "mins": read_time,
                    })
        except Exception:
            log.exception("SatPost failed to build")
            data["ritholtz"] = [i for i in data["ritholtz"] if i.get("kind") != "SATPOST"]

    # Load GitHub Trending (core/scrape_github_trending.py): today's page, in
    # GitHub's own order. The tab shows the top GITHUB_TOP.
    gh_df = read_csv_safe(BASE_DIR / "data/github_trending/repos.csv")
    if gh_df is not None:
        try:
            gh_df = gh_df.fillna("")
            if {"repo", "rank"}.issubset(gh_df.columns):
                updated["github"] = newest_scrape(gh_df)
                gh_df = gh_df[gh_df["repo"].astype(str).str.count("/") == 1]
                gh_df = gh_df.assign(rank=pd.to_numeric(gh_df["rank"], errors="coerce"))
                gh_df = gh_df.dropna(subset=["rank"]).sort_values("rank", kind="stable")
                gh_df = gh_df.drop_duplicates(subset=["repo"], keep="first")
                github_pool = len(gh_df)
                for _, row in gh_df.iterrows():
                    try:  # one odd row costs that row
                        data["github"].append(github_item(row))
                    except Exception as e:
                        log.warning("skipping bad GitHub row %r: %s", row.get("repo"), e)
                data["github"] = data["github"][:GITHUB_TOP]
        except Exception:
            log.exception("GitHub Trending failed to build")
            data["github"] = []

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
    data["totals"] = {"monthly": monthly_pool, "yearly": len(yearly_all), "news_days": NEWS_DAYS,
                      "github": github_pool}
    # The page keeps unread posts that drop out of the top 50 (index.html
    # trackKept). This list lets it forget posts from a sub that was removed.
    data["reddit_subs"] = sorted(TRACKED_SUBS) if TRACKED_SUBS else []

    stamps = reddit_list_stamps()
    updated["reddit"] = max(stamps.values()) if stamps else ""  # last Mac-browser save
    data["updated"] = updated  # when each feed last landed (UTC ISO)
    return data


@app.get("/api/status")
def status():
    """Health page for fleet-health and humans: when each Reddit list was last
    saved by the Mac mini (oldest first), and when each feed last landed."""
    saved, checked = reddit_list_stamps("lists"), reddit_list_stamps("checked")
    via = reddit_list_stamps("via")  # page, json or rss: which of the Mac's methods saved it
    # GitHub's RSS backup refilled a list after the Mac last saved it: that's what's live.
    for k, stamp in reddit_list_stamps("lists", GITHUB_META).items():
        if stamp > saved.get(k, ""):
            via[k] = "github rss"
    # checked = the Mac reached the list's real page (saved or, if too short, not);
    # fleet-health grades the oldest `checked`, so a quiet sub doesn't page.
    lists = sorted(({"list": k, "saved": saved.get(k, ""), "checked": checked.get(k, ""),
                     "via": via.get(k, "")}
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
        "counts": {k: len(d[k]) for k in ("monthly", "yearly", "news", "ritholtz", "github")},
    }


# ---------- /api/freshness: what the SCREEN serves, contract v1 (2 Oct 2026) ----------
# fleet-health judges it (probe "freshness"). Built from get_data(), the exact answer
# the page renders, never from a writer's own "I ran" stamp. Ages in hours only.
REDDIT_MAX_AGE_H = 52   # Mac every 12 h; dead Mac -> GitHub backup after 36 h, 6 lists / 3 h
NEWS_MAX_AGE_H = 38     # 03:00 UTC + 09:00 retry; worst seen 32.5 h (25-26 Sep), + GHA lag
GITHUB_MAX_AGE_H = 18   # every 6 h + morning kicks; worst seen 8.9 h
AM_READS_LAG_H = 6      # Ritholtz posts ~06:00-06:30 ET Mon-Sat (Sat = Weekend Reads, no Sunday)


def _age_h(stamp, now):
    """Hours since an ISO stamp (naive = UTC, like the GitHub runners write), or None."""
    when = pd.to_datetime(str(stamp or ""), utc=True, errors="coerce")
    if pd.isna(when):
        return None
    return round((now - when.to_pydatetime()).total_seconds() / 3600, 1)


def _eastern_offset_h(utc: datetime) -> int:
    """US/Eastern offset (-4 EDT / -5 EST) by the US DST rule, no tz database needed."""
    def nth_sunday(month, n):
        d = datetime(utc.year, month, 1, tzinfo=timezone.utc)
        d += timedelta(days=(6 - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    start = nth_sunday(3, 2) + timedelta(hours=7)   # 2:00 EST
    end = nth_sunday(11, 1) + timedelta(hours=6)    # 2:00 EDT
    return -4 if start <= utc < end else -5


def am_reads_max_age_h(now: datetime) -> float:
    """Hours since the latest Ritholtz slot (Mon-Sat 06:30 ET) that is due by now
    (slot + AM_READS_LAG_H), + 1 h because posts land 06:00-06:30. The served list
    must be at least that new: a missed weekday turns red the next morning, while
    Sunday and Monday 05:00 still accept Saturday's Weekend Reads."""
    off = timedelta(hours=_eastern_offset_h(now))
    et = now + off
    for back in range(0, 9):
        day = (et - timedelta(days=back)).date()
        if day.weekday() == 6:     # Sunday: no post
            continue
        slot_et = datetime(day.year, day.month, day.day, 6, 30, tzinfo=timezone.utc)
        if slot_et + timedelta(hours=AM_READS_LAG_H) <= et:
            return round((et - slot_et).total_seconds() / 3600 + 1, 1)
    return 48.0  # not reached: some Mon-Sat slot is always due within 8 days


def served_reddit_age(items, suffix, saved, github, now):
    """Age of the OLDEST list the tab is showing: each list's newest save, by the Mac
    (data/reddit_browser.json lists) or GitHub's RSS backup (reddit_github.json),
    both shipped in the same commit as the CSV. `checked` is NOT used: the Mac writes
    it even when it kept the old file."""
    ages = []
    for sub in {i["source"][2:] for i in items if str(i.get("source", "")).startswith("r/")}:
        key = f"r_{sub}{suffix}"
        stamp = max(saved.get(key, ""), github.get(key, ""))
        if stamp:
            ages.append(_age_h(stamp, now))
    ages = [a for a in ages if a is not None]
    return max(ages) if ages else None


def freshness_items(now: datetime = None) -> list:
    now = now or datetime.now(timezone.utc)
    d = get_data()
    saved, github = reddit_list_stamps("lists"), reddit_list_stamps("lists", GITHUB_META)
    rith = [i for i in d["ritholtz"] if i.get("kind") != "SATPOST"]
    satpost = [i for i in d["ritholtz"] if i.get("kind") == "SATPOST"]

    def newest(items):
        ages = [a for a in (_age_h(i.get("pub_ts"), now) for i in items) if a is not None]
        return min(ages) if ages else None
    return [
        {"name": "reddit-monthly", "inputAgeH": None,
         "servedAgeH": served_reddit_age(d["monthly"], "", saved, github, now),
         "graceH": 0, "maxAgeH": REDDIT_MAX_AGE_H},
        {"name": "reddit-yearly", "inputAgeH": None,
         "servedAgeH": served_reddit_age(d["yearly"], "_yearly", saved, github, now),
         "graceH": 0, "maxAgeH": REDDIT_MAX_AGE_H},
        {"name": "news", "inputAgeH": None, "servedAgeH": _age_h(d["updated"]["news"], now),
         "graceH": 0, "maxAgeH": NEWS_MAX_AGE_H},
        {"name": "am-reads", "inputAgeH": None, "servedAgeH": newest(rith),
         "graceH": 0, "maxAgeH": am_reads_max_age_h(now)},
        # SatPost has had no new issue since 26 Jun 2026 (the feed itself), so no cap:
        # its age is shown, not graded.
        {"name": "satpost", "inputAgeH": None, "servedAgeH": newest(satpost), "graceH": 0},
        {"name": "github-trending", "inputAgeH": None, "servedAgeH": _age_h(d["updated"]["github"], now),
         "graceH": 0, "maxAgeH": GITHUB_MAX_AGE_H},
    ]


@app.get("/api/freshness")
def freshness():
    try:
        body, code = {"app": "reddit-scraper", "v": 1, "items": freshness_items()}, 200
    except Exception as e:
        log.exception("freshness failed")
        body, code = {"error": type(e).__name__}, 500
    return Response(json.dumps(body), status_code=code, media_type="application/json",
                    headers={"Cache-Control": "no-store"})
