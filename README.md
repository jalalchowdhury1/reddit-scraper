# Daily Reader

One page for the day's reading: the top posts from 13 subreddits, Bangladesh news, the
Ritholtz AM Reads + SatPost newsletters, and GitHub's trending top 10. Read/favorite state syncs across devices.

**Live:** https://reddit-scraper-lyart.vercel.app · **Health:** `/api/status`

> **Working on this repo? Read [`AGENTS.md`](AGENTS.md) first.** It is the source of truth:
> every scraper, the API, the hard rules, tests, monitoring and a runbook. This page is the
> short version.

## How it works

```
Mac mini (07:35 + 19:35)          GitHub Actions (nightly + mornings + every 6 h)
headless browser → Reddit         News, AM Reads, SatPost, Reddit backup, GitHub Trending
          \                          /
           CSV files in data/, pushed to main
                      │  Vercel redeploys on every push
                      ▼
      server.py (FastAPI) → /api/data → templates/index.html
                      │
        read + favorites ↔ localStorage ↔ Firebase
```

- **Reddit** comes from a real headless browser on the owner's Mac mini
  (`core/scrape_reddit_browser.py`, run by launchd via `mac/reddit-browser.sh`), because Reddit
  blocks GitHub's servers. It saves real upvotes. Each list has backups on the Mac: the page,
  then Reddit's JSON through the same browser, then its RSS feed, then a fresh browser profile.
  Every run ends with a `METHOD CHECK` line saying whether each backup still works. If the Mac
  misses a list for 36 hours, GitHub's RSS backup (`core/scrape_top.py`, every 3 hours) refills
  it, showing each post's rank instead of upvotes. No Reddit API key anywhere.
- **Tabs:** Monthly and Yearly = the top 50 of all tracked subs, mixed by a tier score so one
  big sub can't take over. That mix reshuffles on every scrape, so a post you haven't read yet
  stays at the bottom ("Still unread from earlier lists") until you read it, or 30 days after it left.
  News = every story from the last 7 days. AM Reads = today's list only. GitHub = the top 10
  of github.com/trending (today, GitHub's own order), refreshed every 6 hours
  (`core/scrape_github_trending.py`).
- **The 13 subs** live in `core/reddit_common.py`: dataisbeautiful, todayilearned, bestof,
  getmotivated, UnethicalLifeProTips, LifeProTips, TrueReddit, UpliftingNews, lifehacks,
  Productivity, PersonalFinance, explainlikeimfive, AskHistorians.

## Commands

```bash
.venv/bin/uvicorn server:app --reload          # local site: http://localhost:8000
.venv/bin/python -m pytest tests -q            # unit + robustness tests (~10 s)
python3 tests/e2e_site.py http://localhost:8000   # real-browser checks (needs Playwright)
```

Deploy = push to `main` (Vercel). Tests also run on GitHub for every code push.

## Rules that break production if ignored

1. Keep `requirements.txt` minimal (Vercel's 250 MB limit). Scraper libraries go in
   `requirements-scraper.txt`.
2. `vercel.json` uses the legacy `builds` API; bundled folders go in `config.includeFiles`.
3. `server.py` builds every path from `BASE_DIR`, and calls `TemplateResponse` with keyword args.
4. Files under `data/` must be added with `git add -f` (the folder is gitignored).
5. Never show an invented upvote number, and don't change the tier-score math without the
   owner's OK.

Details and the reasons behind each: [`AGENTS.md`](AGENTS.md) §5.
