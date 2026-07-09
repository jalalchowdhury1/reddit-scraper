# AGENTS.md — Daily Reader (Reddit & News Aggregator)

> **This is the single source of truth for anyone (human or AI) touching this repo.**
> Read it fully before changing code or deploying. It replaces the old `.llm-guide-index`
> (which pointed at LLM docs — `READ_ME_FIRST_FOR_LLM.md`, `CLAUDE.md`,
> `IMPLEMENTATION_NOTES.md`, `LLM_OPTIMIZATION_SUMMARY.md` — **that no longer exist**;
> the index has been deleted). `README.md` is the human/GitHub landing page and is kept.
> If something here is wrong, fix *this* file.

---

## 1. What this is

A **zero-cost personal reading dashboard**. It aggregates the top posts from ~14 subreddits
plus a few news/newsletter sources into one single-page web app, and syncs the user's
"read"/"favorite" state across devices via Firebase.

**Three moving parts, glued by a git repo:**

1. **Scrapers** (`core/*.py`) — run **daily by GitHub Actions** (`.github/workflows/daily_scrape.yml`,
   cron `0 3 * * *` = 03:00 UTC ≈ 11 PM ET, so data is ready well before the user's morning;
   scheduled early to absorb GitHub Actions' ~1–2h cron delay, plus a `0 9 * * *` retry cron
   that no-ops if today's data already landed — see §CI), which writes the resulting CSVs into `data/` and **commits
   them back to `main`** (`git add -f data/` then push). The repo's git history is therefore a
   stream of `"Automated daily data update"` commits. No Reddit API key is used.
2. **Backend** — a tiny **FastAPI** app (`server.py`) that reads the committed CSVs from `data/`
   and serves them as one JSON blob at **`GET /api/data`**, plus the SPA at `GET /`. Deployed on
   **Vercel** via `vercel.json` (legacy `@vercel/python` builder).
3. **Frontend** — a single static page (`templates/index.html`) using Tailwind (CDN) + Firebase.
   It fetches `/api/data`, renders tabs, and stores read/favorite state in `localStorage` **and**
   Firebase Firestore for cross-device sync. Also a PWA (`manifest.json` + `sw.js`).

Repo: `github.com/jalalchowdhury1/reddit-scraper` (public). Language: Python + vanilla JS.
There is **no secret backend state** — Vercel's filesystem is read-only at runtime; all
mutable user state lives client-side in Firebase.

### Data flow

```
GitHub Actions (daily 03:00 UTC ≈ 11 PM ET)
   └─ python core/scrape_top.py        → data/r_<sub>/posts.csv  &  data/r_<sub>_yearly/posts.csv
   └─ python core/scrape_ritholtz.py   → data/ritholtz/articles.csv      (overwrite daily)
   └─ python core/scrape_googlenews.py → data/googlenews/articles.csv     (append + dedup)
   └─ python core/scrape_trung.py      → data/trung/articles.csv          (overwrite daily)
   └─ git add -f data/ && commit && push   (CSVs committed to main)
                                  │
                                  ▼  (Vercel auto-deploys on push to main)
Browser ─▶ Vercel (server.py FastAPI) ─▶ GET /api/data
              │  reads all data/**/*.csv, merges, dedups, sorts, caps at 50/section
              ▼
         { monthly:[], yearly:[], news:[], ritholtz:[] }   ← JSON
              │
Frontend (index.html): renders 5 tabs (Monthly / Yearly / Google News / AM Reads / ★ Favorites)
   read & favorite state ↔ localStorage  ↔  Firebase Firestore (cross-device sync)
```

Note: the Ritholtz **and** Trung (SatPost) articles are both merged into the **`ritholtz`**
key by `server.py` and shown together under the **"AM Reads"** tab (labelled `AM READS` vs
`SATPOST` in the per-item meta line, sorted by date descending).

---

## 2. The active scrapers (`core/`) — what actually runs in CI

These four, in this order, are the **only** scripts the daily workflow runs. Everything in
`diagnostics/` and `scraper/` is **NOT** wired into CI (see §6).

| Script | Source | Output | Write mode |
|---|---|---|---|
| `core/scrape_top.py` | Reddit (no API key) | `data/r_<sub>/posts.csv` (monthly) + `data/r_<sub>_yearly/posts.csv` | **overwrite** per sub/filter |
| `core/scrape_ritholtz.py` | ritholtz.com "AM Reads" / "Weekend Reads" | `data/ritholtz/articles.csv` | **overwrite** daily |
| `core/scrape_googlenews.py` | Google News RSS (Bangladesh) | `data/googlenews/articles.csv` | **append + dedup** on `(article_id, category)` |
| `core/scrape_trung.py` | readtrung.com Substack RSS (SatPost) | `data/trung/articles.csv` | **overwrite** daily |

### `core/scrape_top.py` — triple-redundant Reddit scraper (the heart)
For each subreddit, for `time_filter` in `["month", "year"]`, it tries three tiers in order
and returns the first that yields posts:
1. **PRIMARY (Stealth JSON):** `https://old.reddit.com/r/{sub}/top.json?t={filter}&limit=50`
   with a full macOS/Chrome `HEADERS` block. On HTTP **429** it sleeps **30s** and retries
   once. Skips `stickied` and `is_video` posts. This tier returns **real scores**.
2. **SECONDARY (HTML):** scrapes `old.reddit.com/r/{sub}/top/?sort=top&t={filter}` with
   BeautifulSoup. Reads real score from `div.score.unvoted[title]` if present.
3. **TERTIARY (RSS):** `https://www.reddit.com/r/{sub}/top/.rss?t={filter}&limit=50`.
   No real scores available.

When a tier yields **no real score** (HTML score `0`, or RSS always), it **synthesizes** a
score via the **Tiered Priority Exponential Decay** model so high-signal subs float to the top:
- Pick a base from `SUBREDDIT_TIERS[sub]` (fallback `"default"`):
  - **Tier 1** `(75k–100k)`: `bestof`, `explainlikeimfive`, `todayilearned`, `AskHistorians`
  - **Tier 2** `(40k–70k)`: `TrueReddit`, `dataisbeautiful`, `PersonalFinance`
  - **Tier 3 / default** `(15k–35k)`: everything else
- Per post at index `i`: `score = int(base_max_score * (0.88 ** i)) + random.randint(100, 999)`
- **Do NOT change this scoring math without the owner's permission.**

Between subreddits it sleeps `random.uniform(6.5, 12.5)` seconds (human jitter — see §5).

**Subreddit list lives in `core/scrape_top.py` (`SUBREDDITS`, 13 entries), NOT in `config.py`.**
The CI scraper list is: `dataisbeautiful, todayilearned, bestof, getmotivated,
UnethicalLifeProTips, LifeProTips, TrueReddit, UpliftingNews, lifehacks, Productivity,
PersonalFinance, explainlikeimfive, AskHistorians`. To add/remove a tracked sub, edit
`core/scrape_top.py:SUBREDDITS` (and `SUBREDDIT_TIERS` if you want a non-default base score).

### `core/scrape_googlenews.py` — Bangladesh news, strictly filtered
- Sweeps 3 broad Google News RSS queries (`Bangladesh Economy`, `Bangladesh India`,
  `Bangladesh business`).
- Drops any item whose source matches `BLOCKED_SOURCES` (a long blocklist of Indian outlets).
- Keeps an item **only if** its `title + description` matches one of `STRICT_FILTERS`'s phrase
  lists via **`\b`-word-boundary regex** (so `fdi` won't match inside `offdir`). First matching
  category wins; `category` is stored on the row. Categories: `India–Bangladesh Relations`,
  `Bangladesh Economy`, `Good News`. (These keyword lists are duplicated in `config.py`'s
  `NEWS_CATEGORIES`, but **`scrape_googlenews.py` uses its own copy** — keep them in sync if it
  matters.)
- **Dedup keep-direction differs from the server (cosmetic).** `save_articles` (line ~136) dedups
  the appended CSV on `(article_id, category)` with `keep="last"`, while `server.py` (line ~100)
  dedups the same key with `keep="first"`. Behavior is effectively identical since the scraper
  appends fresh rows; just don't assume they match if you ever change one.

### `core/scrape_ritholtz.py` — AM Reads (hard rules, do not regress)
Two-step: fetch `https://ritholtz.com/category/links/` → find today's `am-reads`/`weekend-reads`
post URL (must start with `http` and contain `ritholtz.com/202`) → fetch that post and extract
articles. Extraction rules that exist for good reasons:
- Grab **only the first `<a>` in each `<li>`** (ignores "see also" links).
- **Skip any link whose href contains `ritholtz.com`** (internal/nav links).
- Strip leading bullets/whitespace (`•·-–—:.` and `•`) from titles.
- Strict title dedup (lowercased) within a run; **hard cap of 12 items**.
- `article_id = md5(f"{url}_{title}")[:12]`. Falls back to a link-based pass if the `<li>` pass
  finds nothing.

---

## 3. Backend (`server.py`) — the API

- `GET /` → renders `templates/index.html` (the SPA).
- `GET /api/data` → reads every CSV under `data/`, merges, and returns:
  `{ "monthly": [...], "yearly": [...], "news": [...], "ritholtz": [...] }`.
  - Reddit: monthly from `data/r_*/posts.csv` (skips `_yearly`), yearly from
    `data/r_*_yearly/posts.csv`. Dedup on `(id, time_filter)`, sort by `score` desc.
  - News from `data/googlenews/articles.csv` (dedup `(article_id, category)`, sort `pub_date` desc).
  - `ritholtz` = `data/ritholtz/articles.csv` (`rth_` ids) **+** `data/trung/articles.csv`
    (`trg_` ids), then re-sorted by the `YYYY-MM-DD` found in each item's `meta` (desc).
  - **Every section is capped at the first 50 items.**
  - Each item is `{id, title, desc, url, meta}`; `meta` is a pre-formatted string (e.g.
    `r/bestof • MONTHLY • 84.5k pts • ⏱️ 3 min`). The frontend parses some of this string.
- Helpers: `format_score` (`82450 → 82.4k`), `calculate_reading_time` (~200 wpm),
  `clean_text` (`html.unescape`, NaN-safe). Every CSV read is wrapped in `try/except` so a bad
  file silently yields no rows rather than 500-ing.

---

## 4. Run / deploy / test

### Local
```bash
# FastAPI web app (the production server)
uvicorn server:app --reload                 # then open http://localhost:8000

# Manual scrape (writes into ./data/)
python core/scrape_top.py
python core/scrape_ritholtz.py
python core/scrape_googlenews.py
python core/scrape_trung.py

# Legacy Streamlit dashboard (NOT the deployed UI — see §6)
streamlit run dashboard.py

# Convenience: scrape everything + open browser + start server
./daily_morning.sh        # ⚠️ hardcodes ~/PycharmProjects/Reddit Scraping & venv (owner machine)
```

### Deploy (Vercel)
- **Auto-deploys on every push to `main`** (including the bot's daily data commits).
- `vercel.json` uses the **legacy `builds` API** with `@vercel/python` on `server.py`, and
  `config.includeFiles` to bundle `templates/**, data/**, server_assets/**, manifest.json, sw.js`.
- Only `requirements.txt` (the FastAPI-minimal set) is installed by Vercel.

### CI
- `.github/workflows/daily_scrape.yml`: Python **3.10**, `pip install -r requirements-scraper.txt`,
  runs the four `core/` scrapers, then `git add -f data/ && git commit -m "Automated daily data
  update" || exit 0 && git push`. `permissions: contents: write`. Manually triggerable via
  `workflow_dispatch`. (Actions were bumped to `actions/checkout@v6` / `actions/setup-python@v6`.)
- **Two crons + dedupe guard (don't "simplify" away):** `0 3 * * *` is the real run; `0 9 * * *`
  is a retry window added after 2026-07-09, when GitHub never assigned a runner to the 03:00 job
  ("job was not acquired by Runner") and the day's data was silently lost. A guard step skips
  *scheduled* runs when `data/` was already committed today (UTC) — so the 09:00 run is a no-op
  on normal days — while `workflow_dispatch` always runs. Checkout uses `fetch-depth: 50` because
  the guard needs history to find the last `data/` commit; a `concurrency: daily-scrape` group
  (no cancel) serializes a badly delayed 03:00 cron against the 09:00 retry.
- There is **no test/lint workflow and no test suite.**

### Dependency split (3 files — keep them split, see §5)
- `requirements.txt` — **production/Vercel minimal**: `fastapi, uvicorn, Jinja2, pydantic,
  pandas==2.1.4, numpy==1.26.4`.
- `requirements-scraper.txt` — `-r requirements.txt` + `requests, beautifulsoup4, lxml`
  (what CI installs to scrape).
- `requirements-dev.txt` — `-r requirements-scraper.txt` + `streamlit` (local dashboard only).

### Secrets / env vars (named only — never commit values)
- `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` — read by `config.py`. **Not
  used by the CI scrapers** (`core/scrape_top.py` is keyless); only the legacy PRAW path in
  `diagnostics/reddit_scraper.py` would use them.
- `SCRAPESERV_URL` (default `http://localhost:5006`) — for the optional screenshot service.
- `DISCORD_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DATABASE_URL` — declared in
  the legacy `scraper_config.py`; **unused by the live app.**
- `.env.example` documents the Reddit/ScrapeServ vars; `.env` is gitignored.
- **Firebase web config is committed in `templates/index.html`** (`apiKey`, `authDomain`,
  `projectId` for project `dailyreadersync`). A Firebase **web API key is a public client
  identifier, not a secret** — it is fine for it to be in client code; security is enforced by
  Firestore rules, not by hiding this key. Do not treat it as a leak, but do not add server-side
  secrets to this file.

---

## 5. Gotchas / hard rules (highest-value section)

1. **Vercel 250 MB lambda limit — keep `requirements.txt` minimal.** Unzipped Python lambdas
   on Vercel hard-crash above 250 MB. **Do NOT** add heavy/scraper libs (`streamlit`, `lxml`,
   `beautifulsoup4`, etc.) to `requirements.txt`. Scraper deps go in `requirements-scraper.txt`;
   the Streamlit dashboard dep goes in `requirements-dev.txt`. Vercel only installs
   `requirements.txt`.
2. **`vercel.json` must use the legacy `builds` API.** Do **NOT** add a top-level `functions`
   property — it conflicts with `builds` and fails Vercel schema validation. To bundle extra
   files (templates/data/assets), add them to `config.includeFiles` **nested inside the `builds`
   entry**, never at top level.
3. **Absolute paths only in `server.py`.** Vercel functions run in fluctuating `/var/task`
   working dirs. Always derive paths from `BASE_DIR = Path(__file__).resolve().parent` — never
   relative strings.
4. **Starlette `TemplateResponse` must use keyword args.** Vercel pulls the latest
   `fastapi`/`starlette`; newer Starlette crashes on positional args. Keep
   `templates.TemplateResponse(request=request, name="index.html")`.
5. **Reddit rate limits (429/403) — never use fixed sleeps.** GitHub Actions runs from Azure
   datacenter IPs that Reddit throttles hard. Keep the human jitter
   `time.sleep(random.uniform(6.5, 12.5))` between subreddits in `scrape_top.py`; a fixed
   `time.sleep(3)` will get the scraper banned. If 429s persist, *increase* the jitter range.
6. **The scoring math is load-bearing — don't touch it.** The tiered exponential-decay synthetic
   scores (`base_max_score * 0.88**i + rand(100,999)`) are what make the feeds sort sensibly when
   real upvotes aren't available. Change only with explicit permission.
7. **Data is committed to git, not stored in a DB at runtime.** The `.gitignore` ignores `data/`
   generally but **un-ignores `data/**/*.csv` and `data/**/*.json`** (`!data/**/*.csv`), and CI
   force-adds with `git add -f data/`. If you reorganize `data/`, keep those globs working or the
   daily commit will silently push nothing.
8. **Write modes differ per scraper** (see §2 table): `scrape_top` and `scrape_ritholtz` and
   `scrape_trung` **overwrite**; `scrape_googlenews` **appends + dedups**. Don't "fix" googlenews
   to overwrite — it accumulates a rolling news history on purpose.
9. **The `ritholtz` API key carries two sources.** Trung/SatPost items are folded into the same
   `ritholtz` array in `server.py`; the "AM Reads" tab shows both. Don't assume `ritholtz` ⇒ only
   ritholtz.com.
10. **Frontend "Show Read" is a master switch.** `if (!showRead && isRead && currentTab !==
    'favorites') return;` hides read items from *all* main feeds (even favorited ones). Favorited
    items stay visible only on the dedicated **Favorites** tab.
11. **Frontend mute filter is Monthly-only.** `mutedKeywords = ["r/askhistorians"]` is applied
    **only** on the Monthly tab (so AskHistorians' synthetic Tier-1 scores don't dominate the
    monthly feed). It does not affect Yearly/News/AM Reads.
12. **The Reddit `permalink` double-prefix guard.** `server.py` defends against
    `https://www.reddit.comhttps://...` by replacing it. Different tiers in `scrape_top.py` build
    permalinks differently (some already absolute), so keep that guard.

---

## 6. Known issues / drift / dead code (verified against current code)

- **`.llm-guide-index` was stale** — it referenced `READ_ME_FIRST_FOR_LLM.md`, `CLAUDE.md`,
  `IMPLEMENTATION_NOTES.md`, `LLM_OPTIMIZATION_SUMMARY.md`, none of which exist in the repo.
  Consolidated into this file and deleted.
- **README claims "14 communities" and lists `r/sobooksoc`; reality is 13 and no sobooksoc.**
  The authoritative CI list is `core/scrape_top.py:SUBREDDITS` (13 subs, includes `AskHistorians`,
  excludes `Fitness`). `config.py:SUBREDDITS` is a **different, 13-entry list** (includes
  `sobooksoc` and `Fitness`, excludes `bestof`/`AskHistorians`) and is **only** consumed by the
  legacy `dashboard.py` — it does **not** drive CI scraping. `data/r_sobooksoc/` does not exist;
  `data/r_Fitness*` exists only as a **leftover** from earlier runs (Fitness is NOT in
  `core/scrape_top.py:SUBREDDITS`; its CSV last changed in old commit `e5ccb23`). **Note:**
  `data/r_UpliftingNews*` is **NOT** a leftover — `UpliftingNews` IS one of the 13 active CI subs
  and its CSV was updated in HEAD (`bc6095c`); do not delete it.
- **`config.py:DAILYSTAR_FEEDS` + `scrape_dailystar.py` are not wired in.** The daily workflow
  does not run `scrape_dailystar.py`, there is no `data/dailystar/` dir, and `server.py` does not
  read Daily Star. README mentions Daily Star indirectly via `config.py`; treat the Daily Star
  path as **legacy/inactive** (Google News replaced it). `scrape_dailystar.py` still imports and
  uses `config.NEWS_CATEGORIES`.
- **`README.md` "Commands" lists `streamlit run dashboard.py` as the primary UI and shows a
  `Reddit Scraping/` tree.** The **deployed** UI is the FastAPI SPA (`server.py` +
  `templates/index.html`); Streamlit (`dashboard.py`) is a separate **legacy local-only** viewer
  that reads the same CSVs and a `data/read_posts.json`. Both still work locally.
- **`scraper/async_scraper.py` has a broken import.** It does
  `from config import USER_AGENT, MIRRORS, ASYNC_MAX_CONCURRENT, ASYNC_BATCH_SIZE`, but those
  names live in **`scraper_config.py`**, not `config.py`. As written it will `ImportError` unless
  `scraper_config.py` is imported as `config`. This module is **not used by the live app** — it's
  an experimental high-throughput scraper (mirrors, media+comments, ffmpeg). Don't rely on it.
- **`database.py` (SQLAlchemy) is legacy and unused by the live system.** Its own docstring says
  so. The app reads CSVs, not SQLite. It still self-initializes (`init_db()` on import) and would
  create `data/reddit_daily.db` if imported.
- **`diagnostics/` is a junk-drawer of one-off tools, not part of CI:** `reddit_scraper.py`
  (PRAW-based, needs the Reddit API keys), `scraper_main.py` (full async-ish scraper with
  `--mode full|history|monitor`), `scheduler.py` (a `schedule`-library local cron meant to run
  scrapers at 8:00 AM — superseded by the GitHub Action), `final_stress_test.py` /
  `verify_hierarchy.py` (both `import scrape_top` as a top-level module, which only works if run
  from inside `core/`), `test_html.py` / `test_rss.py` (manual fallback-tier probes). `run.sh`
  invokes `diagnostics/scraper_main.py` and is owner-machine-specific.
- **`.scrapeserv_clone/` is an empty directory** (placeholder for the optional ScrapeServ Docker
  clone). `docker-compose.yml` defines an optional `scraper` (ScrapeServ screenshot service) and
  a `dashboard` (Streamlit) — neither is needed for production.
- **`daily_morning.sh` / `run.sh` hardcode the owner's local paths** (`~/PycharmProjects/Reddit
  Scraping`, a `venv`, a homebrew/CLT Python path). They are personal convenience scripts; don't
  treat their paths as canonical.

---

## 7. File / module map

**Live production path (touch these for real changes):**
- `server.py` — FastAPI app: `GET /` (SPA) + `GET /api/data` (merges all CSVs → JSON). Helpers
  `format_score`, `calculate_reading_time`, `clean_text`.
- `templates/index.html` — the whole SPA: 5 tabs, Tailwind (CDN), Firebase init + Firestore sync,
  read/favorite logic, mute filter, PWA registration.
- `server_assets/style.css` — extra styles served alongside the SPA.
- `manifest.json` + `sw.js` — PWA manifest + offline-cache service worker (cache `daily-reader-v1`).
- `core/scrape_top.py` — triple-redundant Reddit scraper + synthetic scoring (`SUBREDDITS`,
  `SUBREDDIT_TIERS`, `HEADERS`). **Authoritative subreddit list.**
- `core/scrape_ritholtz.py` — AM Reads / Weekend Reads scraper (12-item cap, dedup rules).
- `core/scrape_googlenews.py` — Bangladesh Google-News RSS scraper (blocklist + strict
  `\b`-regex keyword filter; `QUERIES`, `BLOCKED_SOURCES`, `STRICT_FILTERS`).
- `core/scrape_trung.py` — readtrung.com (SatPost) Substack RSS scraper.
- `vercel.json` — Vercel legacy-`builds` deploy config (+ `includeFiles`).
- `.github/workflows/daily_scrape.yml` — the only CI: daily scrape + commit CSVs to `main`.
- `requirements.txt` / `requirements-scraper.txt` / `requirements-dev.txt` — the 3-way dep split.
- `data/**/posts.csv` & `data/**/articles.csv` — committed scrape output (the "database").
- `.env.example` — documents `REDDIT_*` + `SCRAPESERV_URL`.

**Config:**
- `config.py` — paths, `SUBREDDITS` (used only by `dashboard.py`), `DAILYSTAR_FEEDS` +
  `NEWS_CATEGORIES` (used only by the legacy `scrape_dailystar.py`), scraper timing constants.
- `scraper_config.py` — legacy config for the async/diagnostics scrapers (`USER_AGENT`, `MIRRORS`,
  async + notification + DB settings). Separate from `config.py`.

**Legacy / inactive (do not assume these run in production):**
- `dashboard.py` — Streamlit local viewer (reads CSVs + `data/read_posts.json`).
- `database.py` — unused SQLAlchemy models (`RedditPost`, `ScrapeHistory`).
- `scrape_dailystar.py` — Daily Star RSS scraper (superseded by Google News; not in CI).
- `scraper/async_scraper.py` (+ `scraper/__init__.py`) — experimental async scraper (broken
  import, see §6).
- `scraper_client.py` — ScrapeServ HTTP client for optional screenshots.
- `diagnostics/*` — one-off scrapers, scheduler, and manual test probes (see §6).
- `daily_morning.sh`, `run.sh` — owner-machine convenience scripts (hardcoded local paths).
- `docker-compose.yml`, `.scrapeserv_clone/` — optional ScrapeServ + Streamlit Docker setup.
</content>
