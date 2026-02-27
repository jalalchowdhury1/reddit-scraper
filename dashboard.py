"""
Reddit Daily Dashboard + Daily Star News Browser
=================================================

WHAT IT DOES:
1. Displays Reddit top posts (monthly + yearly) in tab 1 & 2
2. Displays Daily Star news articles (keyword-matched) in tab 3
3. Lets users mark posts/articles as "read"
4. Read status persists across sessions (saved to JSON)
5. Beautiful Tokyo Night theme with category badges

KEY FEATURES:
- 3 tabs: Monthly Top, Yearly Top, Daily Star News
- Unified read tracking (Reddit + News in same JSON file)
- Subreddit/category filters
- Sort by score/comments (Reddit) or date (News)
- Pagination (50 items per tab)
- Read posts hidden by default (toggle in sidebar)
- Gracefully handles missing data (shows helpful messages)

USAGE:
    streamlit run dashboard.py

DEPENDENCIES:
    - streamlit >= 1.28.0 (UI framework)
    - pandas >= 2.1.0 (data processing)
    - config.py (subreddit and category config)

READ TRACKING SYSTEM:
    File: data/read_posts.json
    Keys for Reddit posts: bare ID (e.g., "1r2vnhs")
    Keys for News articles: "dsr_" prefix (e.g., "dsr_464356fa75d5")
    → No collision possible between systems

IMPORTANT FOR LLMs:
- Do NOT manually edit data/read_posts.json (use dashboard UI instead)
- If dashboard shows "No data": Run scrape_top.py and/or scrape_dailystar.py
- To debug: Check sidebar "Show read posts" to see all items
- CSS styling: style.css must be in same directory as this file
"""
import streamlit as st
import pandas as pd
from pathlib import Path
import glob
import json
import os
import tempfile
import logging
from typing import Tuple

import config

# ============================================================================
# LOGGING SETUP
# ============================================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ============================================================================
# READ TRACKING CONFIGURATION
# ============================================================================
# File that stores which posts/articles user has marked as read
READ_POSTS_FILE = Path("data/read_posts.json")

# ============================================================================
# FAVORITE TRACKING CONFIGURATION
# ============================================================================
FAVORITE_POSTS_FILE = Path("data/favorite_posts.json")

def load_favorite_posts() -> set:
    if not FAVORITE_POSTS_FILE.exists(): return set()
    try:
        with open(FAVORITE_POSTS_FILE, "r") as f: return set(json.load(f))
    except: return set()

def save_favorite_posts(fav_set: set) -> None:
    FAVORITE_POSTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd, tmp_path = tempfile.mkstemp(dir=str(FAVORITE_POSTS_FILE.parent), suffix=".tmp")
        with os.fdopen(fd, "w") as f: json.dump(sorted(fav_set), f, indent=2)
        os.replace(tmp_path, str(FAVORITE_POSTS_FILE))
    except: pass

# ============================================================================
# READ TRACKING FUNCTIONS
# ============================================================================


def load_read_posts() -> set:
    """
    Load read post IDs from persistent JSON storage.

    Returns:
        set: IDs of read posts/articles. May contain:
            - Reddit post IDs: bare numeric IDs (e.g., "1r2vnhs")
            - News article IDs: with "dsr_" prefix (e.g., "dsr_464356fa75d5")

    Behavior:
        - If file doesn't exist: returns empty set
        - If file corrupted: logs error, returns empty set
        - Strips legacy "_month"/"_year" suffixes (old format auto-migration)

    WHY THIS MATTERS:
        - User marking post as read in Monthly tab also hides it in Yearly
        - Post stays hidden even after browser refresh
        - Across multiple browser sessions
    """
    if not READ_POSTS_FILE.exists():
        return set()
    try:
        with open(READ_POSTS_FILE, "r") as f:
            data = json.load(f)
        # Support both old format (list of "id_month" strings) and new (bare IDs)
        cleaned = set()
        for item in data:
            # Strip legacy suffixes like "_month" / "_year"
            base_id = str(item).rsplit("_month", 1)[0].rsplit("_year", 1)[0]
            cleaned.add(base_id)
        return cleaned
    except (json.JSONDecodeError, TypeError, IOError) as e:
        logger.error(f"Failed to load read_posts.json: {e}")
        return set()


