import requests
import pandas as pd
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from bs4 import BeautifulSoup

SUBREDDITS = [
    "dataisbeautiful", "todayilearned", "sobooksoc", "Fitness", 
    "getmotivated", "UnethicalLifeProTips", "LifeProTips", 
    "TrueReddit", "UpliftingNews", "lifehacks", "Productivity", 
    "PersonalFinance", "explainlikeimfive"
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
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
        
        for thing in soup.find_all('div', class_='thing')[:50]:
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
        # Track index to create a descending 'dummy' score
        for i, entry in enumerate(root.findall('atom:entry', ns)):
            raw_link = entry.find('atom:link', ns).attrib.get('href', '') if entry.find('atom:link', ns) is not None else ''
            
            # FIX 1: Ensure absolute URL
            full_link = raw_link
            if raw_link.startswith('/'):
                full_link = f"https://www.reddit.com{raw_link}"
            
            # FIX 2: Give a descending dummy score so the dashboard sorts correctly
            # (Higher index = older post = lower dummy score)
            dummy_score = 50 - i 
            
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

def fetch_reddit_posts(subreddit: str, time_filter: str) -> list:
    """PRIMARY: Fetches top posts via Public JSON."""
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t={time_filter}&limit=50"
    try:
        response = requests.get(url, headers=HEADERS, timeout=12)
        if response.status_code in [403, 429]:
            raise requests.exceptions.HTTPError(f"Rate limited: {response.status_code}")
        response.raise_for_status()
        data = response.json()
        
        posts = []
        for child in data.get('data', {}).get('children', []):
            post = child.get('data', {})
            posts.append({
                'id': post.get('id', ''),
                'title': post.get('title', ''),
                'selftext': post.get('selftext', ''),
                'permalink': post.get('permalink', ''),
                'score': post.get('score', 0)
            })
        return posts
    except Exception as e:
        print(f"  🔄 Primary (JSON) failed ({e}). Switching to Fallbacks...")
        
        # Chain 1: Try HTML (Secondary) - Better because it has SCORES
        html_posts = fetch_via_html(subreddit, time_filter)
        if html_posts: 
            return html_posts
            
        # Chain 2: Try RSS (Tertiary) - Last resort (No scores)
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
            time.sleep(2) 

if __name__ == "__main__":
    main()
