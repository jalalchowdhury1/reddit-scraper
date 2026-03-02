import requests
import pandas as pd
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timedelta, timezone
import email.utils
import os

FEEDS = {
    "CFR": "https://www.cfr.org/rss",
    "Chatham House": "https://www.chathamhouse.org/rss.xml",
    "RUSI": "https://rusi.org/rss.xml",
    "Brookings": "https://www.brookings.edu/feed/",
    "CSIS": "https://www.csis.org/analysis/rss",
    "RAND": "https://www.rand.org/analysis.xml/feed",
    "Wilson Center": "https://www.wilsoncenter.org/rss.xml",
    "ECFR": "https://ecfr.eu/feed/"
}

HEADERS = {"User-Agent": "Mozilla/5.0 DailyReaderScraper/1.0"}

def fetch_feed(name, url):
    print(f"📡 Fetching {name}...")
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        root = ET.fromstring(response.content)

        articles = []
        # Handle both RSS 2.0 and Atom
        items = root.findall('.//item')
        if not items:
            items = root.findall('.//{http://www.w3.org/2005/Atom}entry')
        
        # Calculate the cutoff date (30 days ago) - make it timezone-aware
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
        
        for item in items:
            title = item.findtext('title') or item.findtext('{http://www.w3.org/2005/Atom}title')
            link = item.findtext('link')
            if link is None:
                link_elem = item.find('{http://www.w3.org/2005/Atom}link')
                link = link_elem.attrib.get('href') if link_elem is not None else ""
            
            desc = item.findtext('description') or item.findtext('{http://www.w3.org/2005/Atom}summary') or ""
            pub_date_str = item.findtext('pubDate') or item.findtext('{http://www.w3.org/2005/Atom}published') or ""
            
            # Parse the date and check if it's within 30 days
            pub_date = None
            if pub_date_str:
                try:
                    pub_date = email.utils.parsedate_to_datetime(pub_date_str)
                    # Skip articles older than 30 days
                    if pub_date < cutoff_date:
                        continue
                    # Convert to ISO format for storage
                    pub_date_iso = pub_date.isoformat()
                except Exception:
                    pub_date_iso = pub_date_str
            else:
                pub_date_iso = ""
            
            articles.append({
                "article_id": hash(link),
                "title": title,
                "url": link,
                "description": desc[:500],
                "pub_date": pub_date_iso,
                "source": name
            })
        return articles
    except Exception as e:
        print(f"  ❌ Failed to fetch {name}: {e}")
        return []

def main():
    # Delete old data file if it exists
    output_path = Path("data/thinktanks/articles.csv")
    if output_path.exists():
        os.remove(output_path)
        print(f"🗑️ Deleted old data file: {output_path}")
    
    all_articles = []
    for name, url in FEEDS.items():
        all_articles.extend(fetch_feed(name, url))

    if all_articles:
        df = pd.DataFrame(all_articles)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)
        print(f"✅ Saved {len(all_articles)} articles to {output_path}")
    else:
        print("⚠️ No articles fetched.")

if __name__ == "__main__":
    main()
