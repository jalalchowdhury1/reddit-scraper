import requests
import pandas as pd
import time
import random
import xml.etree.ElementTree as ET
from pathlib import Path
from bs4 import BeautifulSoup

SUBREDDITS = [
    "dataisbeautiful", "todayilearned", "bestof",
    "getmotivated", "UnethicalLifeProTips", "LifeProTips",
    "TrueReddit", "UpliftingNews", "lifehacks", "Productivity",
    "PersonalFinance", "explainlikeimfive", "AskHistorians"
]

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

# Tiered priority system for dummy upvote generation in fallback scrapers
SUBREDDIT_TIERS = {
    # Tier 1: The Heavyweights (Highest priority)
    "bestof": (75000, 100000),
    "explainlikeimfive": (75000, 100000),
    "todayilearned": (75000, 100000),
    "AskHistorians": (75000, 100000),

    # Tier 2: High Signal
    "TrueReddit": (40000, 70000),
    "dataisbeautiful": (40000, 70000),
    "PersonalFinance": (40000, 70000),

    # Tier 3: Default (Everything else)
    "default": (15000, 35000)
}

def fetch_via_html(subreddit: str, time_filter: str) -> list:
    """SECONDARY: Scrapes the raw HTML of old.reddit.com - Better because it has SCORES."""
    print(f"    🛡️ Attempting Secondary Fallback (HTML) for r/{subreddit}...")
    url = f"https://old.reddit.com/r/{subreddit}/top/?sort=top&t={time_filter}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        posts = []

        # Determine base score range for this subreddit
        score_range = SUBREDDIT_TIERS.get(subreddit, SUBREDDIT_TIERS["default"])
        base_max_score = random.randint(score_range[0], score_range[1])

        for i, thing in enumerate(soup.find_all('div', class_='thing')[:50]):
            title_elem = thing.find('a', class_='title')
            if not title_elem: continue

            # Extract raw permalink
            raw_permalink = thing.get('data-permalink', '')

            # ENSURE ABSOLUTE URL: If it starts with /r/, prepend reddit.com
            if raw_permalink.startswith('/'):
                full_permalink = f"https://www.reddit.com{raw_permalink}"
            elif not raw_permalink.startswith('http'):
                full_permalink = f"https://www.reddit.com/{raw_permalink.lstrip('/')}"
            else:
                full_permalink = raw_permalink

            score = 0
            score_elem = thing.find('div', class_='score unvoted')
            if score_elem and score_elem.get('title'):
                try: score = int(score_elem.get('title'))
                except ValueError: pass

            # If score is 0 (not scraped), use tiered exponential decay
            if score == 0:
                # Exponential decay: each post drops by roughly 12% from the previous, plus some random noise
                score = int(base_max_score * (0.88 ** i)) + random.randint(100, 999)

            posts.append({
                'id': thing.get('data-fullname', '').split('_')[-1],
                'title': title_elem.text.strip(),
                'selftext': "",
                'permalink': full_permalink,
                'score': score
            })

        return posts
    except Exception as e:
        print(f"    ❌ Secondary Fallback (HTML) also failed: {e}")
        return []

def fetch_via_rss(subreddit: str, time_filter: str) -> list:
    """TERTIARY (LAST RESORT): Fetches posts via RSS - Fixed for Absolute URLs and Sorting."""
    print(f"  ⚠️ Attempting Tertiary Fallback (RSS) for r/{subreddit}...")
    url = f"https://www.reddit.com/r/{subreddit}/top/.rss?t={time_filter}&limit=50"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.content)

        posts = []
        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        # Determine base score range for this subreddit
        score_range = SUBREDDIT_TIERS.get(subreddit, SUBREDDIT_TIERS["default"])
        base_max_score = random.randint(score_range[0], score_range[1])

        # Track index to create a descending 'dummy' score with exponential decay
        for i, entry in enumerate(root.findall('atom:entry', ns)):
            raw_link = entry.find('atom:link', ns).attrib.get('href', '') if entry.find('atom:link', ns) is not None else ''

            # FIX 1: Ensure absolute URL
            full_link = raw_link
            if raw_link.startswith('/'):
                full_link = f"https://www.reddit.com{raw_link}"

            # FIX 2: Tiered exponential decay scoring for better sorting
            # Exponential decay: each post drops by roughly 12% from the previous, plus some random noise
            dummy_score = int(base_max_score * (0.88 ** i)) + random.randint(100, 999)

            posts.append({
                'id': entry.findtext('atom:id', '', ns).split('_')[-1],
                'title': entry.findtext('atom:title', '', ns),
                'selftext': "",
                'permalink': full_link,
                'score': dummy_score
            })
        return posts
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
                'score': post.get('score', 0)
            })
        return posts
    except Exception as e:
        print(f"  ❌ Primary Stealth JSON failed: {e}")
        return []

def fetch_reddit_posts(subreddit: str, time_filter: str) -> list:
    """PRIMARY: Fetches top posts via old.reddit.com JSON (Stealth). Falls back to HTML/RSS."""
    # Try stealth JSON first
    json_posts = fetch_via_json(subreddit, time_filter)
    if json_posts:
        return json_posts

    # Fallback to HTML (has scores)
    html_posts = fetch_via_html(subreddit, time_filter)
    if html_posts:
        return html_posts

    # Last resort: RSS
    return fetch_via_rss(subreddit, time_filter)

def save_posts_to_csv(posts: list, subreddit: str, time_filter: str):
    if not posts: return
    folder_suffix = "_yearly" if time_filter == "year" else ""
    folder_path = Path(f"data/r_{subreddit}{folder_suffix}")
    folder_path.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(posts).to_csv(folder_path / "posts.csv", index=False)
    print(f"  ✅ Saved {len(posts)} posts to {subreddit}")

def main():
    print("="*50)
    print("🚀 Triple-Threat Reddit Scraper (JSON -> HTML -> RSS)")
    print("="*50)
    for sub in SUBREDDITS:
        for t_filter in ["month", "year"]:
            print(f"📡 Processing r/{sub} ({t_filter})...")
            posts = fetch_reddit_posts(sub, t_filter)
            save_posts_to_csv(posts, sub, t_filter)
            # Randomized human-like jitter (6.5 to 12.5 seconds)
            jitter = random.uniform(6.5, 12.5)
            print(f"  💤 Humanizing delay: Sleeping for {jitter:.2f} seconds...")
            time.sleep(jitter)

if __name__ == "__main__":
    main()