def save_read_posts(read_set: set) -> None:
    """
    Atomically save read post/article IDs to JSON.

    Args:
        read_set (set): IDs to save

    Safety Features:
        - Write to temp file first, then atomic rename
        - Prevents corruption if process crashes mid-write
        - Cleans up temp file on error
        - Logs errors instead of crashing

    ATOMIC WRITE PATTERN:
        1. Create temp file
        2. Write entire set to temp file
        3. Atomic rename temp → real file
        → Either all data written or nothing (no partial writes)
    """
    READ_POSTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Write to temp file first, then atomically replace
        fd, tmp_path = tempfile.mkstemp(
            dir=str(READ_POSTS_FILE.parent), suffix=".tmp"
        )
        with os.fdopen(fd, "w") as f:
            json.dump(sorted(read_set), f, indent=2)
        os.replace(tmp_path, str(READ_POSTS_FILE))
    except IOError as e:
        logger.error(f"Failed to save read_posts.json: {e}")
        # Clean up temp file on failure
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ============================================================================
# STYLING
# ============================================================================


def local_css(file_name: str) -> None:
    """
    Inject CSS from file into Streamlit page.

    Args:
        file_name (str): Path to CSS file (relative to current directory)

    Note:
        - style.css must exist in same directory as this file
        - Contains Tokyo Night color scheme
        - Includes badge styles for Reddit subreddits and News categories
    """
    path = Path(file_name)
    if path.exists():
        st.markdown(f"<style>{path.read_text()}</style>", unsafe_allow_html=True)


# ============================================================================
# STREAMLIT PAGE SETUP
# ============================================================================
if "read_posts" not in st.session_state:
    st.session_state.read_posts = load_read_posts()

if "favorite_posts" not in st.session_state:
    st.session_state.favorite_posts = load_favorite_posts()

st.set_page_config(
    page_title="Reddit Daily",
    page_icon="https://www.redditstatic.com/desktop2x/img/favicon/android-icon-192x192.png",
    layout="wide",
    initial_sidebar_state="expanded",
)
local_css("style.css")

# ============================================================================
# DATA LOADING — REDDIT POSTS
# ============================================================================


