import argparse
import json
import requests
import pandas as pd
import time
import random
import xml.etree.ElementTree as ET
from pathlib import Path
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from reddit_common import SUBREDDITS, SUBREDDIT_TIERS, list_key, load_meta, fresh_keys
# The Mac's checks for "is this really r/sub's top list?" (stdlib only, no browser needed)
from scrape_reddit_browser import list_problem, raw_from_json, raw_from_rss

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
}


# Reddit 429s most RSS calls from GitHub's shared IPs (21 of 26 on 26 Sep 2026).
# One polite retry per call, capped per run so the job stays well under its
# 20-minute timeout.
RSS_BACKOFF_BUDGET = {"seconds": 480}
# Hard stop for the whole Reddit pass: reddit_backup.yml kills the job at 20 min,
# and a killed job never reaches its commit step.
RUN_DEADLINE_S = 12 * 60

def retry_after(response) -> int:
    try:
        return max(5, int(float(response.headers.get("Retry-After", 30))))
    except (TypeError, ValueError):
        return 30

def rss_selftext(content_html: str) -> str:
    """A self-post's body sits in <div class="md">; link posts have none."""
    if not content_html:
        return ""
    md = BeautifulSoup(content_html, "html.parser").find("div", class_="md")
    return md.get_text(" ", strip=True) if md else ""

def parse_rss(content: bytes, subreddit: str) -> list:
    root = ET.fromstring(content)
    ns = {'atom': 'http://www.w3.org/2005/Atom'}

    # RSS has NO scores. The made-up, decaying number below only orders the
    # merged Monthly/Yearly list. score_real=False stops the site from showing
    # it as upvotes (it did until 26 Sep 2026).
    score_range = SUBREDDIT_TIERS.get(subreddit, SUBREDDIT_TIERS["default"])
    base_max_score = random.randint(score_range[0], score_range[1])

    posts = []
    for i, entry in enumerate(root.findall('atom:entry', ns)):
        link_el = entry.find('atom:link', ns)
        raw_link = link_el.attrib.get('href', '') if link_el is not None else ''
        full_link = f"https://www.reddit.com{raw_link}" if raw_link.startswith('/') else raw_link
        posts.append({
            'id': entry.findtext('atom:id', '', ns).split('_')[-1],
            'title': entry.findtext('atom:title', '', ns),
            'selftext': rss_selftext(entry.findtext('atom:content', '', ns)),
            'permalink': full_link,
            'score': int(base_max_score * (0.88 ** i)) + random.randint(100, 999),
            'score_real': False,
        })
    return posts

def fetch_via_rss(subreddit: str, time_filter: str) -> list:
    """TERTIARY (LAST RESORT): top posts via RSS. Real order and text, no scores."""
    print(f"  ⚠️ Attempting Tertiary Fallback (RSS) for r/{subreddit}...")
    url = f"https://www.reddit.com/r/{subreddit}/top/.rss?t={time_filter}&limit=50"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 429 and RSS_BACKOFF_BUDGET["seconds"] > 0:
            wait = min(retry_after(response), 60, RSS_BACKOFF_BUDGET["seconds"])
            RSS_BACKOFF_BUDGET["seconds"] -= wait
            print(f"  ⏳ RSS 429: waiting {wait}s, then one more try...")
            time.sleep(wait)
            response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        problem = list_problem(raw_from_rss(response.content), subreddit, time_filter,
                               response.url, upvotes=False)
        if problem:  # a login page, another sub, an older list, a near-empty feed
            print(f"  ❌ RSS for r/{subreddit}: {problem}; not saved")
            return []
        return parse_rss(response.content, subreddit)
    except Exception as e:
        print(f"  ❌ Tertiary Fallback (RSS) failed: {e}")
        return []

def fetch_via_json(subreddit: str, time_filter: str) -> list:
    """PRIMARY: Stealth fetch via old.reddit.com JSON endpoint."""
    print(f"  🔄 Attempting Primary Fetch (Stealth JSON) for r/{subreddit}...")
    # Use old.reddit.com and append .json before the query parameters
    url = f"https://old.reddit.com/r/{subreddit}/top.json?t={time_filter}&limit=50"

    try:
        response = requests.get(url, headers=HEADERS, timeout=15)

        # Handle strict rate limiting (429) explicitly
        if response.status_code == 429:
            print("  ⚠️ HTTP 429 Too Many Requests. Reddit is suspicious. Sleeping for 30s...")
            time.sleep(30)
            # Try one more time after a long pause
            response = requests.get(url, headers=HEADERS, timeout=15)

        response.raise_for_status()
        data = response.json()
        raw, complete = raw_from_json(data)
        problem = list_problem(raw, subreddit, time_filter, response.url, complete=complete)
        if problem:
            print(f"  ❌ JSON for r/{subreddit}: {problem}; not saved")
            return []

        posts = []
        for item in data.get('data', {}).get('children', []):
            post = item['data']
            # Skip stickied posts/ads
            if post.get('stickied') or post.get('is_video'):
                continue

            posts.append({
                'id': post.get('id', ''),
                'title': post.get('title', ''),
                'selftext': post.get('selftext', ''),
                'permalink': f"https://www.reddit.com{post.get('permalink', '')}",
                'score': post.get('score', 0),
                'score_real': True,
            })
        return posts
    except Exception as e:
        print(f"  ❌ Primary Stealth JSON failed: {e}")
        return []

