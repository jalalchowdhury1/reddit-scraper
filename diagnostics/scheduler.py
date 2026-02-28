"""
Daily Scheduler for Reddit Daily Dashboard

WHAT IT DOES:
1. Runs scheduled scraping of all data sources at 8:00 AM daily
2. Scrapes Reddit posts (monthly + yearly) via scraper_main.py
3. Scrapes Daily Star news via scrape_dailystar.py
4. Scrapes Ritholtz AM Reads via scrape_ritholtz.py

KEY FEATURES:
- Runs as a background daemon or one-time job
- Uses Python schedule library for cron-like functionality
- Logs all scraping activities with timestamps

USAGE:
    # Run once immediately
    python3 scheduler.py

    # Or import and run in background:
    from scheduler import start_scheduler_background
    start_scheduler_background()

DEPENDENCIES:
    - schedule (pip install schedule)
    - subprocess (stdlib)

IMPORTANT FOR LLMs:
- Uses config.SUBREDDITS for subreddit list (single source of truth)
- Calls scraper_main.py for Reddit scraping (not scrape_top.py)
- This scheduler is separate from the dashboard - runs independently

TODO FOR LLM OPTIMIZATION:
- Add error handling with retry logic
- Add email/notification on failure
- Consider using APScheduler for more robust scheduling
"""
import time
import logging
from datetime import datetime
import schedule
import threading
import subprocess
import sys
from pathlib import Path

import config

# ============================================================================
# LOGGING SETUP
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Subreddits to scrape (from config.py - single source of truth)
SUBREDDITS = [s["name"] for s in config.SUBREDDITS]

POSTS_PER_SUBREDDIT = 10  # Get more posts to filter duplicates


def run_daily_scrape():
    """Run the daily scrape for all sources"""
    logger.info("=" * 50)
    logger.info("Starting scheduled daily scrape...")
    logger.info(f"Time: {datetime.now()}")
    logger.info("=" * 50)
    
    # Scrape Reddit posts
    for subreddit in SUBREDDITS:
        try:
            logger.info(f"Scraping r/{subreddit}...")
            # Run the universal scraper for each subreddit
            result = subprocess.run(
                [sys.executable, "scraper_main.py", subreddit, 
                 "--mode", "history", 
                 "--limit", str(POSTS_PER_SUBREDDIT)],
                capture_output=True,
                text=True,
                cwd=Path(__file__).parent
            )
            if result.returncode == 0:
                logger.info(f"Successfully scraped r/{subreddit}")
            else:
                logger.error(f"Error scraping r/{subreddit}: {result.stderr}")
        except Exception as e:
            logger.error(f"Exception scraping r/{subreddit}: {e}")
    
    # Scrape Daily Star news
    try:
        logger.info("Scraping Daily Star news...")
        result = subprocess.run(
            [sys.executable, "scrape_dailystar.py"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent
        )
        if result.returncode == 0:
            logger.info("Successfully scraped Daily Star news")
        else:
            logger.error(f"Error scraping Daily Star: {result.stderr}")
    except Exception as e:
        logger.error(f"Exception scraping Daily Star: {e}")
    
    # Scrape Ritholtz AM Reads
    try:
        logger.info("Scraping Ritholtz AM Reads...")
        result = subprocess.run(
            [sys.executable, "scrape_ritholtz.py"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent
        )
        if result.returncode == 0:
            logger.info("Successfully scraped Ritholtz AM Reads")
        else:
            logger.error(f"Error scraping Ritholtz: {result.stderr}")
    except Exception as e:
        logger.error(f"Exception scraping Ritholtz: {e}")
    
    logger.info("=" * 50)
    logger.info("Daily scrape completed!")
    logger.info("=" * 50)



def run_scheduler():
    """Run the scheduler in a loop"""
    # Schedule the scrape to run daily at a specific time
    # You can adjust the time as needed
    schedule.every().day.at("08:00").do(run_daily_scrape)
    
    # Also run every hour for testing (uncomment in production)
    # schedule.every().hour.do(run_daily_scrape)
    
    logger.info("Scheduler started. Daily scrape scheduled for 8:00 AM.")
    logger.info("Press Ctrl+C to stop.")
    
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute


def start_scheduler_background():
    """Start the scheduler in a background thread"""
    thread = threading.Thread(target=run_scheduler, daemon=True)
    thread.start()
    logger.info("Background scheduler started.")
    return thread


if __name__ == "__main__":
    # Run once immediately to test
    print("Running initial scrape...")
    run_daily_scrape()
    
    # Then start the scheduler
    print("\nStarting scheduler...")
    run_scheduler()