def load_posts() -> pd.DataFrame:
    """
    Load all scraped Reddit posts from CSV files.

    Returns:
        pd.DataFrame: Combined posts with columns:
            - id, title, author, score, num_comments, etc. (see CSV_FORMAT.md)
            - subreddit (added from folder name)
            - time_filter (added: "month" or "year")

    Data Layout:
        data/r_dataisbeautiful/posts.csv → subreddit="dataisbeautiful", time_filter="month"
        data/r_dataisbeautiful_yearly/posts.csv → subreddit="dataisbeautiful", time_filter="year"
        (Same pattern for all 13 subreddits)

    Error Handling:
        - Missing files: logged but skip (no crash)
        - Corrupt CSVs: logged but skip
        - Missing columns: safely defaults to empty string / 0
        - NaN values: filled with defaults

    Returns empty DataFrame if:
        - data/ directory doesn't exist
        - No CSV files found
        - All CSVs are empty or corrupt

    WHY SAFE DEFAULTS MATTER:
        - Some posts might not have all fields
        - Dashboard should never crash due to missing data
        - Partial data is better than nothing
    """
    data_dir = Path("data")
    all_posts = []

    if not data_dir.exists():
        return pd.DataFrame()

    # Monthly posts: data/r_*/posts.csv  (excluding _yearly folders)
    for csv_file in sorted(glob.glob(str(data_dir / "r_*/posts.csv"))):
        if "_yearly" in csv_file:
            continue
        try:
            df = pd.read_csv(csv_file)
            if df.empty or "id" not in df.columns:
                continue
            sub_name = Path(csv_file).parent.name.replace("r_", "")
            df["subreddit"] = sub_name
            df["time_filter"] = "month"
            all_posts.append(df)
        except Exception as e:
            logger.warning(f"Skipping {csv_file}: {e}")

    # Yearly posts: data/r_*_yearly/posts.csv
    for csv_file in sorted(glob.glob(str(data_dir / "r_*_yearly/posts.csv"))):
        try:
            df = pd.read_csv(csv_file)
            if df.empty or "id" not in df.columns:
                continue
            sub_name = Path(csv_file).parent.name.replace("r_", "").replace("_yearly", "")
            df["subreddit"] = sub_name
            df["time_filter"] = "year"
            all_posts.append(df)
        except Exception as e:
            logger.warning(f"Skipping {csv_file}: {e}")

    if not all_posts:
        return pd.DataFrame()

    combined = pd.concat(all_posts, ignore_index=True)

    # Ensure required columns exist with safe defaults
    for col, default in [
        ("score", 0),
        ("num_comments", 0),
        ("author", "unknown"),
        ("selftext", ""),
        ("permalink", ""),
        ("title", "Untitled"),
    ]:
        if col not in combined.columns:
            combined[col] = default

    # Fill NaN values with defaults
    combined["score"] = pd.to_numeric(combined["score"], errors="coerce").fillna(0).astype(int)
    combined["num_comments"] = pd.to_numeric(combined["num_comments"], errors="coerce").fillna(0).astype(int)
    combined["author"] = combined["author"].fillna("unknown")
    combined["selftext"] = combined["selftext"].fillna("")
    combined["title"] = combined["title"].fillna("Untitled")
    combined["id"] = combined["id"].astype(str)

    # Deduplicate by post id within each time_filter group
    combined = combined.drop_duplicates(subset=["id", "time_filter"], keep="first")

    return combined


# ============================================================================
# DATA LOADING — NEWS ARTICLES
# ============================================================================


def load_news_articles() -> pd.DataFrame:
    """
    Load scraped Daily Star articles from CSV.

    Returns:
        pd.DataFrame: Articles with columns:
            - article_id, title, url, description, pub_date, author, category,
            - matched_keywords, feed_source, scraped_at

    Data Source:
        data/dailystar/articles.csv (created by scrape_dailystar.py)

    Error Handling:
        - Missing file: returns empty DataFrame (news tab shows helpful message)
        - Corrupt CSV: returns empty DataFrame
        - Missing columns: safely defaults to empty string
        - NaN values: filled with defaults

    Why empty description OK:
        - Some RSS feeds have minimal descriptions
        - Dashboard still shows title + preview
    """
    csv_path = Path("data/dailystar/articles.csv")
    if not csv_path.exists():
        return pd.DataFrame()

    try:
        df = pd.read_csv(csv_path)
        if df.empty or "article_id" not in df.columns:
            return pd.DataFrame()

        for col, default in [
            ("title", "Untitled"),
            ("url", ""),
            ("description", ""),
            ("pub_date", ""),
            ("author", "Unknown"),
            ("category", "Uncategorized"),
            ("matched_keywords", ""),
        ]:
            if col not in df.columns:
                df[col] = default

        df["article_id"] = df["article_id"].astype(str)
        df["title"] = df["title"].fillna("Untitled")
        df["description"] = df["description"].fillna("")
        df["author"] = df["author"].fillna("Unknown")
        df = df.drop_duplicates(subset=["article_id", "category"], keep="first")
        return df
    except Exception as e:
        logger.warning(f"Failed to load news articles: {e}")
        return pd.DataFrame()


# ============================================================================
# DATA LOADING — RITHOLTZ AM READS
# ============================================================================


