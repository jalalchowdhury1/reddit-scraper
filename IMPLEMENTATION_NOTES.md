# Daily Star News Tab — Implementation Complete

## What Was Added

### 1. Configuration (`config.py`)
- **`DAILYSTAR_FEEDS`**: 5 RSS feed URLs from thedailystar.net
  - business, business/economy, news/bangladesh, opinion, news
- **`NEWS_CATEGORIES`**: 3 keyword categories with 270+ phrase keywords
  - India-Bangladesh Relations (cyan badge)
  - Bangladesh Economy (orange badge)  
  - Good News (green badge)

### 2. News Scraper (`scrape_dailystar.py`)
- Fetches RSS feeds using `requests` + `xml.etree.ElementTree`
- Strips HTML from descriptions with BeautifulSoup
- Matches articles via case-insensitive substring search
- Saves matched articles to `data/dailystar/articles.csv`
- One article can match multiple categories (separate CSV rows)
- Polite 1.5s delay between feeds

**Run it**: `python3 scrape_dailystar.py`

### 3. Dashboard Styling (`style.css`)
- `.news-cat-relations` — cyan badge
- `.news-cat-economy` — orange badge  
- `.news-cat-goodnews` — green badge
- `.news-date` — yellow monospace date display
- `.news-keywords` — muted matched-keywords text

### 4. Dashboard Tab (`dashboard.py`)
- `load_news_articles()` — loads news CSV with safe defaults
- `render_article_card()` — card with category badge, date, title, preview, author, keywords, buttons
- `render_news_tab()` — category filter, date sort, 50-article pagination
- Read tracking uses `dsr_{article_id}` prefix to prevent collision with Reddit IDs
- Added 5th metric to stats row (News count)
- All 3 tabs work independently or together

### 5. Documentation (`CLAUDE.md`)
- Updated project description, structure, data flow
- Documented news CSV format and categories
- Added troubleshooting section
- Updated "How to Run" with news scraper

## How Read Tracking Works

**Same JSON file** (`data/read_posts.json`) tracks both Reddit + news:
- Reddit posts: bare ID (e.g., `"1r2vnhs"`)
- News articles: prefixed ID (e.g., `"dsr_464356fa75d5"`)

No collision possible. Atomically saved on each mark/unmark.

## CSV Schema

`data/dailystar/articles.csv`:
```
article_id, title, url, description, pub_date, author, 
category, matched_keywords, feed_source, scraped_at
```

## Testing

Run the scraper:
```bash
python3 scrape_dailystar.py
```

Output:
- Fetches 50 articles from 5 feeds (10 per feed)
- Deduplicates to ~36 unique articles
- Matches keyword categories, saves matched articles to CSV
- Run 2-3 times to test dedup and update logic

Run the dashboard:
```bash
streamlit run dashboard.py
```

Tabs:
1. **Monthly Top** — Reddit monthly posts with subreddit filter
2. **Yearly Top** — Reddit yearly posts with subreddit filter  
3. **Daily Star News** — News articles with category filter

Stats row shows: Monthly, Yearly, News, Unread, Total counts

## Why Only 2 Matched Articles?

The Daily Star's recent articles don't heavily feature:
- India-Bangladesh relation keywords
- Good news keywords  
- Economy keywords that match our phrase list

This is expected behavior. More matches will appear as:
- News changes (India-Bangladesh border news, economic announcements, etc.)
- You refine keyword phrases in `config.py`

## Bug Fixes Applied

1. **XML parsing**: Fixed `findtext()` not extracting from nested HTML tags (e.g., `<title><a>...</a></title>`)
   - Added `_get_element_text()` recursive function
   - Now properly extracts title and description from HTML-wrapped elements

2. **Date parsing**: Uses `email.utils.parsedate_to_datetime()` for RFC 822 dates
   - Falls back to raw string if parse fails
   - Safe error handling

3. **Article ID generation**: Uses numeric GUID when available, falls back to link hash
   - Ensures stable IDs across rescapes

## Key Design Decisions

- **RSS over HTML scraping**: 50 articles/day available without following links
- **No new dependencies**: All libraries already in requirements.txt
- **Prefix-based read tracking**: `dsr_` prevents ID collision, single JSON file
- **Keyword matching**: Substring search (case-insensitive) on title + description
- **Multi-category articles**: One row per matching category
- **Dashboard gracefully handles**: Reddit-only, news-only, or both data sources

## Next Steps (Optional)

1. **Customize keywords**: Edit `config.py` → `NEWS_CATEGORIES` for better matches
2. **Add more feeds**: Add URLs to `DAILYSTAR_FEEDS` list
3. **Automate scraping**: Add Daily Star to `scheduler.py` (calls `scrape_dailystar.py` daily)
4. **Filter by date**: Modify `render_news_tab()` to add date range picker
5. **Export matched articles**: Add download CSV button to news tab

