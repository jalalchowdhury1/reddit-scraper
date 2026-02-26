"""
Reddit Top Posts Scraper — Monthly & Yearly Top Posts

WHAT IT DOES:
1. Fetches top posts from 13 subreddits using old.reddit.com JSON API
2. Saves monthly posts to data/r_<subreddit>/posts.csv
3. Saves yearly posts to data/r_<subreddit>_yearly/posts.csv
4. Merges with existing CSV files (deduplicates by post ID)

KEY FEATURES:
- Simple, lightweight scraping (no API keys required)
- Uses old.reddit.com JSON endpoints (reliable mirror)
- Deduplication prevents duplicate posts across runs
- 1 second delay between requests (rate limiting)

USAGE:
    python3 scrape_top.py

OUTPUT:
    data/r_<subreddit>/posts.csv (monthly)
    data/r_<subreddit>_yearly/posts.csv (yearly)

DEPENDENCIES:
    - requests (HTTP fetching)
    - pandas (CSV handling)

IMPORTANT FOR LLMs:
- Subreddits are defined in config.py → SUBREDDITS list
- This scraper does NOT use the database (database.py is unused)
- Uses config.POSTS_PER_SUBREDDIT for post count
- Dashboard loads from CSVs, not database

TODO FOR LLM OPTIMIZATION:
- Add try/except around HTTP requests with proper error logging
- Add input validation for subreddit names
- Consider adding retry logic for failed requests
"""
import requests
import pandas as pd
import time
from datetime import datetime
import os
import logging
from typing import List, Dict, Optional

import config

# ============================================================================
# LOGGING SETUP
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================
# Reddit mirrors (old.reddit.com works best for JSON)
MIRRORS = [
    "https://old.reddit.com",
]

USER_AGENT = "RedditDaily/1.0"

# Subreddits to scrape (from config.py - single source of truth)
# Note: Using config.SUBREDDITS for consistency
SUBREDDITS = [s["name"] for s in config.SUBREDDITS]

POSTS_PER_SUBREDDIT = config.POSTS_PER_SUBREDDIT


def get_top_posts(subreddit, time_filter="month", limit=20):
    """
    Get top posts from a subreddit for a specific time period
    
    Args:
        subreddit: Subreddit name (without r/)
        time_filter: 'month' or 'year'
        limit: Number of posts to fetch
    """
    print(f"📡 Fetching r/{subreddit} top {time_filter}...")
    
    base_url = f"{MIRRORS[0]}/r/{subreddit}/top.json?t={time_filter}&limit={limit}"
    
    headers = {"User-Agent": USER_AGENT}
    
    try:
        response = requests.get(base_url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        posts = []
        children = data.get('data', {}).get('children', [])
        
        for child in children:
            p = child['data']
            
            # Determine post type
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
            
            post = {
                "id": p.get('id'),
                "title": p.get('title'),
                "author": p.get('author'),
                "created_utc": datetime.fromtimestamp(p.get('created_utc', 0)).isoformat(),
                "permalink": p.get('permalink'),
                "url": p.get('url_overridden_by_dest', p.get('url')),
                "score": p.get('score', 0),
                "upvote_ratio": p.get('upvote_ratio', 0),
                "num_comments": p.get('num_comments', 0),
                "num_crossposts": p.get('num_crossposts', 0),
                "selftext": p.get('selftext', ''),
                "post_type": post_type,
                "is_nsfw": p.get('over_18', False),
                "is_spoiler": p.get('spoiler', False),
                "flair": p.get('link_flair_text', ''),
                "total_awards": p.get('total_awards_received', 0),
                "has_media": p.get('is_video', False) or p.get('is_gallery', False),
                "media_downloaded": False,
                "time_filter": time_filter,
                "source": f"Top-{time_filter}"
            }
            posts.append(post)
        
        print(f"   ✅ Got {len(posts)} posts from r/{subreddit}")
        return posts
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return []


def save_posts(posts, subreddit, time_filter):
    """Save posts to CSV file"""
    if not posts:
        return
    
    # Create data directory
    os.makedirs("data", exist_ok=True)
    
    # For monthly posts, use r_ prefix; for yearly, use a separate file
    if time_filter == "month":
        filename = f"data/r_{subreddit}/posts.csv"
    else:
        filename = f"data/r_{subreddit}_yearly/posts.csv"
    
    # Create subreddit directory
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    
    df = pd.DataFrame(posts)
    
    if os.path.exists(filename):
        # Load existing and merge
        existing_df = pd.read_csv(filename)
        
        # Combine and remove duplicates by post ID
        combined = pd.concat([existing_df, df], ignore_index=True)
        combined = combined.drop_duplicates(subset=['id'], keep='first')
        
        combined.to_csv(filename, index=False)
        print(f"   💾 Updated {filename} ({len(combined)} total posts)")
    else:
        df.to_csv(filename, index=False)
        print(f"   💾 Saved {filename}")


def scrape_all_top(time_filter="month"):
    """Scrape top posts from all subreddits"""
    print(f"\n{'='*50}")
    print(f"🗓️ SCRAPING TOP POSTS - {time_filter.upper()}")
    print(f"{'='*50}\n")
    
    all_posts = []
    
    for subreddit in SUBREDDITS:
        posts = get_top_posts(subreddit, time_filter, POSTS_PER_SUBREDDIT)
        
        if posts:
            save_posts(posts, subreddit, time_filter)
            all_posts.extend(posts)
        
        time.sleep(1)  # Rate limiting
    
    print(f"\n{'='*50}")
    print(f"✅ COMPLETE! Scraped {len(all_posts)} {time_filter}ly posts")
    print(f"{'='*50}\n")
    
    return all_posts


def main():
    """Main function"""
    print("Reddit Top Posts Scraper")
    print("=" * 40)
    
    # Scrape monthly top posts
    print("\n📅 Step 1: Scraping top monthly posts...")
    scrape_all_top("month")
    
    # Scrape yearly top posts
    print("\n📅 Step 2: Scraping top yearly posts...")
    scrape_all_top("year")
    
    print("\n🎉 All scraping complete!")
    print("Run: streamlit run dashboard.py")
    print("Then refresh your browser at http://localhost:8501")


if __name__ == "__main__":
    main()
