import os
import csv
import time
from scraper_utils import fetch_top_posts, extract_post_data

SUBREDDITS = [
    "dataisbeautiful",
    "todayilearned",
    "books",
    "fitness",
    "getmotivated",
    "unethicallifeprotips",
    "lifeprotips",
    "truereddit",
    "upliftingnews",
    "lifehacks",
    "productivity",
    "personalfinance"
]

SEEN_POSTS_FILE = "seen_posts.csv"

def load_seen_posts():
    """Loads IDs of already seen posts."""
    seen = set()
    if os.path.exists(SEEN_POSTS_FILE):
        try:
            with open(SEEN_POSTS_FILE, mode='r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    seen.add(row['id'])
        except Exception:
            pass
    return seen

def save_seen_posts(new_ids):
    """Appends new post IDs to the seen posts file."""
    if not new_ids:
        return
    file_exists = os.path.exists(SEEN_POSTS_FILE)
    with open(SEEN_POSTS_FILE, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['id'])
        if not file_exists:
            writer.writeheader()
        for pid in new_ids:
            writer.writerow({'id': pid})

def get_highlights(subs=None):
    seen_ids = load_seen_posts()
    newly_seen = []
    
    highlights = {}
    target_subs = subs if subs is not None else SUBREDDITS

    for sub in target_subs:
        print(f"🔍 Fetching r/{sub}...")
        highlights[sub] = {"month": [], "year": []}
        
        # Fetch Month
        month_posts = fetch_top_posts(sub, t='month', limit=10)
        for p in month_posts:
            data = extract_post_data(p['data'])
            if data['id'] not in seen_ids:
                highlights[sub]["month"].append(data)
                newly_seen.append(data['id'])
                seen_ids.add(data['id'])
            if len(highlights[sub]["month"]) >= 5:
                break
        
        # Avoid rate limiting
        time.sleep(1)
        
        # Fetch Year
        year_posts = fetch_top_posts(sub, t='year', limit=10)
        for p in year_posts:
            data = extract_post_data(p['data'])
            if data['id'] not in seen_ids:
                highlights[sub]["year"].append(data)
                newly_seen.append(data['id'])
                seen_ids.add(data['id'])
            if len(highlights[sub]["year"]) >= 5:
                break
        
        time.sleep(1)
                    
    save_seen_posts(newly_seen)
    return highlights

def print_highlights(highlights):
    print("\n" + "="*60)
    print("🌟 REDDIT TRENDING HIGHLIGHTS 🌟")
    print("="*60)
    
    any_new = False
    for sub, periods in highlights.items():
        if not periods['month'] and not periods['year']:
            continue
            
        any_new = True
        print(f"\n--- r/{sub} ---")
        
        if periods['month']:
            print(f"  📅 Top 5 This Month:")
            for i, post in enumerate(periods['month'], 1):
                print(f"    {i}. {post['title']}")
                print(f"       Score: {post['score']} | {post['permalink']}")
        
        if periods['year']:
            print(f"  🗓️ Top 5 This Year:")
            for i, post in enumerate(periods['year'], 1):
                print(f"    {i}. {post['title']}")
                print(f"       Score: {post['score']} | {post['permalink']}")

    if not any_new:
        print("\n😴 No new trending posts found today!")
    
    print("\n" + "="*60)

if __name__ == "__main__":
    import sys
    
    # Simple test mode
    if "--test" in sys.argv:
        SUBREDDITS = ["dataisbeautiful"]
        print("🧪 Running in TEST mode (one subreddit only)")

    results = get_highlights()
    print_highlights(results)
