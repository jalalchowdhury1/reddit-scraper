# LLM Startup Guide — Reddit Daily Dashboard + Daily Star News

**READ THIS FIRST before making any changes or troubleshooting.**

---

## 🎯 Project Overview

This is a dual-source content aggregation + curation dashboard:

1. **Reddit Aggregator**: Scrapes top posts from 13 subreddits (monthly + yearly)
2. **Daily Star News Browser**: Scrapes The Daily Star (Bangladesh) RSS feeds and matches articles to 3 keyword categories
3. **Unified Dashboard**: Displays both in 3 tabs with persistent read tracking

**Current Status**: ✅ Fully functional. 2+ matched news articles, 580+ Reddit posts.

---

## 📁 Project Structure

```
Reddit Scraping/
├── config.py                    # CENTRAL CONFIG — all settings here
├── dashboard.py                 # MAIN UI (3 tabs, read tracking)
├── scrape_top.py               # Reddit scraper (old.reddit.com JSON API)
├── scrape_dailystar.py         # Daily Star scraper (RSS + keyword matching)
├── style.css                   # Tokyo Night theme + badges
├── CLAUDE.md                   # Architecture documentation (for devs)
├── IMPLEMENTATION_NOTES.md     # Design decisions + bug fixes
├── READ_ME_FIRST_FOR_LLM.md   # THIS FILE
├── requirements.txt            # Python dependencies
├── data/
│   ├── r_*/posts.csv          # Reddit monthly posts
│   ├── r_*_yearly/posts.csv   # Reddit yearly posts
│   ├── dailystar/articles.csv # Daily Star news (keyword-matched)
│   └── read_posts.json         # Read tracking (user edits via UI)
└── venv/                       # Python virtual environment
```

---

## 🚀 Quick Start

### 1. Run Both Scrapers

```bash
cd "/Users/jalalchowdhury/PycharmProjects/Reddit Scraping"
python3 scrape_top.py         # Fetch Reddit posts (takes ~1-2 min)
python3 scrape_dailystar.py   # Fetch news articles (takes ~10-20 sec)
```

### 2. Launch Dashboard

```bash
streamlit run dashboard.py
```

Opens browser at: `http://localhost:8501`

### 3. Use the Dashboard

- **Tab 1 (Monthly Top)**: Reddit monthly posts, filter by subreddit, sort by score/comments
- **Tab 2 (Yearly Top)**: Reddit yearly posts, same filters
- **Tab 3 (Daily Star News)**: News articles, filter by category (Relations/Economy/Good News)
- **Mark as Read**: Click button → post hidden on refresh (across sessions)
- **Sidebar**: Toggle "Show read posts", clear all read markers

---

## 🧠 How It Works (Architecture for LLMs)

### Data Flow: Reddit Posts

```
old.reddit.com/r/{subreddit}/top.json
        ↓
  scrape_top.py (requests + JSON)
        ↓
  data/r_{subreddit}/posts.csv (monthly)
  data/r_{subreddit}_yearly/posts.csv (yearly)
        ↓
  dashboard.py (loads CSVs, renders cards)
        ↓
  User marks read → stored in data/read_posts.json
```

### Data Flow: News Articles

```
thedailystar.net/{section}/rss.xml (5 feeds)
        ↓
  scrape_dailystar.py (requests + xml.etree)
        ↓
  Strips HTML from descriptions
        ↓
  Matches against 3 keyword categories (case-insensitive substring search)
        ↓
  data/dailystar/articles.csv (one row per category match)
        ↓
  dashboard.py (loads CSV, renders cards, filters by category)
        ↓
  User marks read → stored in data/read_posts.json with "dsr_" prefix
```

### Read Tracking System

**File**: `data/read_posts.json` (JSON array of IDs)

**Two ID Formats** (no collision):
- Reddit posts: bare ID → `"1r2vnhs"`
- News articles: prefixed → `"dsr_464356fa75d5"`

**Behavior**:
1. Load on dashboard startup
2. Mark post as read → add ID to set
3. Click button → update set, atomically save JSON
4. Page rerun → filtered posts hidden
5. Browser refresh → JSON reloaded, posts still hidden
6. Next session → JSON reloaded again, state persists

**Why atomic writes?**: Prevents file corruption if process crashes mid-write.

---

## ⚙️ Configuration (All in `config.py`)

### Add/Remove Reddit Subreddits

```python
# config.py, line ~48
SUBREDDITS = [
    {"name": "dataisbeautiful", "display_name": "Data Is Beautiful"},
    # ADD MORE HERE
]
```

Then run `python3 scrape_top.py` → new subreddit data saved.

### Add/Remove Daily Star RSS Feeds

```python
# config.py, line ~70
DAILYSTAR_FEEDS = [
    "https://www.thedailystar.net/business/rss.xml",
    # ADD MORE HERE
]
```

Then run `python3 scrape_dailystar.py` → new feed fetched.

### Modify Keyword Categories

```python
# config.py, line ~79 (NEWS_CATEGORIES)
# Each category has: name, badge_class (CSS), keywords (list of phrases)

# CASE-INSENSITIVE SUBSTRING MATCHING:
# If "gdp growth" is in keywords and article contains "The GDP growth is strong..."
# → Article matches this category
```

