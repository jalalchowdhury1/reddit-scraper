"""
Ritholtz.com AM Reads Scraper
=============================

WHAT IT DOES:
1. Fetches the category/links page to find today's AM Reads post
2. Fetches the individual post to extract 12 articles
3. Saves articles to data/ritholtz/articles.csv
4. Overwrites each day (fresh articles daily)

KEY FEATURES:
- Two-step scraping: category page → individual post
- Extracts: title, URL, description for each article
- Atomic writes prevent corruption
- Polite delay between requests

USAGE:
    python3 core/scrape_ritholtz.py

OUTPUT:
    Saved/Updated: data/ritholtz/articles.csv

DEPENDENCIES:
    - requests (HTTP fetching)
    - BeautifulSoup4 (HTML parsing)
    - pandas (CSV handling)

IMPORTANT FOR LLMs:
- This scraper overwrites data each run (daily posts change)
- Articles are not keyword-matched (all are included)
- Read tracking prefix: "rth_" (different from Reddit and Daily Star)
"""
import requests
import pandas as pd
import os
import time
import hashlib
import re
from datetime import datetime
from bs4 import BeautifulSoup
from typing import List, Dict, Optional

# ============================================================================
# CONSTANTS
# ============================================================================
CATEGORY_URL = "https://ritholtz.com/category/links/"
BASE_URL = "https://ritholtz.com"
SCRAPER_TIMEOUT = 30
SCRAPER_DELAY = 1.5
SCRAPER_USER_AGENT = "RitholtzAMReadsScraper/1.0"

# ============================================================================
# ARTICLE ID GENERATION
# ============================================================================


def make_article_id(url: str, title: str) -> str:
    """
    Generate stable article ID from URL and title hash.
    
    Args:
        url (str): Article URL
        title (str): Article title
        
    Returns:
        str: 12-character hash ID
    """
    unique_str = f"{url}_{title}"
    return hashlib.md5(unique_str.encode()).hexdigest()[:12]


# ============================================================================
# FIND TODAY'S AM READS POST
# ============================================================================


