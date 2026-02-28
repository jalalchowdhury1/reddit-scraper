import requests
import xml.etree.ElementTree as ET
import pandas as pd
import os
import time
import hashlib
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import List, Dict

# Broad search queries to cast a net (we will strictly filter the results locally)
QUERIES = [
    "Bangladesh Economy",
    "Bangladesh India",
    "Bangladesh business"
]

# Comprehensive blocklist of Indian news sources
BLOCKED_SOURCES = [
    "times of india", "the hindu", "hindustan times", "ndtv", "indian express", 
    "news18", "firstpost", "wion", "india today", "business standard", 
    "livemint", "mint", "deccan herald", "economic times", "the wire", 
    "scroll.in", "the quint", "abp news", "zee news", "ani", "republic", 
    "theprint", "outlook india", "telegraph india", "dd news", "swarajya",
    "the statesman", "business today", "financial express", "free press journal"
]

# The user's strict phrase requirements
STRICT_FILTERS = {
    'India–Bangladesh Relations': [
        'india bangladesh', 'bilateral relations', 'transit corridor', 'energy pipeline', 'river link', 'land port', 'rail link', 'road link', 'bus service', 'visa agreement', 'trade agreement', 'water sharing treaty', 'border security', 'defence cooperation', 'bangladesh india', 'india and bangladesh', 'bangladesh and india', 'indo-bangladesh', 'bangladesh-india', 'india–bangladesh', 'bangladesh–india', 'bilateral ties', 'bilateral relationship', 'diplomatic relations', 'diplomatic ties', 'two-way relations', 'two-way ties', 'energy pipelines', 'oil pipeline', 'oil pipelines', 'gas pipeline', 'gas pipelines', 'energy conduit', 'river links', 'river linking', 'waterway link', 'waterway links', 'river connection', 'river connections', 'visa agreements', 'visa pact', 'visa pacts', 'visa deal', 'visa deals', 'trade agreements', 'trade pact', 'trade pacts', 'free trade agreement', 'fta', 'ftas', 'water sharing treaties', 'river water sharing treaty', 'river water sharing treaties', 'water sharing pact', 'water sharing pacts', 'water treaty', 'border security measures', 'border controls', 'border control', 'border protection', 'border enforcement', 'border guard', 'border guards', 'benapole railway station', 'benapole rail link', 'benapole rail', 'benapole railways', 'defense cooperation', 'defence collaboration', 'defense collaboration', 'military cooperation', 'military collaboration', 'defence cooperation agreement', 'defense cooperation agreement'
    ],
    'Bangladesh Economy': [
        'export growth', 'garment sector', 'textile export', 'foreign direct investment', 'exchange rate', 'fiscal deficit', 'monetary policy', 'interest rate', 'gdp growth', 'remittance inflow', 'stock market', 'share price', 'inflation rate', 'textile industry', 'agribusiness sector', 'banking sector', 'budget proposal', 'tax revenue', 'central bank', 'manufacturing output', 'interest payments', 'interest payment', 'exports growth', 'export expansion', 'exports expansion', 'growth in exports', 'export volumes growth', 'increase in exports', 'garment industry', 'apparel sector', 'apparel industry', 'clothing sector', 'clothing industry', 'textile exports', 'textiles export', 'textiles exports', 'textile export volumes', 'export of textiles', 'fdi', 'direct foreign investment', 'foreign investment', 'inward fdi', 'exchange rates', 'currency exchange rate', 'currency rate', 'fx rate', 'forex rate', 'exchange-rate', 'budget deficit', 'fiscal shortfall', 'budget shortfall', 'fiscal gap', 'monetary policies', 'central bank policy', 'central bank policies', 'interest rates', 'borrowing rate', 'lending rate', 'cost of borrowing', 'gross domestic product growth', 'gdp expansion', 'economic growth', 'remittance inflows', 'remittance receipts', 'inflows of remittances', 'worker remittances', 'remittance income', 'equity market', 'share market', 'capital market', 'stock markets', 'share prices', 'stock price', 'stock prices', 'equity price', 'equity prices', 'inflation rates', 'rate of inflation', 'price inflation', 'textiles industry', 'textile industries', 'textiles industries', 'agribusiness', 'agricultural business sector', 'agricultural sector', 'agri-business sector', 'banking industry', 'banks sector', 'financial sector', 'budget proposals', 'budget plan', 'fiscal proposal', 'budget draft', 'tax revenues', 'tax receipts', 'tax collection', 'tax collections', 'central banks', 'reserve bank', 'monetary authority', 'industrial output', 'manufacturing production', 'manufacturing outputs', 'interest expenses', 'interest expense', 'debt service', 'debt servicing', 'interest paid'
    ],
    'Good News': [
        'success story', 'record achievement', 'inaugurated today', 'funded by', 'donation drive', 'rescue operation', 'medical breakthrough', 'education initiative', 'vaccination campaign', 'community uplift', 'peace accord', 'celebration held', 'technology startup', 'innovation hub', 'sports championship', 'cultural festival', 'success stories', 'achievement story', 'success narrative', 'case study', 'case studies', 'success example', 'success examples', 'record achievements', 'record-breaking achievement', 'record-breaking achievements', 'milestone achievement', 'record feat', 'record feats', 'inaugurated', 'officially inaugurated', 'opened today', 'inaugurated this morning', 'inaugurated this afternoon', 'launching new', 'unveiled new', 'debuted new', 'introduced new', 'launched the new', 'funded through', 'financed by', 'backed by', 'supported by', 'sponsored by', 'donation drives', 'donation campaign', 'fundraising drive', 'fundraising campaign', 'charity drive', 'charity campaign', 'donation fundraiser', 'fundraising event', 'rescue operations', 'rescue mission', 'search and rescue operation', 'emergency rescue operation', 'rescue efforts', 'evacuation operation', 'medical breakthroughs', 'healthcare breakthrough', 'scientific breakthrough', 'medical advance', 'medical advances', 'health breakthrough', 'educational initiative', 'education initiatives', 'learning initiative', 'education program', 'education programs', 'vaccination campaigns', 'vaccination drive', 'immunization campaign', 'immunisation campaign', 'immunization drive', 'immunisation drive', 'vaccination program', 'immunization program', 'immunisation program', 'community upliftment', 'community empowerment', 'community development', 'community advancement', 'community uplift initiatives', 'peace accords', 'peace agreement', 'peace agreements', 'peace treaty', 'peace treaties', 'peace pact', 'peace pacts', 'celebration conducted', 'event held', 'festivity held', 'celebration took place', 'celebration organised', 'celebration organized', 'tech startup', 'technology startups', 'tech startups', 'startup technology company', 'startup', 'innovation centre', 'innovation center', 'innovation hubs', 'innovation centers', 'innovation park', 'innovation parks', 'cultural festivals', 'cultural event', 'arts festival', 'culture festival', 'heritage festival', 'cultural celebrations'
    ]
}

