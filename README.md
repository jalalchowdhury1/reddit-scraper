# Daily Reader

One page for the day's reading: the top posts from 13 subreddits, Bangladesh news, and the
Ritholtz AM Reads + SatPost newsletters. Read/favorite state syncs across devices.

**Live:** https://reddit-scraper-lyart.vercel.app · **Health:** `/api/status`

> **Working on this repo? Read [`AGENTS.md`](AGENTS.md) first.** It is the source of truth:
> every scraper, the API, the hard rules, tests, monitoring and a runbook. This page is the
> short version.

## How it works

```
Mac mini (07:35 + 19:35)          GitHub Actions (nightly + mornings)
headless browser → Reddit         News, AM Reads, SatPost, Reddit backup
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
  blocks GitHub's servers. It saves real upvotes. If the Mac misses a list for 36 hours,
  GitHub's RSS backup (`core/scrape_top.py`) refills it, showing each post's rank instead of
  upvotes. No Reddit API key anywhere.
- **Tabs:** Monthly and Yearly = the top 50 of all tracked subs, mixed by a tier score so one
  big sub can't take over. News = every story from the last 7 days. AM Reads = today's list only.
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
