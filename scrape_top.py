import requests
import pandas as pd
import time
from pathlib import Path

# Subreddits extracted from the user's logs
SUBREDDITS = [
    "dataisbeautiful", "todayilearned", "sobooksoc", "Fitness", 
    "getmotivated", "UnethicalLifeProTips", "LifeProTips", 
    "TrueReddit", "UpliftingNews", "lifehacks", "Productivity", 
    "PersonalFinance", "explainlikeimfive"
]

def fetch_reddit_posts(subreddit: str, time_filter: str) -> list:
    """Fetches top posts from a subreddit using Reddit's public JSON endpoint."""
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t={time_filter}&limit=50"
    # A standard web browser User-Agent is critical to avoid immediate blocking
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
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
    except requests.exceptions.RequestException as e:
        print(f"❌ Error fetching r/{subreddit} ({time_filter}): {e}")
        return []

def save_posts_to_csv(posts: list, subreddit: str, time_filter: str):
    """Saves the fetched posts to the CSV directory structure expected by FastAPI."""
    if not posts:
        return
        
    # Determine folder name based on the FastAPI expectations
    folder_suffix = "_yearly" if time_filter == "year" else ""
    folder_path = Path(f"data/r_{subreddit}{folder_suffix}")
    folder_path.mkdir(parents=True, exist_ok=True)
    
    csv_path = folder_path / "posts.csv"
    df = pd.DataFrame(posts)
    df.to_csv(csv_path, index=False)
    print(f"✅ Saved {len(posts)} posts to {csv_path}")

def main():
    print("="*50)
    print("🚀 Reddit Scraper (Public JSON Method - No API Keys)")
    print("="*50)
    
    for sub in SUBREDDITS:
        # Fetch Monthly
        print(f"📡 Fetching r/{sub} (Monthly)...")
        monthly_posts = fetch_reddit_posts(sub, "month")
        save_posts_to_csv(monthly_posts, sub, "month")
        time.sleep(1.5) # Polite delay to prevent rate-limiting
        
        # Fetch Yearly
        print(f"📡 Fetching r/{sub} (Yearly)...")
        yearly_posts = fetch_reddit_posts(sub, "year")
        save_posts_to_csv(yearly_posts, sub, "year")
        time.sleep(1.5) # Polite delay

    print("\n🎉 Reddit scraping complete!")

if __name__ == "__main__":
    main()