def parse_rfc822_date(date_str: str) -> str:
    if not date_str: return ""
    try: return parsedate_to_datetime(date_str).isoformat()
    except: return date_str

def get_category_for_article(title: str, description: str) -> str:
    """Checks if the article contains any of the strict required phrases using exact word boundaries."""
    text_to_search = f"{title} {description}"
    
    for category, phrases in STRICT_FILTERS.items():
        for phrase in phrases:
            # \b ensures we match whole words only (e.g., 'fdi' won't match inside 'offdir')
            pattern = rf"\b{re.escape(phrase)}\b"
            if re.search(pattern, text_to_search, re.IGNORECASE):
                return category
    return None

def scrape_google_news() -> List[Dict]:
    print("="*50)
    print("🌐 Google News Aggregator (Strictly Filtered)")
    print("="*50)
    
    all_articles = []
    seen_urls = set()
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

    for query_str in QUERIES:
        url = f"https://news.google.com/rss/search?q={query_str.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
        print(f"📡 Sweeping broad query: '{query_str}'...")
        
        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            
            channel = root.find("channel")
            if channel is None: continue
            
            for item in channel.findall("item"):
                source = (item.findtext("source") or "Google News").strip()
                
                # --- FILTER 1: Skip Indian Sources ---
                if any(blocked in source.lower() for blocked in BLOCKED_SOURCES):
                    continue
                
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                description = (item.findtext("description") or "").strip()
                pub_date_raw = (item.findtext("pubDate") or "").strip()
                
                if not title or not link or link in seen_urls: continue
                
                # --- FILTER 2: Strict phrase requirement ---
                matched_category = get_category_for_article(title, description)
                if not matched_category:
                    continue # Dropped! Did not contain required keywords.
                
                if " - " in title:
                    title = title.rsplit(" - ", 1)[0]
                    
                pub_date = parse_rfc822_date(pub_date_raw)
                article_id = hashlib.md5(link.encode()).hexdigest()[:15]
                
                seen_urls.add(link)
                all_articles.append({
                    "article_id": article_id,
                    "title": title,
                    "url": link,
                    "description": "",
                    "pub_date": pub_date,
                    "author": source, 
                    "category": matched_category, # Uses the exact name from your JS array
                    "scraped_at": datetime.now().isoformat()
                })
        except Exception as e:
            print(f"❌ Error fetching '{query_str}': {e}")
        time.sleep(1.5)
        
    return all_articles

def save_articles(articles: List[Dict]):
    if not articles:
        print("No articles passed the strict filters.")
        return
        
    out_dir = "data/googlenews"
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "articles.csv")
    
    df = pd.DataFrame(articles)
    if os.path.exists(csv_path):
        existing = pd.read_csv(csv_path)
        combined = pd.concat([existing, df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["article_id", "category"], keep="last")
        combined.to_csv(csv_path, index=False)
        print(f"✅ Updated {csv_path} ({len(combined)} total rows)")
    else:
        df.to_csv(csv_path, index=False)
        print(f"✅ Saved {csv_path} ({len(df)} rows)")

if __name__ == "__main__":
    articles = scrape_google_news()
    save_articles(articles)