**How to improve matches**:
1. Run `python3 scrape_dailystar.py` → fetches 50 articles
2. Check `data/dailystar/articles.csv` for matches
3. Add more specific keywords to `NEWS_CATEGORIES` in `config.py`
4. Run scraper again → more articles should match

---

## 🐛 Troubleshooting (For LLMs)

### Problem: "No posts found" on dashboard

**Cause**: No CSV data in `data/` directory

**Fix**:
```bash
python3 scrape_top.py
```

Check if files created:
```bash
ls data/r_*/posts.csv | head -3
```

### Problem: "No news articles found" in Daily Star tab

**Cause**: Either no CSV exists, or no keyword matches

**Fix**:
```bash
python3 scrape_dailystar.py
```

Check output:
```
Total articles fetched: X
Unique articles: Y
Matched articles (with categories): Z  # Should be > 0
```

If Z = 0, keywords don't match current news. Edit `config.py` to add keywords.

### Problem: Dashboard crashes with error

**Debug steps**:

1. **Check Python syntax**:
   ```bash
   python3 -m py_compile dashboard.py scrape_dailystar.py config.py
   ```

2. **Check if CSS file exists**:
   ```bash
   ls -la style.css
   ```

3. **Check if data files are readable**:
   ```bash
   head -5 data/dailystar/articles.csv
   head -5 data/r_dataisbeautiful/posts.csv
   ```

4. **Look at error message** — usually indicates missing column or corrupt CSV

### Problem: Posts keep reappearing after marking as read

**Cause**: Read keys don't match

**Check**: Look at `data/read_posts.json`
```bash
cat data/read_posts.json
```

Should contain:
- Reddit IDs: `"1r2vnhs"` (bare)
- News IDs: `"dsr_464356fa75d5"` (with prefix)

If missing prefix, manually add and retry.

### Problem: Dashboard runs but sidebar doesn't show

**Cause**: CSS not loading

**Fix**:
```bash
# Check file exists
ls style.css

# Check Streamlit can read it
head -10 style.css
```

Restart dashboard:
```bash
streamlit run dashboard.py --logger.level=debug
```

---

## 📊 CSV Schemas (For LLMs)

### Reddit Posts: `data/r_*/posts.csv` & `data/r_*_yearly/posts.csv`

```
id, title, author, created_utc, permalink, url, score, upvote_ratio,
num_comments, num_crossposts, selftext, post_type, is_nsfw, is_spoiler,
flair, total_awards, has_media, media_downloaded, time_filter, source
```

**Dashboard uses**: `id`, `title`, `score`, `num_comments`, `author`, `permalink`, `selftext`

**Others**: Optional (safely defaulted if missing)

### News Articles: `data/dailystar/articles.csv`

```
article_id, title, url, description, pub_date, author, category,
matched_keywords, feed_source, scraped_at
```

**Dashboard uses all fields** — all required

**Deduplication key**: `(article_id, category)` — same article matching different categories = separate rows

---

## 🔧 Common Tasks for LLMs

### Task: Add a new subreddit

1. Edit `config.py`:
   ```python
   SUBREDDITS = [
       # ... existing ...
       {"name": "new_subreddit_name", "display_name": "Human-Readable Name"},
   ]
   ```

2. Run scraper:
   ```bash
   python3 scrape_top.py
   ```

3. Check output:
   ```
   📡 Fetching r/new_subreddit_name top month...
   ✅ Got X posts from r/new_subreddit_name
   ```

### Task: Add a new Daily Star RSS feed

1. Find feed URL (pattern: `https://www.thedailystar.net/{section}/rss.xml`)

2. Edit `config.py`:
   ```python
   DAILYSTAR_FEEDS = [
       # ... existing ...
       "https://www.thedailystar.net/new-section/rss.xml",
   ]
   ```

3. Run scraper:
   ```bash
   python3 scrape_dailystar.py
   ```

### Task: Improve keyword matching

1. Check current matches:
   ```bash
   python3 scrape_dailystar.py | grep "Matched articles"
   ```

2. Run scraper once manually:
   ```bash
   python3 scrape_dailystar.py
   cat data/dailystar/articles.csv | cut -d',' -f2,7 | head -5
   # Shows: title, category
   ```

3. Analyze articles not matching:
   - Read titles + descriptions
   - Identify missing keywords
   - Add to `config.py` → `NEWS_CATEGORIES` → `keywords` list

4. Re-run scraper:
   ```bash
   python3 scrape_dailystar.py
   # Should see higher "Matched articles" count
   ```

### Task: Debug why a post marked as read reappeared

1. Check read tracking file:
   ```bash
   cat data/read_posts.json | python3 -m json.tool
   ```

2. Look for article ID in list:
   - Reddit: `"1r2vnhs"` (bare)
   - News: `"dsr_464356fa75d5"` (with prefix)

3. If missing:
   - Check sidebar in dashboard: "Posts marked read: X"
   - Click "Clear all read markers"
   - Mark post as read again