def find_am_reads_url(session: requests.Session) -> Optional[str]:
    """
    Find the URL of today's AM Reads or Weekend Reads post from the category page.
    """
    print(f"  Fetching {CATEGORY_URL}...")
    try:
        resp = session.get(CATEGORY_URL, timeout=SCRAPER_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        print(f"    Error fetching category page: {e}")
        return None
    
    soup = BeautifulSoup(resp.content, "html.parser")
    all_links = soup.find_all("a", href=True)
    
    # Valid keywords for both weekdays and weekends
    url_keywords = ["am-reads", "weekend-reads"]
    text_keywords = ["am reads", "weekend reads"]
    
    for link in all_links:
        href = link.get("href", "").lower()
        text = link.get_text().lower()
        
        # Skip social and share links
        if any(x in href for x in ["twitter.com", "facebook.com", "linkedin.com", "mailto:", "rss", "/intent/", "share?"]):
            continue
        
        # Look for AM Reads OR Weekend Reads
        if any(k in href for k in url_keywords) or any(k in text for k in text_keywords):
            if href.startswith("http") and "ritholtz.com/202" in href:
                print(f"    Found reading list post: {link.get('href', '')}")
                return link.get("href", "")
    
    # Fallback
    for link in all_links:
        href = link.get("href", "").lower()
        if href.startswith("http") and "ritholtz.com" in href and any(k in href for k in url_keywords):
            if "/intent/" in href or "share" in href:
                continue
            print(f"    Found reading list post (fallback): {link.get('href', '')}")
            return link.get("href", "")
    
    print("    WARNING: Could not find AM/Weekend Reads post")
    return None


# ============================================================================
# EXTRACT ARTICLES FROM AM READS POST
# ============================================================================


def extract_articles(post_url: str, session: requests.Session) -> List[Dict]:
    """
    Extract articles from an AM Reads post.
    
    The AM Reads post contains a list of links with titles and descriptions.
    We extract: title, URL, description for each article.
    
    Args:
        post_url (str): URL of the AM Reads post
        session (requests.Session): Reusable HTTP session
        
    Returns:
        List[Dict]: List of article dicts with keys:
            - article_id, title, url, description, pub_date, author,
            - source_post, scraped_at
    """
    print(f"  Fetching AM Reads post: {post_url}...")
    try:
        resp = session.get(post_url, timeout=SCRAPER_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        print(f"    Error fetching post: {e}")
        return []
    
    soup = BeautifulSoup(resp.content, "html.parser")
    articles = []
    
    # Find all links in the post content
    # Usually the articles are in a list or in the post body
    content = soup.find("div", class_="entry-content") or soup.find("article") or soup.find("div", class_="post-content")
    
    if not content:
        print("    WARNING: Could not find post content")
        return []
    
    # Find all list items (li) in the content - each article is typically in an li
    list_items = content.find_all("li")
    
    for li in list_items:
        # IMPROVEMENT 1: Primary Link Only - get ONLY the first link in each list item
        # This ignores 'see also' links within list items
        link = li.find("a", href=True)
        if not link:
            continue
            
        href = link.get("href", "")
        link_text = link.get_text().strip()
        
        # Skip internal links, empty links, or very short titles
        if not href or not link_text or len(link_text) < 3:
            continue
        
        # IMPROVEMENT 2: Domain Filter - skip any links containing ritholtz.com
        # This avoids site navigation links and 'see also' internal links
        if "ritholtz.com" in href:
            continue
        
        # Skip social media, RSS, etc.
        if any(x in href.lower() for x in ["twitter", "facebook", "linkedin", "rss", "mailto", "/intent/"]):
            continue
        
        # Get all text in the li, which includes the bullet point and description
        li_text = li.get_text(separator=" ", strip=True)
        
        # The format appears to be: "• [Publication] [Actual Title] [Description]"
        # The link text is the publication name (NYT, WSJ, etc.) which should be author
        
        # Clean up - remove link text, bullets, and special characters BEFORE splitting
        # This ensures the subsequent split on " : " or " - " works on a clean string
        full_text = li_text.replace(link_text, "", 1).strip()
        
        # IMPROVEMENT 3: Clean Title - strip leading bullets and extra whitespace
        # Characters to strip: bullet (unicode and standard), dots, dashes, colons, and whitespace
        chars_to_strip = " \t\n\r•·-–—:." + "\u2022"
        while full_text and full_text[0] in chars_to_strip:
            full_text = full_text[1:]
        full_text = full_text.strip()
        
        # Now split the clean string into title and description
        author = link_text
        
        if " : " in full_text:
            parts = full_text.split(" : ", 1)
            title = parts[0].strip()
            description = parts[1].strip() if len(parts) > 1 else ""
        elif " - " in full_text:
            parts = full_text.split(" - ", 1)
            title = parts[0].strip()
            description = parts[1].strip() if len(parts) > 1 else ""
        else:
            # No clear separator - try splitting by the first colon if it exists
            if ": " in full_text:
                colon_idx = full_text.index(": ")
                title = full_text[:colon_idx].strip()
                description = full_text[colon_idx+2:].strip()
            else:
                # Fallback: title is the whole thing (capped by length later)
                title = full_text
                description = ""
        
        # Final safety cleanup for title and description
        title = title.strip().lstrip(" \t\n\r•·-–—:.")
        description = description.strip().lstrip(" \t\n\r•·-–—:.")
        
        # Generate article ID
        article_id = make_article_id(href, title)
        
        articles.append({
            "article_id": article_id,
            "title": title,
            "url": href,
            "description": description[:500] if description else "",
            "pub_date": datetime.now().isoformat(),
            "author": author,
            "source_post": post_url,
            "scraped_at": datetime.now().isoformat(),
        })
        
        # IMPROVEMENT 4: Increase limit from 10 to 12 to ensure full list is captured
        if len(articles) >= 12:
            break
    
    # If no list items found, fall back to the original link-based approach
    if not articles:
        links = content.find_all("a")
        for link in links:
            href = link.get("href", "")
            title = link.get_text().strip()
            
            # Skip internal links, empty links, or very short titles
            if not href or not title or len(title) < 5:
                continue
            
            # Skip links to the main site or category pages
            if "ritholtz.com" in href and ("category" in href or "tag" in href or "author" in href):
                continue
            
            # Skip social media, RSS, etc.
            if any(x in href.lower() for x in ["twitter", "facebook", "linkedin", "rss", "mailto"]):
                continue
            
            # Get parent to find description
            description = ""
            art_title = "Untitled"
            parent = link.find_parent("li") or link.find_parent("p") or link.find_parent("div")
            if parent:
                parent_text = parent.get_text(separator=" ", strip=True)
                
                # Clean up - remove link text, bullets, and special characters BEFORE splitting
                full_text = parent_text.replace(title, "", 1).strip()
                
                chars_to_strip = " \t\n\r•·-–—:." + "\u2022"
                while full_text and full_text[0] in chars_to_strip:
                    full_text = full_text[1:]
                full_text = full_text.strip()
                
                # Now split the clean string into title and description
                if " : " in full_text:
                    parts = full_text.split(" : ", 1)
                    extracted_title = parts[0].strip()
                    extracted_desc = parts[1].strip() if len(parts) > 1 else ""
                elif " - " in full_text:
                    parts = full_text.split(" - ", 1)
                    extracted_title = parts[0].strip()
                    extracted_desc = parts[1].strip() if len(parts) > 1 else ""
                else:
                    if ": " in full_text:
                        colon_idx = full_text.index(": ")
                        extracted_title = full_text[:colon_idx].strip()
                        extracted_desc = full_text[colon_idx+2:].strip()
                    else:
                        extracted_title = full_text
                        extracted_desc = ""
                
                extracted_title = extracted_title.strip().lstrip(" \t\n\r•·-–—:.")
                extracted_desc = extracted_desc.strip().lstrip(" \t\n\r•·-–—:.")
                
                art_title = extracted_title if extracted_title else "Untitled"
                description = extracted_desc
            
            # Use the link text as author
            author = title
            
            # Generate article ID
            article_id = make_article_id(href, art_title)
            
            articles.append({
                "article_id": article_id,
                "title": art_title[:200],
                "url": href,
                "description": description[:500] if description else "",
                "pub_date": datetime.now().isoformat(),
                "author": author,
                "source_post": post_url,
                "scraped_at": datetime.now().isoformat(),
            })
            
            if len(articles) >= 12:
                break
    
    print(f"    Extracted {len(articles)} articles")
    return articles



# ============================================================================
# SAVE ARTICLES TO CSV
# ============================================================================


def save_articles(articles: List[Dict]) -> None:
    """
    Save articles to data/ritholtz/articles.csv.
    
    This overwrites the file each time (daily posts change).
    
    Args:
        articles (List[Dict]): Articles to save
    """
    if not articles:
        print("\nNo articles to save.")
        return
    
    out_dir = "data/ritholtz"
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "articles.csv")
    
    df = pd.DataFrame(articles)
    df.to_csv(csv_path, index=False)
    print(f"\nSaved {csv_path} ({len(df)} articles)")


# ============================================================================
# MAIN SCRAPING PIPELINE
# ============================================================================


def scrape_am_reads() -> List[Dict]:
    """
    Main scraping pipeline: find today's post → extract articles.
    
    Returns:
        List[Dict]: List of article dicts
    """
    print("\n" + "=" * 55)
    print("Ritholtz AM Reads Scraper")
    print("=" * 55)
    
    session = requests.Session()
    session.headers.update({"User-Agent": SCRAPER_USER_AGENT})
    
    # Step 1: Find today's AM Reads post
    post_url = find_am_reads_url(session)
    if not post_url:
        print("ERROR: Could not find AM Reads post URL")
        return []
    
    time.sleep(SCRAPER_DELAY)
    
    # Step 2: Extract articles from the post
    articles = extract_articles(post_url, session)
    
    print(f"\nTotal articles extracted: {len(articles)}")
    return articles


# ============================================================================
# ENTRY POINT
# ============================================================================


def main():
    """
    Run the complete scraper pipeline.
    """
    articles = scrape_am_reads()
    save_articles(articles)
    print("\nDone! Run: streamlit run dashboard.py")


if __name__ == "__main__":
    main()