def load_ritholtz_articles() -> pd.DataFrame:
    """
    Load scraped Ritholtz AM Reads articles from CSV.

    Returns:
        pd.DataFrame: Articles with columns:
            - article_id, title, url, description, pub_date, author,
            - source_post, scraped_at

    Data Source:
        data/ritholtz/articles.csv (created by scrape_ritholtz.py)

    Error Handling:
        - Missing file: returns empty DataFrame (AM Reads tab shows helpful message)
        - Corrupt CSV: returns empty DataFrame
        - Missing columns: safely defaults to empty string
        - NaN values: filled with defaults
    """
    csv_path = Path("data/ritholtz/articles.csv")
    if not csv_path.exists():
        return pd.DataFrame()

    try:
        df = pd.read_csv(csv_path)
        if df.empty or "article_id" not in df.columns:
            return pd.DataFrame()

        for col, default in [
            ("title", "Untitled"),
            ("url", ""),
            ("description", ""),
            ("pub_date", ""),
            ("author", "Unknown"),
            ("source_post", ""),
        ]:
            if col not in df.columns:
                df[col] = default

        df["article_id"] = df["article_id"].astype(str)
        df["title"] = df["title"].fillna("Untitled")
        df["description"] = df["description"].fillna("")
        df["author"] = df["author"].fillna("Unknown")
        df = df.drop_duplicates(subset=["article_id"], keep="first")
        return df
    except Exception as e:
        logger.warning(f"Failed to load Ritholtz articles: {e}")
        return pd.DataFrame()



# ============================================================================
# SUBREDDIT NAME DISPLAY
# ============================================================================


def get_display_name(sub: str) -> str:
    """
    Map subreddit name to human-readable display name.

    Args:
        sub (str): Subreddit name (case-insensitive)

    Returns:
        str: Display name from config.SUBREDDITS, or "r/{sub}" as fallback

    Example:
        get_display_name("dataisbeautiful") → "Data Is Beautiful"
        get_display_name("unknown_sub") → "r/unknown_sub"
    """
    for s in config.SUBREDDITS:
        if s["name"].lower() == sub.lower():
            return s["display_name"]
    return f"r/{sub}"


# ============================================================================
# REDDIT POST RENDERING
# ============================================================================


def render_post_card(row, is_read: bool) -> None:
    post_id = str(row["id"])
    time_badge = row.get("time_filter", "month").upper()
    title_text = str(row.get("title", "Untitled"))
    selftext = str(row.get("selftext", ""))
    
    score = int(row.get("score", 0))
    score_display = f" • {score:,} pts" if score > 0 else ""
    
    with st.container(border=True):
        html_content = f"""
            <div class="reader-title">{title_text}</div>
            <div class="reader-desc">{selftext}</div>
        """
        st.markdown(html_content, unsafe_allow_html=True)
        
        # Meta info now lives in the first column, utilizing the empty space
        col_meta, col_link, col_fav, col_read = st.columns([4.5, 1.5, 1.5, 1.5])
        
        with col_meta:
            meta_text = f'{get_display_name(row["subreddit"])} • {time_badge}{score_display}'
            st.markdown(f'<div class="bottom-meta">{meta_text}</div>', unsafe_allow_html=True)
            
        with col_link:
            permalink = str(row.get("permalink", ""))
            if permalink:
                st.link_button("↗ Open", f"https://reddit.com{permalink}", use_container_width=True)
        with col_fav:
            is_fav = post_id in st.session_state.favorite_posts
            if is_fav:
                if st.button("★ Saved", key=f"ufav_{post_id}_{row.get('time_filter','m')}", use_container_width=True):
                    st.session_state.favorite_posts.discard(post_id)
                    save_favorite_posts(st.session_state.favorite_posts)
                    st.rerun()
            else:
                if st.button("☆ Save", key=f"fav_{post_id}_{row.get('time_filter','m')}", use_container_width=True):
                    st.session_state.favorite_posts.add(post_id)
                    save_favorite_posts(st.session_state.favorite_posts)
                    st.rerun()
        with col_read:
            if is_read:
                if st.button("↺ Unread", key=f"un_{post_id}_{row.get('time_filter','m')}", use_container_width=True, type="secondary"):
                    st.session_state.read_posts.discard(post_id)
                    save_read_posts(st.session_state.read_posts)
                    st.rerun()
            else:
                if st.button("✓ Mark Read", key=f"rd_{post_id}_{row.get('time_filter','m')}", use_container_width=True, type="primary"):
                    st.session_state.read_posts.add(post_id)
                    save_read_posts(st.session_state.read_posts)
                    st.rerun()


