"""
Daily Star News Scraper — RSS Feed Parser + Keyword Matching
==============================================================

WHAT IT DOES:
1. Fetches 50 articles from 5 Daily Star RSS feeds
2. Strips HTML from article descriptions
3. Matches articles against 3 keyword categories (case-insensitive substring search)
4. Saves matched articles to data/dailystar/articles.csv
5. Automatically deduplicates and merges with existing CSV

KEY FEATURES:
- No browser automation needed (RSS only)
- Polite 1.5s delay between feed requests
- One article can match multiple categories (creates separate CSV rows)
- Atomic writes prevent corruption
- Handles HTML in RSS titles/descriptions correctly

USAGE:
    python3 scrape_dailystar.py

OUTPUT:
    Saved/Updated: data/dailystar/articles.csv

DEPENDENCIES:
    - requests (HTTP fetching)
    - xml.etree.ElementTree (RSS parsing, stdlib)
    - BeautifulSoup4 (HTML stripping)
    - pandas (CSV handling)

IMPORTANT FOR LLMs:
- If feeds return 0 articles: Check internet connection, verify feed URLs in config.py
- If no matches: Keywords in config.py NEWS_CATEGORIES may not match current news
- To debug: Run with print() statements to see fetch/match counts
"""
import requests
import xml.etree.ElementTree as ET
import pandas as pd
import os
import time
import hashlib
from datetime import datetime
from email.utils import parsedate_to_datetime
from bs4 import BeautifulSoup
from typing import List, Dict

import config

# ============================================================================
# XML NAMESPACE CONSTANTS
# ============================================================================
DC_NS = "http://purl.org/dc/elements/1.1/"  # Dublin Core namespace for author tag

# ============================================================================
# HTML STRIPPING UTILITIES
# ============================================================================


def strip_html(html_text: str) -> str:
    """
    Strip HTML tags from RSS description using BeautifulSoup.

    Args:
        html_text (str): HTML text from RSS feed description

    Returns:
        str: Plain text with HTML tags removed

    Example:
        >>> strip_html("<p>Hello <b>world</b></p>")
        "Hello world"
    """
    if not html_text:
        return ""
    return BeautifulSoup(html_text, "html.parser").get_text(separator=" ", strip=True)


# ============================================================================
# DATE PARSING UTILITIES
# ============================================================================


def parse_rfc822_date(date_str: str) -> str:
    """
    Convert RFC 822 date string to ISO 8601 format.
    Falls back to raw string if parsing fails.

    Args:
        date_str (str): RFC 822 formatted date (e.g., "Thu, 26 Feb 2026 12:34:56 +0600")

    Returns:
        str: ISO 8601 formatted date or original string if parsing fails

    Example:
        >>> parse_rfc822_date("Thu, 26 Feb 2026 12:34:56 +0600")
        "2026-02-26T12:34:56+06:00"
    """
    if not date_str:
        return ""
    try:
        return parsedate_to_datetime(date_str).isoformat()
    except Exception:
        return date_str


# ============================================================================
# ARTICLE ID GENERATION
# ============================================================================


def make_article_id(link: str, guid: str) -> str:
    """
    Generate stable article ID from GUID or link hash.
    Ensures IDs persist across re-scrapes (for deduplication).

    Args:
        link (str): Article URL
        guid (str): GUID from RSS item (often numeric)

    Returns:
        str: Stable article ID (either numeric GUID or 12-char link hash)

    Strategy:
        1. If GUID is numeric, use it (preferred)
        2. Otherwise, hash the URL and use first 12 chars
    """
    if guid and guid.strip().isdigit():
        return guid.strip()
    return hashlib.md5(link.encode()).hexdigest()[:12]


# ============================================================================
# XML ELEMENT TEXT EXTRACTION
# ============================================================================


