"""
Read Trung (SatPost) RSS Scraper
================================
Fetches the latest newsletters from Trung Phan's Substack RSS feed.
Extracts title, URL, clean description, and publication date.
"""
import os
import hashlib
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
from email.utils import parsedate_to_datetime

FEED_URL = "https://www.readtrung.com/feed"
OUTPUT_DIR = "data/trung"
OUTPUT_FILE = f"{OUTPUT_DIR}/articles.csv"

def make_article_id(url: str) -> str:
    """Generate a stable 12-character MD5 hash from the URL."""
    return hashlib.md5(url.encode()).hexdigest()[:12]

def clean_html(raw_html: str) -> str:
    """Safely strip HTML tags to get plain text."""
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    return soup.get_text(separator=" ", strip=True)

def scrape_satpost():
    print(f"Fetching SatPost RSS from {FEED_URL}...")
    headers = {"User-Agent": "DailyReader/1.0 (SatPost RSS Scraper)"}
    
    try:
        response = requests.get(FEED_URL, headers=headers, timeout=30)
        response.raise_for_status()
    except Exception as e:
        print(f"Error fetching RSS feed: {e}")
        return

    # Parse XML
    soup = BeautifulSoup(response.content, "xml")
    items = soup.find_all("item")
    
    articles = []
    for item in items[:20]:  # Limit to latest 20
        title = item.find("title").text.strip() if item.find("title") else "Untitled"
        link = item.find("link").text.strip() if item.find("link") else ""
        
        # Substack uses <content:encoded> for the full body, or <description>
        content_tag = item.find("content:encoded")
        raw_content = content_tag.text if content_tag else (item.find("description").text if item.find("description") else "")
        
        # We only need a short description for the main branch UI
        clean_desc = clean_html(raw_content)[:300]
        
        # Parse RFC-822 date to standard ISO format (YYYY-MM-DD)
        pub_date_str = item.find("pubDate").text if item.find("pubDate") else ""
        try:
            dt = parsedate_to_datetime(pub_date_str)
            iso_date = dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            iso_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        article_id = make_article_id(link)

        articles.append({
            "article_id": article_id,
            "title": title,
            "url": link,
            "description": clean_desc,
            "pub_date": iso_date,
            "scraped_at": datetime.now().isoformat()
        })

    if articles:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        df = pd.DataFrame(articles)
        df.to_csv(OUTPUT_FILE, index=False)
        print(f"Successfully saved {len(articles)} SatPost articles to {OUTPUT_FILE}")
    else:
        print("No articles found in the feed.")

if __name__ == "__main__":
    scrape_satpost()