4. If still broken:
   - Check dashboard error logs (bottom of terminal)
   - Verify CSV files are not corrupt

---

## 💾 Database Schema

**Note**: The SQLite database (`reddit_daily.db`) exists but is **NOT used by the dashboard**.
Ignore it. All data flows through CSV files instead.

---

## 🎨 Styling (CSS)

**File**: `style.css`

**Main elements**:
- `.subreddit-badge` → Blue badge (Reddit subreddit name)
- `.time-filter-badge` → Teal badge (MONTH/YEAR)
- `.read-badge` → Gray badge (READ status)
- `.news-cat-relations` → Cyan badge (India-Bangladesh Relations)
- `.news-cat-economy` → Orange badge (Bangladesh Economy)
- `.news-cat-goodnews` → Green badge (Good News)
- `.news-date` → Yellow monospace date
- `.news-keywords` → Muted matched keywords

All use Tokyo Night color variables (`:root { --tn-* }`)

To customize:
1. Edit `style.css`
2. Refresh dashboard browser
3. Changes apply immediately

---

## 🧪 Testing Checklist (For LLMs)

When code changes are made, test these scenarios:

- [ ] `python3 -m py_compile *.py` — all files have valid syntax
- [ ] `python3 scrape_top.py` — Reddit scraper works (creates CSVs)
- [ ] `python3 scrape_dailystar.py` — News scraper works (creates CSV)
- [ ] `streamlit run dashboard.py` — dashboard starts without errors
- [ ] Dashboard loads all 3 tabs
- [ ] Can toggle "Show read posts" without crashes
- [ ] Can mark a post as read → post disappears
- [ ] Can unmark → post reappears
- [ ] Read status persists after browser refresh
- [ ] No errors in browser console (F12)

---

## 📝 Code Conventions for LLMs

### File Headers

Every Python file starts with:
```python
"""
One-line description
=========================

WHAT IT DOES:
- Bullet point 1
- Bullet point 2

KEY FEATURES:
- Feature 1

USAGE:
    command or example

IMPORTANT FOR LLMs:
- Note about edge cases
- Common mistakes to avoid
"""
```

### Function Docstrings

Every function has:
```python
def function_name(arg: type) -> return_type:
    """
    One-line summary.

    Args:
        arg (type): Description

    Returns:
        type: Description

    Example:
        >>> function_name(value)
        result
    """
```

### Section Markers

Code organized into sections:
```python
# ============================================================================
# SECTION NAME
# ============================================================================
# Code goes here
```

---

## 🚨 Critical Rules

1. **Never edit `data/read_posts.json` manually** — use dashboard UI
2. **Never edit CSV files manually** — they're auto-generated, edits get overwritten
3. **Always run scrapers before dashboard** — dashboard reads CSVs created by scrapers
4. **Keep `config.py` as single source of truth** — all settings there
5. **Test syntax before running**: `python3 -m py_compile file.py`
6. **Check file exists before reading**: RSS feeds, CSV files, CSS file
7. **Use atomic writes for JSON** — prevents corruption on crash

---

## 🎯 For LLM: Recommended Order for Any Task

1. **Read** the relevant docstrings at top of file
2. **Read** CLAUDE.md section on that component
3. **Read** function docstrings for the functions you'll modify
4. **Run tests** to verify current behavior
5. **Make minimal changes** (only what's needed)
6. **Test syntax**: `python3 -m py_compile file.py`
7. **Run scrapers** if you changed data loading
8. **Test dashboard** by actually using it
9. **Document your changes** in code comments

---

## 📚 Related Documentation

- **CLAUDE.md** — Architecture, design decisions, critical files table
- **IMPLEMENTATION_NOTES.md** — Why things are done this way, bug fixes applied
- **config.py** — Inline comments explaining every setting
- **scrape_dailystar.py** — Detailed comments for every function
- **dashboard.py** — Detailed comments for every function

---

## 🆘 If Something Goes Wrong

1. **Don't panic** — most issues are simple misconfigurations
2. **Check the 3 common causes**:
   - Missing CSV files (run scrapers)
   - Corrupt JSON (delete `data/read_posts.json`, recreate via UI)
   - Missing CSS file (ensure `style.css` in current directory)
3. **Read error message** — Streamlit errors are usually very descriptive
4. **Check logs** — terminal where `streamlit run` was executed
5. **Verify files exist**:
   ```bash
   ls config.py dashboard.py scrape_*.py style.css data/
   ```

---

## 🎓 Learning Resources

**To understand the code**:
1. Start with `config.py` — understand the data structure
2. Read `scrape_dailystar.py` — understand news scraping
3. Read `dashboard.py` → understand UI rendering
4. Read `CLAUDE.md` → understand architecture

**To make changes**:
1. Identify which file needs editing (see "Critical Files" in CLAUDE.md)
2. Read that file's docstring
3. Read function you're modifying
4. Make minimal change
5. Test it (run scraper or dashboard)

---

**Last Updated**: 2026-02-26
**Version**: 1.0 (Initial LLM-optimized release)
**Status**: ✅ Production ready