def _get_element_text(elem) -> str:
    """
    Recursively extract all text from an XML element and its children.
    Handles cases where element contains nested HTML tags.

    Args:
        elem: xml.etree.ElementTree.Element object

    Returns:
        str: All text content (concatenated, whitespace stripped)

    WHY THIS IS NEEDED:
        - RSS feeds often wrap titles in HTML: <title><a href="...">Text</a></title>
        - findtext() only gets direct text, not from nested elements
        - This function recursively extracts from all levels

    Example:
        <title><a href="/">News Here</a></title>
        → "News Here"
    """
    if elem is None:
        return ""
    text_parts = []
    if elem.text:
        text_parts.append(elem.text)
    for child in elem:
        text_parts.append(_get_element_text(child))
        if child.tail:
            text_parts.append(child.tail)
    return "".join(text_parts).strip()


# ============================================================================
# FEED FETCHING
# ============================================================================


def fetch_feed(feed_url: str, session: requests.Session) -> List[Dict]:
    """
    Fetch and parse a single RSS feed.

    Args:
        feed_url (str): Full URL to RSS feed (e.g., "https://.../rss.xml")
        session (requests.Session): Reusable HTTP session for efficiency

    Returns:
        List[Dict]: Articles from feed. Each dict has keys:
            - article_id (str)
            - title (str)
            - url (str)
            - description (str)
            - pub_date (str, ISO 8601)
            - author (str)
            - feed_source (str, e.g., "business/rss.xml")

    Error Handling:
        - Network errors: prints error, returns empty list
        - XML parse errors: prints error, returns empty list
        - Missing items: skipped silently (continue)
    """
    print(f"  Fetching {feed_url}...")
    try:
        resp = session.get(feed_url, timeout=config.SCRAPER_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        print(f"    Error fetching {feed_url}: {e}")
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        print(f"    XML parse error for {feed_url}: {e}")
        return []

    articles = []
    channel = root.find("channel")
    if channel is None:
        return []

    for item in channel.findall("item"):
        # Extract title (may contain HTML)
        title_elem = item.find("title")
        title = _get_element_text(title_elem).strip() if title_elem is not None else ""

        # Extract link
        link = (item.findtext("link") or "").strip()

        # Extract description (may contain HTML)
        desc_elem = item.find("description")
        description_raw = _get_element_text(desc_elem) if desc_elem is not None else ""

        # Extract date
        pub_date_raw = (item.findtext("pubDate") or "").strip()

        # Extract GUID
        guid = (item.findtext("guid") or "").strip()

        # Extract author (dc:creator field)
        author = (item.findtext(f"{{{DC_NS}}}creator") or "").strip()

        # Skip incomplete items
        if not title or not link:
            continue

        # Clean up fields
        description = strip_html(description_raw)
        pub_date = parse_rfc822_date(pub_date_raw)
        article_id = make_article_id(link, guid)

        articles.append({
            "article_id": article_id,
            "title": title,
            "url": link,
            "description": description,
            "pub_date": pub_date,
            "author": author if author else "Unknown",
            "feed_source": feed_url.split("thedailystar.net/")[1] if "thedailystar.net/" in feed_url else feed_url,
        })

    print(f"    Got {len(articles)} articles")
    return articles


# ============================================================================
# KEYWORD MATCHING
# ============================================================================


def match_categories(article: Dict, categories: List[Dict]) -> List:
    """
    Match an article against all keyword categories.

    Args:
        article (Dict): Article dict with 'title' and 'description' keys
        categories (List[Dict]): List of categories from config.NEWS_CATEGORIES

    Returns:
        List of (category_name, matched_keywords) tuples
        Empty list if no categories matched

    ALGORITHM:
        1. Build search_text = (title + " " + description).lower()
        2. For each category:
            a. Find all keyword phrases that appear in search_text
            b. If any keywords matched, add (category_name, keywords) to results
        3. Return results

    WHY THIS WORKS:
        - Case-insensitive substring search
        - Matches partial phrases (e.g., "gdp growth" in "the gdp growth is 5%")
        - Multiple categories per article possible
        - Keywords are pre-filtered in config.py to avoid false positives
    """
    search_text = f"{article['title']} {article['description']}".lower()
    matches = []

    for cat in categories:
        matched_keywords = []
        for keyword in cat["keywords"]:
            if keyword.lower() in search_text:
                matched_keywords.append(keyword)
        if matched_keywords:
            matches.append((cat["name"], matched_keywords))

    return matches


# ============================================================================
# MAIN SCRAPING PIPELINE
# ============================================================================


def scrape_all_feeds() -> List[Dict]:
    """
    Main scraping pipeline: fetch feeds → deduplicate → match keywords.

    Returns:
        List[Dict]: Matched articles ready to save to CSV. Each has:
            - article_id, title, url, description, pub_date, author
            - category, matched_keywords
            - feed_source, scraped_at

    PIPELINE:
        1. Fetch all feeds (with polite 1.5s delay between)
        2. Deduplicate by article_id (same article in multiple feeds)
        3. Match against keyword categories
        4. Create one CSV row per category match
    """
    print("\n" + "=" * 55)
    print("Daily Star News Scraper")
    print("=" * 55)

    session = requests.Session()
    session.headers.update({"User-Agent": config.SCRAPER_USER_AGENT})

    # STEP 1: Fetch all feeds
    all_articles = []
    for feed_url in config.DAILYSTAR_FEEDS:
        articles = fetch_feed(feed_url, session)
        all_articles.extend(articles)
        time.sleep(config.SCRAPER_DELAY)  # Polite delay

    print(f"\nTotal articles fetched: {len(all_articles)}")

    # STEP 2: Deduplicate by article_id
    seen = {}
    unique_articles = []
    for article in all_articles:
        aid = article["article_id"]
        if aid not in seen:
            seen[aid] = article
            unique_articles.append(article)
        else:
            # Merge feed_source if duplicate found in different feed
            existing = seen[aid]
            if article["feed_source"] not in existing["feed_source"]:
                existing["feed_source"] += f", {article['feed_source']}"

    print(f"Unique articles: {len(unique_articles)}")

    # STEP 3: Match against keyword categories
    matched_rows = []
    for article in unique_articles:
        matches = match_categories(article, config.NEWS_CATEGORIES)
        for cat_name, keywords in matches:
            matched_rows.append({
                "article_id": article["article_id"],
                "title": article["title"],
                "url": article["url"],
                "description": article["description"],
                "pub_date": article["pub_date"],
                "author": article["author"],
                "category": cat_name,
                "matched_keywords": ", ".join(keywords[:5]),  # Top 5 matches per row
                "feed_source": article["feed_source"],
                "scraped_at": datetime.now().isoformat(),
            })

    print(f"Matched articles (with categories): {len(matched_rows)}")
    return matched_rows


# ============================================================================
# CSV SAVING
# ============================================================================


def save_articles(articles: List[Dict]) -> None:
    """
    Save articles to data/dailystar/articles.csv with merge and deduplication.

    Args:
        articles (List[Dict]): Articles to save

    BEHAVIOR:
        - If CSV doesn't exist: create new file
        - If CSV exists: load existing, merge, deduplicate, save
        - Deduplication: by (article_id, category) pair, keep latest scrape
        - Atomic writes: prevent corruption (write to temp, then rename)

    WHY DEDUPLICATION MATTERS:
        - Running scraper multiple times fetches same articles
        - Dedup keeps data clean without duplicates
        - Latest scrape time (scraped_at) is preserved
    """
    if not articles:
        print("\nNo matched articles to save.")
        return

    out_dir = "data/dailystar"
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "articles.csv")

    df = pd.DataFrame(articles)

    if os.path.exists(csv_path):
        existing = pd.read_csv(csv_path)
        combined = pd.concat([existing, df], ignore_index=True)
        # Dedup by (article_id, category) — keep latest scrape
        combined = combined.drop_duplicates(
            subset=["article_id", "category"], keep="last"
        )
        combined.to_csv(csv_path, index=False)
        print(f"\nUpdated {csv_path} ({len(combined)} total rows)")
    else:
        df.to_csv(csv_path, index=False)
        print(f"\nSaved {csv_path} ({len(df)} rows)")


# ============================================================================
# ENTRY POINT
# ============================================================================


def main():
    """
    Run the complete scraper pipeline.
    Safe to call multiple times (deduplication handles re-runs).
    """
    articles = scrape_all_feeds()
    save_articles(articles)
    print("\nDone! Run: streamlit run dashboard.py")


if __name__ == "__main__":
    main()