# ============================================================================
# REDDIT TAB RENDERING
# ============================================================================


def render_tab(df: pd.DataFrame, tab_key: str) -> None:
    """
    Render a full Reddit tab with filters and post cards.

    Args:
        df (pd.DataFrame): Filtered posts to display
        tab_key (str): Unique key for filters ("monthly" or "yearly")

    Tab Layout:
        1. Filter row: Subreddit dropdown | Sort dropdown
        2. Caption showing post count
        3. Post cards (up to 50)

    Filters:
        - Subreddit: "All" or specific subreddit
        - Sort: "Score" (descending) or "Comments" (descending)

    Pagination:
        - Shows "Showing X of Y" caption
        - Renders up to 50 posts (limit prevents performance issues)
    """
    if df.empty:
        st.info("No posts to show.")
        return

    col1, col2 = st.columns([1, 1])

    # Build subreddit list with proper case
    sub_list = sorted(df["subreddit"].unique().tolist(), key=str.lower)
    subs = ["All"] + sub_list
    sel = col1.selectbox("Subreddit", subs, key=f"sub_{tab_key}")
    sort_opt = col2.selectbox("Sort by", ["Score", "Comments"], key=f"sort_{tab_key}")

    if sel != "All":
        df = df[df["subreddit"] == sel]  # Exact match, no .lower()

    sort_col = "score" if sort_opt == "Score" else "num_comments"
    df = df.sort_values(sort_col, ascending=False)

    # Show post count
    st.caption(f"Showing {min(len(df), 50)} of {len(df)} posts")

    for _, row in df.head(50).iterrows():
        post_id = str(row["id"])
        render_post_card(row, post_id in st.session_state.read_posts)


# ============================================================================
# NEWS ARTICLE RENDERING
# ============================================================================


def render_article_card(row, is_read: bool) -> None:
    article_id = str(row["article_id"])
    read_key = f"dsr_{article_id}"
    category = str(row.get("category", ""))
    pub_date = str(row.get("pub_date", ""))[:10]
    title_text = str(row.get("title", "Untitled"))
    description = str(row.get("description", ""))
    
    with st.container(border=True):
        html_content = f"""
            <div class="reader-title">{title_text}</div>
            <div class="reader-desc">{description}</div>
        """
        st.markdown(html_content, unsafe_allow_html=True)
        
        col_meta, col_link, col_fav, col_read = st.columns([4.5, 1.5, 1.5, 1.5])
        
        with col_meta:
            meta_text = f'DAILY STAR • {category} • {pub_date}'
            st.markdown(f'<div class="bottom-meta">{meta_text}</div>', unsafe_allow_html=True)
            
        with col_link:
            url = str(row.get("url", ""))
            if url and url != "nan":
                st.link_button("↗ Open", url, use_container_width=True)
        with col_fav:
            is_fav = read_key in st.session_state.favorite_posts
            if is_fav:
                if st.button("★ Saved", key=f"ufav_{read_key}_{row.get('category','')}", use_container_width=True):
                    st.session_state.favorite_posts.discard(read_key)
                    save_favorite_posts(st.session_state.favorite_posts)
                    st.rerun()
            else:
                if st.button("☆ Save", key=f"fav_{read_key}_{row.get('category','')}", use_container_width=True):
                    st.session_state.favorite_posts.add(read_key)
                    save_favorite_posts(st.session_state.favorite_posts)
                    st.rerun()
        with col_read:
            if is_read:
                if st.button("↺ Unread", key=f"nun_{read_key}_{row.get('category','')}", use_container_width=True, type="secondary"):
                    st.session_state.read_posts.discard(read_key)
                    save_read_posts(st.session_state.read_posts)
                    st.rerun()
            else:
                if st.button("✓ Mark Read", key=f"nrd_{read_key}_{row.get('category','')}", use_container_width=True, type="primary"):
                    st.session_state.read_posts.add(read_key)
                    save_read_posts(st.session_state.read_posts)
                    st.rerun()