def fetch_reddit_posts(subreddit: str, time_filter: str) -> list:
    """RSS first: from GitHub's IPs it is the only way in (checked 26 Sep 2026: JSON
    403, old.reddit 403 or a login page, a real browser "blocked by network
    security"; RSS 200 until rate-limited). JSON stays as a second try in case
    Reddit ever lets GitHub back in, because it carries real upvotes."""
    return fetch_via_rss(subreddit, time_filter) or fetch_via_json(subreddit, time_filter)


def save_posts_to_csv(posts: list, subreddit: str, time_filter: str):
    if not posts: return
    folder_suffix = "_yearly" if time_filter == "year" else ""
    folder_path = Path(f"data/r_{subreddit}{folder_suffix}")
    folder_path.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(posts).to_csv(folder_path / "posts.csv", index=False)
    print(f"  ✅ Saved {len(posts)} posts to {subreddit}")

# When THIS backup last refreshed each list. Its own file, so it never collides with
# the Mac's reddit_browser.json. A list it refreshed recently waits, so each run's
# small batch moves on to the next stalest lists instead of redoing the same ones.
GITHUB_META = Path("data/reddit_github.json")
GITHUB_REFRESH_HOURS = 12


def load_github_meta(path: Path = GITHUB_META) -> dict:
    try:
        lists = json.loads(path.read_text()).get("lists", {})
    except (OSError, ValueError, AttributeError):
        return {}
    return lists if isinstance(lists, dict) else {}


def stamp_github_meta(key: str, path: Path = GITHUB_META):
    lists = load_github_meta(path)
    lists[key] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"note": "When GitHub's RSS backup (core/scrape_top.py) last refreshed "
                                        "each Reddit list the Mac had left stale.",
                                "lists": dict(sorted(lists.items()))}, indent=1) + "\n")


def stale_lists(mac: dict, github: dict, now: datetime) -> list:
    """(sub, time_filter) for every list the Mac hasn't saved in 36 h and this backup
    hasn't refreshed in 12 h, stalest first (never saved = first)."""
    mac_fresh = fresh_keys(mac, now)
    gh_fresh = fresh_keys(github, now, GITHUB_REFRESH_HOURS)
    todo = [(sub, t) for sub in SUBREDDITS for t in ("month", "year")
            if list_key(sub, t) not in mac_fresh and list_key(sub, t) not in gh_fresh]

    def last(x):
        k = list_key(*x)
        return max(str(mac.get(k, "")), str(github.get(k, "")))
    return sorted(todo, key=last)


def main():
    ap = argparse.ArgumentParser(description="GitHub's Reddit backup: RSS for lists the Mac left stale.")
    ap.add_argument("--max-lists", type=int, default=0, help="refresh at most N stale lists (0 = all)")
    a = ap.parse_args()
    print("="*50)
    print("🚀 Reddit backup (RSS -> JSON) for lists the Mac left stale")
    print("="*50)
    deadline = time.monotonic() + RUN_DEADLINE_S
    # Lists the Mac mini's real browser saved recently (real upvotes + text).
    # Leave them alone; RSS here only fills in when the Mac has been down.
    now = datetime.now(timezone.utc)
    try:
        mac, github = load_meta(), load_github_meta()
        todo, n_fresh = stale_lists(mac, github, now), len(fresh_keys(mac, now))
    except Exception as e:  # a bad json must never crash the run
        print(f"⚠️ reddit_browser.json / reddit_github.json unreadable ({e}); scraping every list")
        todo, n_fresh = [(sub, t) for sub in SUBREDDITS for t in ("month", "year")], 0
    print(f"🖥️ {n_fresh} lists fresh from the Mac, {len(todo)} need a refresh here")
    batch = todo[:a.max_lists] if a.max_lists > 0 else todo
    done = 0
    for sub, t_filter in batch:
        if time.monotonic() > deadline:
            print(f"⏱️ {RUN_DEADLINE_S // 60}-min Reddit limit reached: the rest wait for the next run.")
            break
        print(f"📡 Processing r/{sub} ({t_filter})...")
        posts = fetch_reddit_posts(sub, t_filter)
        save_posts_to_csv(posts, sub, t_filter)
        if posts:
            stamp_github_meta(list_key(sub, t_filter))
            done += 1
        # Randomized human-like jitter (6.5 to 12.5 seconds)
        jitter = random.uniform(6.5, 12.5)
        print(f"  💤 Humanizing delay: Sleeping for {jitter:.2f} seconds...")
        time.sleep(jitter)
    print(f"REDDIT BACKUP: refreshed {done} of {len(todo)} lists that needed it (tried {len(batch)})")
    if not batch:
        # Nothing to do (the Mac is fine): still prove RSS reaches Reddit from here,
        # so a dead backup shows up on the fleet board before the day it's needed.
        # One read, nothing written; the sub rotates every 3 hours.
        sub = SUBREDDITS[(datetime.now(timezone.utc).hour // 3) % len(SUBREDDITS)]
        posts = fetch_via_rss(sub, "month")
        print(f"GITHUB REDDIT CHECK: rss {'ok' if posts else 'FAILED'} (r/{sub}: {len(posts)} posts)")


if __name__ == "__main__":
    main()
