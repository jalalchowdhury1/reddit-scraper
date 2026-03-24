# 📂 Daily Reader (Reddit & News Aggregator)

🤖 **LLM System Context (Read This First)**

This is a hybrid-architecture application designed for zero-cost deployment and cross-device sync.

**Backend:** FastAPI (`server.py`) serving static CSV files from `/data`.

**Automation:** GitHub Actions runs scrapers in `/core` daily and commits CSVs back to the repo.

**Frontend:** Single-page app (`templates/index.html`) using Tailwind CSS and Firebase.

**State Management:** CRITICAL. Favorites and "Read" statuses are synced via Firebase Firestore on the client side to bypass Vercel's read-only filesystem.

---

## 🏗️ Architecture Map

### Data Layer (`/data`)
- CSVs for Reddit, AM Reads, and Google News

### Scraper Layer (`/core`)
- `scrape_top.py`: Triple-redundant custom web scraper (JSON → HTML → RSS). No Reddit API Key needed.
  - **Primary (Stealth JSON):** Hits `old.reddit.com/r/{sub}/top.json`. Requires robust macOS/Chrome `HEADERS`, handles `429` rate limits with a 30-second backoff, and skips stickied/video posts.
  - **Secondary (HTML):** Fallback web scraping if JSON fails.
  - **Tertiary (RSS):** Ultimate fallback hitting Reddit's RSS feeds.
- `scrape_ritholtz.py`: Financial link aggregator (10 articles daily from the AM Reads newsletter).
- `scrape_googlenews.py`: Filtered news aggregator for Bangladesh-specific news.

### Deployment
- `vercel.json`: Python builder for FastAPI
- `.github/workflows/daily_scrape.yml`: Morning CRON job (10:00 UTC / 5:00 AM EST)

---

## 🚨 Deployment & Vercel Limitations (CRITICAL Rules for LLMs)
If you are an LLM assisting with this repository, **you must obey these rules** to prevent breaking the Vercel production deployment:

1. **Strict Dependency Split (250MB Lambda Limit):** 
   - AWS Python Lambdas on Vercel hard-crash if the unzipped package exceeds 250MB.
   - **DO NOT** add heavy data science libraries (`streamlit`, `lxml`, `beautifulsoup4`) to `requirements.txt`.
   - `requirements.txt` MUST ONLY contain the bare minimum for FastAPI (`fastapi`, `uvicorn`, `pandas`, `Jinja2`). 
   - Put GitHub scraper dependencies in `requirements-scraper.txt`.
   - Put local dashboard dependencies in `requirements-dev.txt`.
2. **Legacy Vercel Configuration (`vercel.json`):** 
   - This project correctly relies on the legacy `builds` API for `@vercel/python`. 
   - **DO NOT** use the top-level `functions` property to configure files; it conflicts and crashes schema validation. 
   - If you need to include static files (like templates or data), pass an array to `config.includeFiles` strictly nested inside the `builds` wrapper.
3. **Absolute Paths Only (`server.py`):** 
   - Vercel Serverless Functions execute in isolated, fluctuating `/var/task` directories. 
   - **DO NOT** use relative string formats to find files. 
   - Always derive absolute paths dynamically via `BASE_DIR = Path(__file__).resolve().parent`.
4. **Starlette Compatibility (`TemplateResponse`):** 
   - Vercel routinely pulls the latest minor versions of `fastapi` and `starlette` dynamically. 
   - Newer `starlette` releases crash instantly if `TemplateResponse` receives positional arguments. 
   - You MUST use explicit keyword arguments: `templates.TemplateResponse(request=request, name="index.html")`.

---

## 📊 Subreddits Tracked (14 Communities)

1. `r/dataisbeautiful` - Data Is Beautiful
2. `r/todayilearned` - Today I Learned
3. `r/sobooksoc` - So many books, so little time
4. `r/Fitness` - Fitness
5. `r/getmotivated` - Get Motivated!
6. `r/UnethicalLifeProTips` - Unethical Life Pro Tips
7. `r/LifeProTips` - Life Pro Tips
8. `r/TrueReddit` - TrueReddit
9. `r/UpliftingNews` - Uplifting News
10. `r/lifehacks` - Lifehacks
11. `r/Productivity` - Productivity
12. `r/PersonalFinance` - Personal Finance
13. `r/explainlikeimfive` - Explain Like I'm Five
14. `r/bestof` - Best Of Reddit