# ============================================================================
# NEWS TAB RENDERING
# ============================================================================


def render_news_tab(df: pd.DataFrame) -> None:
    """
    Render the Daily Star News tab with category filter and article cards.

    Args:
        df (pd.DataFrame): News articles to display

    Tab Layout:
        1. Filter row: Category dropdown | Date sort dropdown
        2. Caption showing article count
        3. Article cards (up to 50)

    Filters:
        - Category: "All Categories" or specific category
        - Sort: "Date (Newest)" or "Date (Oldest)"

    Pagination:
        - Shows "Showing X of Y" caption
        - Renders up to 50 articles (limit prevents performance issues)
    """
    if df.empty:
        st.info("No news articles found. Run `python scrape_dailystar.py` to fetch news.")
        return

    col1, col2 = st.columns([1, 1])

    # Category filter
    cat_list = sorted(df["category"].unique().tolist())
    cats = ["All Categories"] + cat_list
    sel_cat = col1.selectbox("Category", cats, key="news_cat")
    sort_opt = col2.selectbox("Sort by", ["Date (Newest)", "Date (Oldest)"], key="news_sort")

    if sel_cat != "All Categories":
        df = df[df["category"] == sel_cat]

    ascending = sort_opt == "Date (Oldest)"
    df = df.sort_values("pub_date", ascending=ascending, na_position="last")

    st.caption(f"Showing {min(len(df), 50)} of {len(df)} articles")

    for _, row in df.head(50).iterrows():
        read_key = f"dsr_{row['article_id']}"
        render_article_card(row, read_key in st.session_state.read_posts)


# ============================================================================
# RITHOLTZ AM READS ARTICLE RENDERING
# ============================================================================


def render_ritholtz_card(row, is_read: bool) -> None:
    article_id = str(row["article_id"])
    read_key = f"rth_{article_id}"
    pub_date = str(row.get("pub_date", ""))[:10]
    title_text = str(row.get("title", "Untitled"))
    description = str(row.get("description", ""))

    with st.container(border=True):
        html_content = f"""
            <div class="reader-title">{title_text}</div>
            <div class="reader-desc">{description}</div>
        """
        st.markdown(html_content, unsafe_allow_html=True)

        col_meta, col_link, col_fav, col_read = st.columns([4.5, 1.5, 1.5, 1.5])
        
        with col_meta:
            meta_text = f'AM READS • {pub_date}'
            st.markdown(f'<div class="bottom-meta">{meta_text}</div>', unsafe_allow_html=True)
            
        with col_link:
            url = str(row.get("url", ""))
            if url and url != "nan":
                st.link_button("↗ Open", url, use_container_width=True)
        with col_fav:
            is_fav = read_key in st.session_state.favorite_posts
            if is_fav:
                if st.button("★ Saved", key=f"ufav_{read_key}", use_container_width=True):
                    st.session_state.favorite_posts.discard(read_key)
                    save_favorite_posts(st.session_state.favorite_posts)
                    st.rerun()
            else:
                if st.button("☆ Save", key=f"fav_{read_key}", use_container_width=True):
                    st.session_state.favorite_posts.add(read_key)
                    save_favorite_posts(st.session_state.favorite_posts)
                    st.rerun()
        with col_read:
            if is_read:
                if st.button("↺ Unread", key=f"rth_un_{read_key}", use_container_width=True, type="secondary"):
                    st.session_state.read_posts.discard(read_key)
                    save_read_posts(st.session_state.read_posts)
                    st.rerun()
            else:
                if st.button("✓ Mark Read", key=f"rth_rd_{read_key}", use_container_width=True, type="primary"):
                    st.session_state.read_posts.add(read_key)
                    save_read_posts(st.session_state.read_posts)
                    st.rerun()


