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
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
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
ET = ZoneInfo("America/New_York")
MAX_ARTICLES = 12

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
# NORMALIZATION + DEDUP HELPERS (added 2026-09-26)
# ============================================================================
# Zero-width chars show up before the bullet ("\u200b• Title") and defeated the
# old leading-bullet strip, so the same article could appear twice.
ZERO_WIDTH = "\u200b\u200c\u200d\u2060\ufeff"
STRIP_CHARS = " \t\n\r\u00a0•·-–—:." + "\u2022" + ZERO_WIDTH

# Promo lines that are not articles (video embeds, podcast plugs, signups).
JUNK_TITLE_RE = re.compile(
    r"^(video of the day|be sure to check out|sign up|subscribe|masters in business|"
    r"see also|previously|the podcast|the weekend is here|untitled$|previous post|next post|"
    r"to learn how these reads)", re.I)
JUNK_URL_RE = re.compile(r"(itunes\.apple\.com|podcasts\.apple\.com|open\.spotify\.com/show)", re.I)

SEEN_FILE = "data/ritholtz/seen.json"
SEEN_KEEP_DAYS = 45


def clean_title_text(text: str) -> str:
    """Strip zero-width chars, leading bullets/punctuation and collapse spaces."""
    text = re.sub(f"[{ZERO_WIDTH}]", "", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    while text and text[0] in STRIP_CHARS:
        text = text[1:]
    return text.strip()


def normalize_title(title: str) -> str:
    """Comparison key for a title: lowercase letters/digits only, first 60 chars."""
    t = clean_title_text(title).lower()
    t = re.sub(r"[^a-z0-9 ]", "", t)
    return re.sub(r"\s+", " ", t).strip()[:60]


def normalize_url(url: str) -> str:
    """Comparison key for a URL: no scheme/www/query/fragment/trailing slash.
    YouTube watch URLs keep their v= id since that IS the article."""
    u = (url or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^(www\.|m\.)", "", u)
    vid = re.search(r"[?&]v=([\w-]+)", u)
    u = re.split(r"[?#]", u)[0].rstrip("/")
    if vid and "youtube.com/watch" in u:
        u += "?v=" + vid.group(1)
    return u


def is_junk(title: str, url: str) -> bool:
    return bool(JUNK_TITLE_RE.search(clean_title_text(title)) or JUNK_URL_RE.search(url or ""))


def dedupe_articles(articles: List[Dict]) -> List[Dict]:
    """Drop repeats inside one post: same normalized URL OR same normalized title."""
    seen_urls, seen_titles, out = set(), set(), []
    for a in articles:
        ku, kt = normalize_url(a["url"]), normalize_title(a["title"])
        if ku in seen_urls or (kt and kt in seen_titles):
            continue
        seen_urls.add(ku)
        if kt:
            seen_titles.add(kt)
        out.append(a)
    return out


def load_seen() -> Dict:
    try:
        with open(SEEN_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def filter_already_shown(articles: List[Dict], seen: Dict, post_url: str) -> List[Dict]:
    """Drop articles already shown in an EARLIER post (Ritholtz sometimes re-links).
    Re-running the same post keeps its own articles."""
    out = []
    for a in articles:
        keys = ["u:" + normalize_url(a["url"]), "t:" + normalize_title(a["title"])]
        if any(k in seen and seen[k]["post"] != post_url for k in keys if len(k) > 2):
            print(f"    skip (shown on an earlier day): {a['title'][:60]}")
            continue
        out.append(a)
    return out


def remember_shown(articles: List[Dict], seen: Dict, post_url: str, post_date: str) -> Dict:
    for a in articles:
        for k in ["u:" + normalize_url(a["url"]), "t:" + normalize_title(a["title"])]:
            if len(k) > 2 and k not in seen:
                seen[k] = {"post": post_url, "date": post_date}
    cutoff = (datetime.now(ET) - timedelta(days=SEEN_KEEP_DAYS)).strftime("%Y-%m-%d")
    return {k: v for k, v in seen.items() if v.get("date", "9999") >= cutoff}


def save_seen(seen: Dict) -> None:
    os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
    with open(SEEN_FILE, "w") as f:
        json.dump(seen, f, indent=0, sort_keys=True)


def get_post_date(soup: BeautifulSoup) -> Optional[str]:
    """The post's real publish time (ISO, US/Eastern). The old code stamped the
    SCRAPE time, so a Friday list scraped after midnight UTC read as Saturday."""
    tag = soup.find("meta", attrs={"property": "article:published_time"})
    raw = tag.get("content") if tag else None
    if not raw:
        t = soup.find("time", attrs={"datetime": True})
        raw = t.get("datetime") if t else None
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(ET).isoformat()
    except Exception:
        return None


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
    seen_titles = set()
    post_date = get_post_date(soup) or datetime.now(ET).isoformat()
    print(f"    Post published: {post_date}")
    
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
        full_text = clean_title_text(li_text.replace(link_text, "", 1))
        
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
        elif " . " in full_text[:160]:
            parts = full_text.split(" . ", 1)
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
        title = clean_title_text(title)
        description = clean_title_text(description)
        
        # STRICT TITLE DEDUPLICATION - Skip duplicate titles
        if not title or is_junk(title, href):
            continue
        
        # Normalize the title for strict mathematical comparison
        clean_title = title.strip().lower()
        
        # If we have already seen this exact title in this scrape session, skip the duplicate
        if clean_title in seen_titles:
            continue
        
        # Otherwise, add it to our tracking set and proceed
        seen_titles.add(clean_title)
        
        # Generate article ID
        article_id = make_article_id(href, title)
        
        articles.append({
            "article_id": article_id,
            "title": title,
            "url": href,
            "description": description[:500] if description else "",
            "pub_date": post_date,
            "author": author,
            "source_post": post_url,
            "scraped_at": datetime.now().isoformat(),
        })
        
        # IMPROVEMENT 4: Increase limit from 10 to 12 to ensure full list is captured
        if len(articles) >= MAX_ARTICLES * 2:
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
            
            # STRICT TITLE DEDUPLICATION - Skip duplicate titles (fallback section)
            art_title = clean_title_text(art_title)
            if not art_title or is_junk(art_title, href):
                continue
            
            clean_title = art_title.strip().lower()
            if clean_title in seen_titles:
                continue
            seen_titles.add(clean_title)
            
            # Generate article ID
            article_id = make_article_id(href, art_title)
            
            articles.append({
                "article_id": article_id,
                "title": art_title[:200],
                "url": href,
                "description": description[:500] if description else "",
                "pub_date": post_date,
                "author": author,
                "source_post": post_url,
                "scraped_at": datetime.now().isoformat(),
            })
            
            if len(articles) >= MAX_ARTICLES * 2:
                break
    
    articles = dedupe_articles(articles)
    print(f"    Extracted {len(articles)} articles (after in-post dedup)")
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
    # Same post + same articles as what's on disk -> leave the file alone, so
    # the morning re-check workflow doesn't create an empty "changed" commit.
    try:
        old = pd.read_csv(csv_path)
        if list(old["article_id"]) == list(df["article_id"]) and list(old["pub_date"]) == list(df["pub_date"]):
            print(f"\nUnchanged: {csv_path} already holds this post ({len(df)} articles)")
            return
    except Exception:
        pass
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
    if not articles:
        return []

    # Step 3: drop articles already shown on an earlier day, then cap
    seen = load_seen()
    articles = filter_already_shown(articles, seen, post_url)[:MAX_ARTICLES]
    new_seen = remember_shown(articles, dict(seen), post_url, articles[0]["pub_date"][:10] if articles else "")
    if new_seen != seen:  # don't rewrite (and commit) an unchanged file
        save_seen(new_seen)

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