---

## 🧠 Reddit Scoring Algorithm

Because RSS and HTML fallbacks do not provide real upvote counts, we use a "Tiered Priority Exponential Decay" algorithm to simulate scores. This ensures high-signal subreddits naturally float to the top.

| Tier | Base Score | Subreddits |
|------|------------|------------|
| Tier 1 | 75k-100k | `bestof`, `explainlikeimfive`, `todayilearned` |
| Tier 2 | 40k-70k | `TrueReddit`, `dataisbeautiful`, `PersonalFinance` |
| Tier 3 | 15k-35k | Default for all others |

**Decay Formula:** `int(base_max_score * (0.88 ** index)) + random.randint(100, 999)`

*Do NOT change this scoring math without permission.*

---

## 🛠️ Troubleshooting & Known Behaviors

### Sync Issues
- Check the Sync Key at the bottom of the Favorites tab
- Ensure `cloudReadPosts` and `cloudFavorites` are pulling from the same Firebase group

### GitHub Action Failures
- The GitHub Action uses `git add -f data/` to bypass the .gitignore
- Ensure `requirements.txt` includes `streamlit` and `pandas`

### Reddit Blocks (429/403 Errors)
- GitHub Actions uses Azure Data Center IPs, which are strictly rate-limited
- If 429 errors occur, increase the jitter sleep delay in `scrape_top.py`
- Always use `random.uniform(6.5, 12.5)` for delays between subreddit requests to simulate human jitter
- Fixed delays (e.g., `time.sleep(3)`) will get the scraper banned

### Frontend Behavior
- **"Show Read" Toggle:** Acts as a strict master switch. The logic `if (!showRead && isRead && currentTab !== 'favorites') { return; }` ensures that read items are hidden from all main feeds (Monthly, Yearly, AM Reads), even if they are favorited. Favorited items are only persistently visible on the dedicated 'Favorites' tab.
- **Score Formatting:** Uses JS helper `formatScore()` to convert large integers into clean text (e.g., `84500` becomes `84.5k pts`)
- **State Management:** Read status and Favorites are stored in `localStorage` AND synced via Firebase Firestore for cross-device sync

### Ritholtz Scraper Rules
- Must only grab the *first* `<a>` tag within list items (`<li>`) to avoid duplicating "see also" links
- Must strictly ignore any internal links containing `ritholtz.com`
- Must strip leading bullets (`•`) and whitespace from titles
- Hard limit of 12 items

---

## 🚀 Commands

### Local Dashboard
```bash
streamlit run dashboard.py
```

### Local Web App
```bash
uvicorn server:app --reload
```

### Manual Scraping
```bash
# Scrape all subreddits
python -m core.scrape_top

# Scrape specific subreddit
python -m core.scrape_top python --mode history --limit 50
```

---

## 📁 Project Structure

```
Reddit Scraping/
├── server.py                 # FastAPI backend
├── dashboard.py             # Streamlit dashboard
├── config.py                 # Configuration
├── database.py               # Database models
├── requirements.txt          # Python dependencies
├── vercel.json              # Vercel deployment config
├── .github/workflows/
│   └── daily_scrape.yml     # Daily CRON job
├── core/                     # Scraper modules
│   ├── scrape_top.py        # Triple-redundant Reddit scraper
│   ├── scrape_ritholtz.py   # Financial articles scraper
│   └── scrape_googlenews.py # Bangladesh news scraper
├── data/                     # CSV data storage
│   ├── r_subreddit/         # Reddit data
│   ├── ritholtz.csv         # AM Reads
│   └── googlenews.csv       # Google News
└── templates/
    └── index.html           # Frontend SPA
```

---

## ⚙️ Prerequisites

- Python 3.8+
- Firebase project (for Firestore sync)
- Vercel account (for deployment)

---

## 🔧 Docker Usage (Optional)

```bash
# Start all services
docker compose up -d

# Start ScrapeServ only (for screenshots)
docker compose up -d scraper
```

---

*Built with ❤️ using Python + FastAPI + Tailwind CSS + Firebase*

---

## 📝 Version History

- **v1.1** - Current release