# ============================================================================
# RITHOLTZ AM READS TAB RENDERING
# ============================================================================


def render_ritholtz_tab(df: pd.DataFrame) -> None:
    """
    Render the Ritholtz AM Reads tab with article cards.

    Args:
        df (pd.DataFrame): AM Reads articles to display

    Tab Layout:
        1. Caption showing article count (10 articles per day)
        2. Article cards (up to 10)

    Note:
        - Articles are pre-filtered to 10 per day
        - No filters needed (all 10 are shown)
    """
    if df.empty:
        st.info("No AM Reads articles found. Run `python scrape_ritholtz.py` to fetch articles.")
        return

    st.caption(f"Showing {len(df)} articles")

    for _, row in df.iterrows():
        read_key = f"rth_{row['article_id']}"
        render_ritholtz_card(row, read_key in st.session_state.read_posts)



# ============================================================================
# SIDEBAR
# ========================

# ========================
with st.sidebar:
    st.markdown('<div class="sidebar-header">Settings</div>', unsafe_allow_html=True)

    show_read = st.checkbox("Show read posts", value=False)

    st.markdown("---")

    read_count = len(st.session_state.read_posts)
    st.markdown(f'<div class="sidebar-stat">Posts marked read: **{read_count}**</div>', unsafe_allow_html=True)

    fav_count = len(st.session_state.favorite_posts)
    st.markdown(f'<div class="sidebar-stat">Favorited items: **{fav_count}**</div>', unsafe_allow_html=True)

    if st.button("Clear all read markers", use_container_width=True, type="secondary"):
        st.session_state.read_posts = set()
        save_read_posts(set())
        st.rerun()

    st.markdown("---")
    st.markdown(
        '<div class="sidebar-tip">Posts you mark as read are saved to disk and stay hidden across sessions.</div>',
        unsafe_allow_html=True,
    )


# ============================================================================
# MAIN CONTENT
# ============================================================================
# Load data
posts_df = load_posts()
news_df = load_news_articles()
ritholtz_df = load_ritholtz_articles()

has_reddit = not posts_df.empty
has_news = not news_df.empty
has_ritholtz = not ritholtz_df.empty

if not has_reddit and not has_news and not has_ritholtz:
    st.warning("No data found. Run `python scrape_top.py`, `python scrape_dailystar.py` and/or `python scrape_ritholtz.py` first.")
    st.stop()

# Create sets of items to hide from main tabs
hide_reddit = st.session_state.favorite_posts.copy()
hide_news = st.session_state.favorite_posts.copy()
hide_ritholtz = st.session_state.favorite_posts.copy()

if not show_read:
    hide_reddit.update(st.session_state.read_posts)
    hide_news.update(st.session_state.read_posts)
    hide_ritholtz.update(st.session_state.read_posts)

# Apply filters
filtered_df = posts_df[~posts_df["id"].astype(str).isin(hide_reddit)] if has_reddit else posts_df
filtered_news = news_df[~news_df["article_id"].astype(str).apply(lambda x: f"dsr_{x}").isin(hide_news)] if has_news else news_df
filtered_ritholtz = ritholtz_df[~ritholtz_df["article_id"].astype(str).apply(lambda x: f"rth_{x}").isin(hide_ritholtz)] if has_ritholtz else ritholtz_df

