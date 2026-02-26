"""
Reddit Scraper Module — PRAW-based

WHAT IT DOES:
1. Fetches top posts from subreddits using PRAW (official Reddit API)
2. Stores posts in SQLite database (database.py)
3. Tracks seen posts to avoid duplicates
4. Supports both monthly and yearly time filters

KEY FEATURES:
- Uses official Reddit API (requires API keys in .env)
- Database-backed deduplication
- Detailed post metadata extraction
- Image/gallery detection

USAGE:
    python3 reddit_scraper.py

    # Or import and use programmatically:
    from reddit_scraper import RedditScraper
    scraper = RedditScraper()
    posts = scraper.daily_scrape()

DEPENDENCIES:
    - praw (pip install praw) - Official Reddit API wrapper
    - sqlalchemy (database.py)

IMPORTANT FOR LLMs:
- This is an ALTERNATIVE scraper to scrape_top.py
- Uses config.REDDIT_CLIENT_ID and config.REDDIT_CLIENT_SECRET for authentication
- Stores posts in database.py (SQLite), NOT in CSVs
- The dashboard uses CSV files, not this database
- Keys obtained from: https://www.reddit.com/prefs/apps (create "script" app)

NOTE:
    The dashboard does NOT use this scraper. It uses scrape_top.py which
    writes directly to CSV files. This module exists for advanced use cases.
"""
import logging
from datetime import datetime
from typing import List, Dict, Optional
import praw
from praw.models import Submission

import config
import database

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RedditScraper:
    """Reddit scraper using PRAW"""
    
    def __init__(self):
        """Initialize Reddit API client"""
        self.reddit = praw.Reddit(
            client_id=config.REDDIT_CLIENT_ID,
            client_secret=config.REDDIT_CLIENT_SECRET,
            user_agent=config.REDDIT_USER_AGENT
        )
        self.subreddits = config.SUBREDDITS
        self.posts_per_subreddit = config.POSTS_PER_SUBREDDIT
    
    def get_post_image_url(self, post: Submission) -> tuple:
        """
        Extract image URL from a post if available
        Returns: (is_image: bool, image_url: str)
        """
        # Check for image posts
        if post.is_video:
            return False, None
            
        # Check post hint for images
        if hasattr(post, 'post_hint') and post.post_hint == 'image':
            return True, post.url
            
        # Check for gallery posts
        if hasattr(post, 'is_gallery') and post.is_gallery:
            # Get first image from gallery
            if hasattr(post, 'gallery_data') and post.gallery_data:
                items = post.gallery_data.get('items', [])
                if items:
                    # Gallery URLs need special handling with media_metadata
                    return True, None  # Mark as image but we'll handle separately
                    
        # Check for external image links
        if any(post.url.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
            return True, post.url
            
        return False, None
    
    def scrape_subreddit(self, subreddit_name: str, time_filter: str = "month") -> List[Dict]:
        """
        Scrape top posts from a subreddit
        
        Args:
            subreddit_name: Name of the subreddit (without r/)
            time_filter: Time filter - 'month', 'year', 'week', 'day', 'hour', 'all'
            
        Returns:
            List of post dictionaries
        """
        logger.info(f"Scraping r/{subreddit_name} (time: {time_filter})")
        
        try:
            subreddit = self.reddit.subreddit(subreddit_name)
            posts = subreddit.top(time_filter=time_filter, limit=self.posts_per_subreddit)
            
            scraped_posts = []
            duplicates = 0
            new_posts = 0
            
            for post in posts:
                # Check if we've already seen this post
                if database.is_post_seen(post.id):
                    duplicates += 1
                    logger.debug(f"Skipping duplicate post: {post.id}")
                    continue
                
                # Extract image info
                is_image, image_url = self.get_post_image_url(post)
                
                # Create post dictionary
                post_data = {
                    'post_id': post.id,
                    'subreddit': subreddit_name,
                    'title': post.title,
                    'author': str(post.author) if post.author else "[deleted]",
                    'url': post.url,
                    'permalink': f"https://reddit.com{post.permalink}",
                    'score': post.score,
                    'num_comments': post.num_comments,
                    'created_utc': datetime.fromtimestamp(post.created_utc),
                    'time_filter': time_filter,
                    'selftext': post.selftext if hasattr(post, 'selftext') else None,
                    'is_image': is_image,
                    'image_url': image_url,
                    'is_shown': True
                }
                
                scraped_posts.append(post_data)
                new_posts += 1
                
                logger.info(f"New post: {post.title[:50]}... (r/{subreddit_name})")
            
            # Log scrape history
            database.add_scrape_history(
                subreddit=subreddit_name,
                posts_found=self.posts_per_subreddit,
                new_posts=new_posts,
                duplicates=duplicates
            )
            
            logger.info(f"r/{subreddit_name}: {new_posts} new, {duplicates} duplicates")
            return scraped_posts
            
        except Exception as e:
            logger.error(f"Error scraping r/{subreddit_name}: {e}")
            database.add_scrape_history(
                subreddit=subreddit_name,
                posts_found=0,
                new_posts=0,
                duplicates=0,
                errors=str(e)
            )
            return []
    
    def scrape_all_subreddits(self, time_filter: str = "month") -> List[Dict]:
        """
        Scrape all configured subreddits
        
        Args:
            time_filter: Time filter for posts
            
        Returns:
            List of all new posts
        """
        all_posts = []
        
        for subreddit in self.subreddits:
            subreddit_name = subreddit['name']
            posts = self.scrape_subreddit(subreddit_name, time_filter)
            all_posts.extend(posts)
        
        return all_posts
    
    def daily_scrape(self) -> int:
        """
        Perform daily scrape - first try monthly, then yearly
        Only adds posts we haven't seen before
        
        Returns:
            Number of new posts added
        """
        logger.info("Starting daily scrape...")
        
        # First, get top monthly posts
        monthly_posts = self.scrape_all_subreddits(time_filter="month")
        
        # Then, get top yearly posts (to fill in gaps)
        yearly_posts = self.scrape_all_subreddits(time_filter="year")
        
        # Combine and save all new posts
        all_posts = monthly_posts + yearly_posts
        
        saved_count = 0
        for post_data in all_posts:
            try:
                database.add_post(post_data)
                saved_count += 1
            except Exception as e:
                # Post might already exist (race condition)
                logger.debug(f"Post already exists: {post_data['post_id']}")
        
        logger.info(f"Daily scrape complete: {saved_count} new posts saved")
        return saved_count


def run_scrape():
    """Run the scraper - can be called from scheduler or CLI"""
    try:
        scraper = RedditScraper()
        new_posts = scraper.daily_scrape()
        print(f"Scraping complete! Added {new_posts} new posts.")
        return new_posts
    except Exception as e:
        print(f"Error during scraping: {e}")
        return 0


if __name__ == "__main__":
    run_scrape()
