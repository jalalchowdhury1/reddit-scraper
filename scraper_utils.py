import requests
import datetime
import os
import random
import json
import csv

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

MIRRORS = [
    "https://old.reddit.com",
    "https://redlib.catsarch.com",
    "https://redlib.vsls.cz",
    "https://r.nf",
    "https://libreddit.northboot.xyz",
    "https://redlib.tux.pizza"
]

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})

def fetch_json(url, retries=3):
    """Fetch JSON with retry logic."""
    for attempt in range(retries):
        try:
            response = SESSION.get(url, timeout=15)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:  # Rate limited
                os.system(f"sleep {5 * (attempt + 1)}")
        except Exception:
            if attempt < retries - 1:
                os.system("sleep 2")
    return None

def fetch_top_posts(subreddit, t='month', limit=5):
    """Fetch top posts for a subreddit with a specific time scale."""
    mirrors = MIRRORS.copy()
    random.shuffle(mirrors)
    
    for base_url in mirrors:
        url = f"{base_url}/r/{subreddit}/top.json?t={t}&limit={limit}&raw_json=1"
        data = fetch_json(url)
        if data:
            return data.get('data', {}).get('children', [])
    return []

def extract_post_data(p):
    """Extract relevant post data from Reddit JSON."""
    post_type = "text"
    if p.get('is_video'):
        post_type = "video"
    elif p.get('is_gallery'):
        post_type = "gallery"
    elif any(ext in p.get('url', '').lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']) or 'i.redd.it' in p.get('url', ''):
        post_type = "image"
    elif p.get('is_self'):
        post_type = "text"
    else:
        post_type = "link"
    
    return {
        "id": p.get('id'),
        "title": p.get('title'),
        "author": p.get('author'),
        "created_utc": datetime.datetime.fromtimestamp(p.get('created_utc', 0)).isoformat(),
        "permalink": f"https://reddit.com{p.get('permalink')}",
        "url": p.get('url_overridden_by_dest', p.get('url')),
        "score": p.get('score', 0),
        "num_comments": p.get('num_comments', 0),
        "subreddit": p.get('subreddit'),
        "post_type": post_type
    }
