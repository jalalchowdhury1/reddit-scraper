# Reddit Daily Dashboard — Project Documentation

> This file is optimized for LLM consumption. Read this FIRST before modifying any code.

---

## What This Project Does

A Reddit scraping and dashboard system that:
1. Scrapes top posts from 13 subreddits (monthly + yearly)
2. Scrapes The Daily Star (Bangladesh) news via RSS, matching articles to keyword categories
3. Saves everything to CSV files
4. Displays them in a Streamlit web dashboard (3 tabs: Monthly, Yearly, Daily Star News)
5. Lets the user mark posts/articles as "read" — read items stay hidden across sessions

---

## Project Structure

```
Reddit Scraping/
├── dashboard.py          # [MAIN UI] Streamlit dashboard — this is what the user sees
├── style.css             # [STYLING] Tokyo Night CSS theme for the dashboard
├── config.py             # [CONFIG] Subreddit list, paths, API keys
├── scraper_config.py     # [CONFIG] Advanced scraper settings (mirrors, rate limits)
├── scrape_top.py         # [SCRAPER] Simple top-posts fetcher (monthly + yearly)
├── scrape_dailystar.py   # [SCRAPER] Daily Star RSS news scraper (keyword matching)
├── scraper_main.py       # [SCRAPER] Full-featured universal scraper (CLI)
├── reddit_scraper.py     # [SCRAPER] PRAW-based scraper (requires Reddit API keys)
├── scheduler.py          # [AUTOMATION] Daily scheduled scraping at 8 AM
├── database.py           # [DATABASE] SQLAlchemy models (currently unused by dashboard)
├── scraper_client.py     # [OPTIONAL] ScrapeServ screenshot client
├── scraper/
│   ├── __init__.py
│   └── async_scraper.py  # [OPTIONAL] Async 10x speed scraper
├── data/                 # [OUTPUT] All scraped data lives here
│   ├── r_<subreddit>/posts.csv       # Monthly posts per subreddit
│   ├── r_<subreddit>_yearly/posts.csv # Yearly posts per subreddit
│   ├── dailystar/articles.csv        # Daily Star news articles (keyword-matched)
│   ├── read_posts.json               # Persistent read-tracking (JSON array of IDs)
│   ├── reddit_daily.db               # SQLite database (NOT used by dashboard)
│   └── screenshots/                  # Optional screenshots
├── requirements.txt
├── docker-compose.yml
├── .env.example          # Environment variable template
└── CLAUDE.md             # THIS FILE — read this first
```

---

## Key Data Flow

```
1. SCRAPING:
   python scrape_top.py
   → Fetches top 20 posts/subreddit from old.reddit.com JSON API
   → Saves to: data/r_<name>/posts.csv (monthly)
   → Saves to: data/r_<name>_yearly/posts.csv (yearly)
   → Merges with existing CSV (deduplicates by post ID)

2. DASHBOARD:
   streamlit run dashboard.py
   → Loads all data/r_*/posts.csv files
   → Loads data/read_posts.json for read tracking
   → Filters out read posts
   → Renders cards with Tokyo Night theme

3. NEWS SCRAPING:
   python scrape_dailystar.py
   → Fetches 5 RSS feeds from thedailystar.net using requests + xml.etree
   → Strips HTML from descriptions using BeautifulSoup
   → Matches articles against 3 keyword categories (case-insensitive)
   → Saves to: data/dailystar/articles.csv (merge/dedup by article_id + category)
   → An article can match multiple categories (creates separate rows)

4. MARK AS READ:
   User clicks "Mark Read" button
   → Reddit posts: bare ID added (e.g., "1r2vnhs")
   → News articles: prefixed ID added (e.g., "dsr_753291")
   → Set is atomically saved to data/read_posts.json
   → Dashboard reruns and hides the item
   → On next session: JSON is loaded, item stays hidden
```

---

## Critical Files — When to Edit What

| Task | File(s) to Edit |
|------|-----------------|
| Change dashboard appearance | `style.css` (CSS) and `dashboard.py` (layout) |
| Add/remove subreddits | `config.py` → `SUBREDDITS` list |
| Fix read tracking | `dashboard.py` → `load_read_posts()`, `save_read_posts()` |
| Change Reddit scraping behavior | `scrape_top.py` (simple) or `scraper_main.py` (advanced) |
| Change news scraping / keywords | `scrape_dailystar.py` + `config.py` → `NEWS_CATEGORIES` |
| Add/remove RSS feeds | `config.py` → `DAILYSTAR_FEEDS` list |
| Change scraping schedule | `scheduler.py` → `schedule.every().day.at("08:00")` |
| Add new CSV columns | `scrape_top.py` → `get_top_posts()` return dict |
| Change data directory | `config.py` → `DATA_DIR` |

---

## How Read Tracking Works (Important)

**Storage**: `data/read_posts.json` — a JSON array of ID strings.

**Key design choices**:
- Reddit posts use **bare post ID** (e.g., `"1r2vnhs"`). Marking read in Monthly also hides in Yearly.
- News articles use **`dsr_` prefix** (e.g., `"dsr_753291"`). This prevents collision with Reddit IDs.
- Both stored in the same JSON file — one unified read-tracking system.

**Persistence flow**:
1. On dashboard load: `load_read_posts()` reads the JSON file into a Python `set`
2. Stored in `st.session_state.read_posts` (survives Streamlit reruns within a session)
3. On mark-read click: ID is added to the set, then atomically written to JSON
4. On new session (new browser tab, server restart): JSON is re-read from disk
5. **Atomic writes**: Uses temp file + `os.replace()` to prevent corruption