# Stats row
monthly_count = len(filtered_df[filtered_df["time_filter"] == "month"]) if has_reddit else 0
yearly_count = len(filtered_df[filtered_df["time_filter"] == "year"]) if has_reddit else 0
news_count = len(filtered_news) if has_news else 0
amreads_count = len(filtered_ritholtz) if has_ritholtz else 0
unread_total = (len(filtered_df) if has_reddit else 0) + news_count + amreads_count
total = (len(posts_df) if has_reddit else 0) + (len(news_df) if has_news else 0) + (len(ritholtz_df) if has_ritholtz else 0)

st.markdown(
    f'<div class="discreet-stats">'
    f'Monthly: <b>{monthly_count}</b> &nbsp;|&nbsp; '
    f'Yearly: <b>{yearly_count}</b> &nbsp;|&nbsp; '
    f'News: <b>{news_count}</b> &nbsp;|&nbsp; '
    f'AM Reads: <b>{amreads_count}</b> &nbsp;|&nbsp; '
    f'<span style="color: var(--tn-blue)">Unread: <b>{unread_total}</b></span> &nbsp;|&nbsp; '
    f'Total: <b>{total}</b>'
    f'</div>', 
    unsafe_allow_html=True
)

st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

# Tabs
tab_monthly, tab_yearly, tab_news, tab_amreads, tab_favorites = st.tabs(["Monthly Top", "Yearly Top", "Daily Star News", "AM Reads", "⭐ Favorites"])

with tab_monthly:
    if has_reddit:
        render_tab(
            filtered_df[filtered_df["time_filter"] == "month"].copy(),
            "monthly",
        )
    else:
        st.info("No Reddit posts found. Run `python scrape_top.py` to fetch data.")

with tab_yearly:
    if has_reddit:
        render_tab(
            filtered_df[filtered_df["time_filter"] == "year"].copy(),
            "yearly",
        )
    else:
        st.info("No Reddit posts found. Run `python scrape_top.py` to fetch data.")

with tab_news:
    render_news_tab(filtered_news.copy() if has_news else pd.DataFrame())

with tab_amreads:
    render_ritholtz_tab(filtered_ritholtz.copy() if has_ritholtz else pd.DataFrame())

with tab_favorites:
    st.markdown("### ⭐ Favorited Items")
    found_any = False
    
    if has_reddit:
        fav_reddit = posts_df[posts_df["id"].astype(str).isin(st.session_state.favorite_posts)]
        if not fav_reddit.empty:
            found_any = True
            st.markdown("#### Reddit Posts")
            for _, row in fav_reddit.iterrows():
                render_post_card(row, str(row["id"]) in st.session_state.read_posts)
                
    if has_news:
        fav_news = news_df[news_df["article_id"].astype(str).apply(lambda x: f"dsr_{x}").isin(st.session_state.favorite_posts)]
        if not fav_news.empty:
            found_any = True
            st.markdown("#### Daily Star News")
            for _, row in fav_news.iterrows():
                render_article_card(row, f"dsr_{row['article_id']}" in st.session_state.read_posts)
                
    if has_ritholtz:
        fav_rith = ritholtz_df[ritholtz_df["article_id"].astype(str).apply(lambda x: f"rth_{x}").isin(st.session_state.favorite_posts)]
        if not fav_rith.empty:
            found_any = True
            st.markdown("#### AM Reads")
            for _, row in fav_rith.iterrows():
                render_ritholtz_card(row, f"rth_{row['article_id']}" in st.session_state.read_posts)
                
    if not found_any:
        st.info("You haven't favorited any items yet. Click the '☆ Fav' button on any post to save it here!")

st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
st.markdown(
    '<p class="footer-text">Read posts are saved to disk and persist across sessions.</p>',
    unsafe_allow_html=True,
)

