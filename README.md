# Reddit Daily Dashboard 📊

A beautiful dashboard to view and track the top posts from your favorite Reddit communities - daily updated with no duplicates!

**Uses the [Reddit Universal Scraper](https://github.com/ksanjeev284/reddit-universal-scraper/) - NO API KEYS REQUIRED!**

## Features

- 🎨 **Beautiful Dashboard** - Modern, dark-themed UI with Streamlit
- 📅 **Daily Updates** - Automatic daily scraping of top posts
- 🚫 **No Duplicates** - Tracks seen posts to avoid showing the same content twice
- 🗓️ **Sort by Time** - View top monthly and yearly posts separately
- 📸 **Screenshot Capture** - Uses ScrapeServ to take screenshots of posts
- 🔄 **13 Subreddits** - Tracks posts from diverse communities
- 🚀 **No API Keys Needed** - Uses web scraping instead of Reddit API

## Subreddits Tracked

1. r/dataisbeautiful - Data Is Beautiful
2. r/todayilearned - Today I Learned
3. r/sobooksoc - So many books, so little time
4. r/Fitness - Fitness
5. r/getmotivated - Get Motivated!
6. r/UnethicalLifeProTips - Unethical Life Pro Tips
7. r/LifeProTips - Life Pro Tips
8. r/TrueReddit - TrueReddit
9. r/UpliftingNews - Uplifting News
10. r/lifehacks - Lifehacks
11. r/Productivity - Productivity
12. r/PersonalFinance - Personal Finance
13. r/explainlikeimfive - Explain Like I'm Five

## Prerequisites

- Python 3.8+
- Docker & Docker Compose (optional, for screenshots)
- ffmpeg (optional, for video processing)

## Quick Start

### 1. Install Dependencies

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install requirements
pip install -r requirements.txt

# Install Playwright browsers (required for scraping)
playwright install
```

### 2. Run Initial Scrape

```bash
# Scrape all subreddits (history mode - fast, no media)
python scraper_main.py dataisbeautiful --mode history --limit 20
python scraper_main.py todayilearned --mode history --limit 20
# ... repeat for other subreddits

# Or use full mode (slower, includes media)
python scraper_main.py dataisbeautiful --mode full --limit 20
```

### 3. Launch Dashboard

```bash
streamlit run dashboard.py
```

The dashboard will open at http://localhost:8501

## Daily Usage

### Manual Scraping

```bash
# Scrape a single subreddit
python scraper_main.py python --mode history --limit 50

# Full scrape with media
python scraper_main.py python --mode full --limit 100
```

### Automated Daily Scraping

Start the scheduler to automatically scrape every day:

```bash
python scheduler.py
```

This will run the scraper daily at 8:00 AM (configurable in `scheduler.py`).

### Using the Built-in Dashboard

The Reddit Universal Scraper has its own built-in dashboard:

```bash
python scraper_main.py --dashboard
```

This opens http://localhost:8501 with:
- 📊 Overview - Stats & charts
- 📈 Analytics - Sentiment & keywords
- 🔍 Search - Query scraped data
- 💬 Comments - Comment analysis
- ⚙️ Scraper - Start new scrapes
- 📋 Job History - View all jobs
- 🔌 Integrations - API, export, plugins

### REST API

```bash
python scraper_main.py --api
```

Then visit http://localhost:8000/docs for API documentation.

## Project Structure

```
Reddit Scraping/
├── config.py              # Your dashboard config
├── database.py            # Database models
├── dashboard.py           # Your Streamlit dashboard
├── scheduler.py           # Daily scheduler
├── scraper_main.py        # Reddit Universal Scraper entry point
├── scraper/               # Scraper's core modules
├── requirements.txt       # Python dependencies
├── docker-compose.yml     # Docker services
└── data/                 # Data directory
    ├── r_subreddit/       # Scraped data (CSV/JSON)
    └── backups/           # Database backups
```

## Docker Usage (Optional)

For screenshots with ScrapeServ:

```bash
# Start ScrapeServ only
docker compose up -d scraper

# Or start the full stack with API
docker compose up -d
```

## Troubleshooting

### Playwright issues
```bash
playwright install chromium
```

### No data showing
Make sure you've run the scraper first:
```bash
python scraper_main.py dataisbeautiful --mode history --limit 20
```

### Dashboard not loading data
Check the data folder has CSV files:
```bash
ls -la data/r_dataisbeautiful/
```

## Credits

- [Reddit Universal Scraper](https://github.com/ksanjeev284/reddit-universal-scraper/) - The scraper engine
- [ScrapeServ](https://github.com/goodreasonai/ScrapeServ) - Screenshot capture

---

Built with ❤️ using Python + Streamlit