**Legacy migration**: The loader strips `_month`/`_year` suffixes from old-format entries, so upgrading is seamless.

---

## CSV Format

Posts CSVs have these columns (both scrapers produce compatible output):

```
id, title, author, created_utc, permalink, url, score, upvote_ratio,
num_comments, num_crossposts, selftext, post_type, is_nsfw, is_spoiler,
flair, total_awards, has_media, media_downloaded, time_filter, source
```

The dashboard only requires: `id`, `title`, `score`, `num_comments`, `author`, `permalink`, `selftext`. Missing columns are safely defaulted.

### News CSV Format

`data/dailystar/articles.csv` columns:

```
article_id, title, url, description, pub_date, author, category,
matched_keywords, feed_source, scraped_at
```

The dashboard requires: `article_id`, `title`, `url`, `description`, `pub_date`, `author`, `category`, `matched_keywords`.

### News Categories (3 configured)

Defined in `config.py` → `NEWS_CATEGORIES`:
1. **India-Bangladesh Relations** (cyan badge) — 70+ keyword phrases
2. **Bangladesh Economy** (orange badge) — 100+ keyword phrases
3. **Good News** (green badge) — 100+ keyword phrases

Articles are matched via case-insensitive substring search on title + description. An article can match multiple categories.

---

## Subreddits (13 configured)

Defined in `config.py` → `SUBREDDITS`:
1. dataisbeautiful — Data Is Beautiful
2. todayilearned — Today I Learned
3. sobooksoc — So many books, so little time
4. Fitness — Fitness
5. getmotivated — Get Motivated!
6. UnethicalLifeProTips — Unethical Life Pro Tips
7. LifeProTips — Life Pro Tips
8. TrueReddit — TrueReddit
9. UpliftingNews — Uplifting News
10. lifehacks — Lifehacks
11. Productivity — Productivity
12. PersonalFinance — Personal Finance
13. explainlikeimfive — Explain Like I'm Five

To add a new subreddit: add to `config.py` SUBREDDITS list AND to `scrape_top.py` SUBREDDITS list.

---

## How to Run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Scrape Reddit data (run this first, or nothing will show)
python scrape_top.py

# 3. Scrape Daily Star news (keyword-matched articles)
python scrape_dailystar.py

# 4. Launch dashboard
streamlit run dashboard.py

# 5. (Optional) Start automated daily scraping
python scheduler.py
```

---

## Common Issues & Fixes

### "No posts found" on dashboard
- **Cause**: No CSV data in `data/` directory
- **Fix**: Run `python scrape_top.py` and/or `python scrape_dailystar.py` first

### "No news articles found" in Daily Star tab
- **Cause**: No `data/dailystar/articles.csv` or no keyword matches
- **Fix**: Run `python scrape_dailystar.py`. If still empty, check RSS feed availability.

### Posts reappear after marking as read
- **Cause (old)**: Read keys used `id_month` format, which could mismatch
- **Fix**: Now uses bare post ID. The loader auto-migrates old format entries.
- **Check**: Look at `data/read_posts.json` — should contain bare IDs like `["1r2vnhs", "abc123"]`

### Subreddit filter shows no results
- **Cause (old)**: Case sensitivity bug (`.lower()` mismatch)
- **Fix**: Subreddit dropdown now uses exact-match from the dataframe

### CSV loading errors
- **Cause**: Corrupt or empty CSV files
- **Fix**: Dashboard now skips bad CSVs with a warning log instead of crashing

### Dashboard looks wrong / unstyled
- **Cause**: `style.css` not found or not loaded
- **Fix**: Ensure `style.css` is in the project root (same dir as `dashboard.py`)

---

## Architecture Notes for AI Agents

- **The dashboard reads from CSVs, NOT from the SQLite database.** The `database.py` file exists but is only used by `reddit_scraper.py` (the PRAW-based scraper). The primary scraper (`scrape_top.py`) does not use the database.
- **Three scraper systems exist**: `scrape_top.py` (Reddit, simple), `scraper_main.py` (Reddit, advanced CLI), and `scrape_dailystar.py` (Daily Star news via RSS). The dashboard works with output from any combination.
- **The scheduler calls `scraper_main.py`**, not `scrape_top.py`. The scheduler produces CSVs in the same directory structure.
- **Streamlit reruns the entire script** on every user interaction. Session state (`st.session_state`) persists within a browser session. Cross-session persistence uses the JSON file.
- **CSS targets Streamlit internal class names** which can change between Streamlit versions. If styling breaks after a Streamlit upgrade, check `style.css` selectors.

---

## Dependencies

```
streamlit >= 1.28.0    # Dashboard framework
pandas >= 2.1.0        # Data processing
requests >= 2.31.0     # HTTP for scraping
beautifulsoup4         # HTML parsing (scraper_main.py)
sqlalchemy >= 2.0.0    # Database ORM (database.py)
schedule >= 1.2.0      # Job scheduling
python-dotenv          # .env loading
aiohttp                # Async scraper (optional)
aiofiles               # Async file I/O (optional)
```

---

## File Modification Safety

- **Safe to modify**: `dashboard.py`, `style.css`, `config.py`, `scrape_top.py`, `scrape_dailystar.py`
- **Modify with care**: `scraper_main.py` (complex, many features)
- **Do not modify unless you understand the schema**: `database.py`
- **Generated data (do not edit manually)**: `data/r_*/posts.csv`, `data/dailystar/articles.csv`, `data/read_posts.json`
