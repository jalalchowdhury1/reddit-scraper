# Daily Reader - LLM Master Instructions

## 1. Project Overview
This project is a static, serverless news and Reddit aggregator. It runs via Python scrapers executed daily on GitHub Actions, which generate static JSON/CSV files. The frontend is a vanilla HTML/JS/CSS single-page application hosted on Vercel. 

**CRITICAL RULE:** Do NOT add complex backend frameworks (Flask, Django, Node.js), databases, or API keys unless explicitly instructed by the user. Rely on the existing static file generation architecture.

## 2. Scraper Architecture & Fallback Systems

### Reddit Scraper (`core/scrape_top.py`)
GitHub Actions uses Azure Data Center IPs, which are strictly rate-limited and often receive `403 Forbidden` errors from Reddit. Because of this, the Reddit scraper uses a "Triple-Threat" fallback system:
1. **Primary (Stealth JSON):** Hits `old.reddit.com/r/{sub}/top.json`. Requires robust macOS/Chrome `HEADERS`, handles `429` rate limits with a 30-second backoff, and skips stickied/video posts.
2. **Secondary (HTML):** Fallback web scraping if JSON fails.
3. **Tertiary (RSS):** Ultimate fallback hitting Reddit's RSS feeds.

**Reddit Scoring Algorithm (Crucial for UI Sorting):**
Because RSS and HTML fallbacks do not provide real upvote counts, we use a "Tiered Priority Exponential Decay" algorithm to simulate scores. This ensures high-signal subreddits naturally float to the top of the user's combined feed.
* **Tier 1 (75k-100k base):** `bestof`, `explainlikeimfive`, `todayilearned`
* **Tier 2 (40k-70k base):** `TrueReddit`, `dataisbeautiful`, `PersonalFinance`
* **Tier 3 (15k-35k base):** Default for all others
* *Decay Formula:* `int(base_max_score * (0.88 ** index)) + random.randint(100, 999)`
* *Do NOT change this scoring math without permission.*

**Anti-Bot Protections:**
* Always use `random.uniform(6.5, 12.5)` for delays between subreddit requests to simulate human jitter. Fixed delays (e.g., `time.sleep(3)`) will get the scraper banned.

### Ritholtz AM Reads Scraper (`core/scrape_ritholtz.py`)
* **Parsing Rules:** Must only grab the *first* `<a>` tag within list items (`<li>`) to avoid duplicating "see also" links.
* **Filters:** Must strictly ignore any internal links containing `ritholtz.com`.
* **Formatting:** Must strip leading bullets (`•`) and whitespace from titles.
* **Limit:** Hard limit of 12 items to ensure the full list is captured without overflowing.

## 3. Frontend & UI Logic (`index.html`)

* **"Show Read" Toggle:** This acts as a strict master switch. The logic `if (!showRead && isRead && currentTab !== 'favorites') { return; }` ensures that read items are hidden from all main feeds (Monthly, Yearly, AM Reads), even if they are favorited. Favorited items are only persistently visible on the dedicated 'Favorites' tab.
* **Score Formatting:** Uses a JS helper `formatScore()` to convert large integers into clean text (e.g., `84500` becomes `84.5k pts`).
* **State Management:** Read status and Favorites are stored entirely in `localStorage`. Do not attempt to move this to a database.

## 4. Automation & Deployment (`.github/workflows/daily_scrape.yml`)
* The scraper is scheduled via cron to run at `0 10 * * *` (10:00 AM UTC / 5:00 AM EST) daily.
* Always include `workflow_dispatch` so the user can trigger manual runs.
* Upon successful completion, GitHub Actions commits the generated data to the `main` branch, which automatically triggers a Vercel deployment.
