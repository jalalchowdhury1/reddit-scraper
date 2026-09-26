# AGENTS.md — Daily Reader (Reddit & News Aggregator)

> **The single source of truth for anyone (human or AI) touching this repo.** Read it fully
> before changing code or deploying. `README.md` is the short GitHub landing page; when the two
> disagree, this file wins, and whoever notices fixes the other one. Last full accuracy pass
> against the code: 26 Sep 2026.

Live site: **https://reddit-scraper-lyart.vercel.app** · Health: **`/api/status`** ·
Repo: `github.com/jalalchowdhury1/reddit-scraper` (public) · Python + vanilla JS.

---

## 1. What this is

A **zero-cost personal reading page**. It pulls the top posts from 13 subreddits plus Bangladesh
news and two newsletters into one page, and syncs "read" / "favorite" across devices with
Firebase.

**In 30 seconds:** robots save lists as CSV files into `data/` and push them to GitHub →
Vercel redeploys on every push → `server.py` turns the CSVs into one JSON answer → the page
(`templates/index.html`) shows it. Nothing is stored on the server; your read/favorite state
lives in the browser and in Firebase.

**The robots (who writes what):**

| Robot | When | Writes |
|---|---|---|
| **Mac mini** launchd `com.jalal.reddit-browser` → `mac/reddit-browser.sh` → `core/scrape_reddit_browser.py` | 07:35 + 19:35 local | `data/r_<sub>[_yearly]/posts.csv` with **real upvotes**, `data/reddit_browser.json` |
| GitHub `.github/workflows/daily_scrape.yml` | 03:00 UTC, retry 09:00 UTC | News, AM Reads, SatPost, and Reddit **only for lists the Mac hasn't saved in 36 h** |
| GitHub `.github/workflows/am_reads.yml` | 11:45 / 13:30 / 15:30 UTC | AM Reads + SatPost again (Ritholtz posts ~6:30 AM ET) |

### Data flow

```
Mac mini, 07:35 + 19:35 (real headless browser; Reddit blocks GitHub's IPs)
   └─ core/scrape_reddit_browser.py → data/r_<sub>[_yearly]/posts.csv + data/reddit_browser.json
   └─ git add -f … && commit && push           (its own clone, 3-try rebase loop)
GitHub Actions, 03:00 UTC (+ 09:00 retry)
   └─ core/scrape_top.py        → Reddit backup: only lists the Mac missed for 36 h (RSS, no upvotes)
   └─ core/scrape_ritholtz.py   → data/ritholtz/articles.csv   (only today's list, no repeats)
   └─ core/scrape_googlenews.py → data/googlenews/articles.csv (append + dedup)
   └─ core/scrape_trung.py      → data/trung/articles.csv      (overwrite)
   └─ git add -f data/ && commit && push
                                  │
                                  ▼  Vercel auto-deploys every push to main
Browser ─▶ server.py (FastAPI on Vercel) ─▶ GET /api/data
              ▼
   { monthly, yearly, news, ritholtz, totals, updated }
              ▼
index.html: 5 tabs (Monthly / Yearly / News / AM Reads / ★ Favorites)
   read + favorite state ↔ localStorage ↔ Firebase Firestore (cross-device)
```

Ritholtz **and** SatPost (Trung) items both go into the **`ritholtz`** key and show together on
the **AM Reads** tab (`AM READS` / `WEEKEND READS` vs `SATPOST` in each item's meta).

---

## 2. The scrapers (`core/`)

| Script | Runs on | Source | Output | Write mode |
|---|---|---|---|---|
| `core/scrape_reddit_browser.py` | **Mac mini** (launchd) | reddit.com top pages in headless Chromium | `data/r_<sub>/posts.csv`, `data/r_<sub>_yearly/posts.csv`, `data/reddit_browser.json` | **overwrite** per list, only when the page loaded |
| `core/scrape_top.py` | GitHub (daily) | Reddit JSON → HTML → RSS | same Reddit files | **overwrite**, skips lists the Mac saved in 36 h |
| `core/scrape_ritholtz.py` | GitHub (daily + am_reads) | ritholtz.com AM Reads / Weekend Reads | `data/ritholtz/articles.csv` (+ `seen.json`) | **overwrite**, only when the post changed |
| `core/scrape_googlenews.py` | GitHub (daily) | Google News RSS (Bangladesh) | `data/googlenews/articles.csv` | **append + dedup** on `(article_id, category)` |
| `core/scrape_trung.py` | GitHub (daily + am_reads) | readtrung.com Substack RSS (SatPost) | `data/trung/articles.csv` | **overwrite** |

`core/reddit_common.py` (stdlib only) holds what the Reddit scrapers share: **`SUBREDDITS`
(the authoritative list, 13 entries)**, `SUBREDDIT_TIERS`, `tier_score()`, and the Mac/GitHub
freshness handshake (`data/reddit_browser.json`, `FRESH_HOURS = 36`).
Nothing in `diagnostics/` or `scraper/` runs anywhere (see §6).

### 2a. `core/scrape_reddit_browser.py` — the real Reddit source (Mac mini, since 26 Sep 2026)

**Why a browser:** Reddit blocks every plain request now. GitHub's IPs get 403/429, and even the
owner's home IP gets a JavaScript challenge page on the JSON and HTML endpoints. A real headless
Chromium (Playwright) passes that challenge by itself after one warm-up load of reddit.com. The
new Reddit page carries each post as a `<shreddit-post>` with attributes `id`, `score`,
`comment-count`, `post-title`, `post-type`, `permalink`; self-post text sits in
`[slot="text-body"]` (ads are a separate `shreddit-ad-post`). So: real upvotes, real text, no
login, no key, no AI. **The official OAuth API was tried and never worked for the owner. Don't
suggest it again.**

What one run does (~5–6 min):
- Warm-up load of reddit.com, then for each of the 13 subs × `month`/`year`: open
  `/r/<sub>/top/?t=<month|year>`, scroll like a person until 50 posts (max 10 scrolls, stops after
  3 scrolls with nothing new), read the attributes. Videos are skipped (it's a reading list).
- **Saves a list only if the page really loaded:** at least `MIN_POSTS = 5` posts on the page
  (counted *before* videos are dropped) and at least one readable row. Otherwise the old file
  stays. 5, not more, because real lists can be short: r/lifehacks had 7 posts for Sep 2026.
- A bad page gets one retry after a fresh warm-up. **4 failed lists in a row = stop** (Reddit is
  blocking this browser; hammering makes it worse). Hard stop at 15 min (`RUN_DEADLINE_S`).
- Human pace: 3–7 s between pages.
- `data/reddit_browser.json` gets two stamps per list, written **right away** (a run killed
  midway keeps what it did): `lists` = last **saved** (GitHub's backup keys off this), and
  `checked` = last time Reddit served the list's real page, saved or not (a challenge page has
  no posts; a quiet sub can be too short to save). fleet-health grades `checked`.
- If Playwright was upgraded and its browser is missing ("Executable doesn't exist"), it runs
  `python3 -m playwright install chromium` once and carries on.
- Prints `BROWSER SAVED: N of M lists` (+ which kept their old file). Exit 1 if it saved none.
- Stdlib + Playwright only: the Mac's `/opt/homebrew/bin/python3` has Playwright but no pandas.
- Manual run: `python3 core/scrape_reddit_browser.py [--only sub1,sub2] [--visible] [--profile DIR]`.

**CSV columns:** `id,title,selftext,permalink,score,upvotes,comments,score_real`.
- **`upvotes` = Reddit's real number (what the site shows).**
- **`score` = the tier ordering number** (`reddit_common.tier_score`, same math as the RSS
  backup). Why not order by real upvotes: they differ ~20x between subs, and doing so made
  Monthly 46 of 50 r/todayilearned and Yearly 50 of 50.
- `score_real=False` on Mac rows, because their `score` IS made up. A reader that doesn't know
  about `upvotes` then shows the rank, never the tier number.
- `comments` is stored, not shown yet. Row order = Reddit's own top order (the site's `rank`).

### 2b. `mac/reddit-browser.sh` — the launchd wrapper

launchd `com.jalal.reddit-browser` (`mac/com.jalal.reddit-browser.plist`,
`StartCalendarInterval` 07:35 + 19:35, never `StartInterval`) runs this script **from the job's
own clone** at `~/.local/share/reddit-browser/reddit-scraper`, never the PyCharm working copy.
The work lives inside `main()`, so bash has read all of it before `git reset --hard` can replace
the file mid-run. Each run:

1. Writes `== YYYY-MM-DD HH:MM:SS start` to the log (fleet-health parses this line).
2. **Takes a lock** (`~/.local/share/reddit-browser/run.lock`, a directory). Another run holding
   it → prints `ANOTHER RUN IS ACTIVE: skipping this one` and exits 0. A lock older than 40 min
   belongs to a killed run and is taken over (`old lock from a killed run`).
3. Gets its clone to exactly `origin/main` (self-update): clones if missing, clears what a run
   killed mid-git leaves behind (`.git/index.lock`, a half-done rebase), then `git fetch` +
   `git reset --hard origin/main`. If that still fails, the clone is broken: it deletes it and
   clones once more (`clone looks broken: cloning it again`; the clone is ~6 MB). Network git
   calls have timeouts (fetch/clone/pull 300 s, push 120 s), so a hung GitHub can't hold the lock.
4. Runs the scraper under `timeout 1200` with `python3 -u` (unbuffered: a killed run still leaves
   its lines in the log), profile `~/.local/share/reddit-browser/profile` (a throwaway profile
   just for this job; it keeps Reddit's cookie).
5. `git add -f data/r_*/posts.csv` (+ the json if present). Nothing changed →
   `NO REDDIT CHANGES (scraper exit N)` and exits with the scraper's code.
6. Commits, then pushes with a 3-try loop (`git pull --rebase -X theirs` between tries, because
   GitHub's jobs push to the same branch). Success line:
   `REDDIT PUSHED: N files in <sha> (scraper exit N)`, then `== … done`.

Failure lines: `LOCK FAILED`, `CLONE FAILED`, `GIT SYNC FAILED`, `COMMIT FAILED`,
`PUSH FAILED after 3 tries`.
Log: `~/Library/Logs/reddit-browser.log`. The wrapper trims it in place (past ~500 KB, keeps the
last 3000 lines). `REDDIT_BROWSER_*` env vars exist only so the tests can point it at a local
git repo.

**Install / reinstall** (after the code is on `origin/main`; also in the plist's top comment):
```bash
git clone https://github.com/jalalchowdhury1/reddit-scraper.git ~/.local/share/reddit-browser/reddit-scraper
cp mac/com.jalal.reddit-browser.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jalal.reddit-browser.plist
launchctl kickstart gui/$(id -u)/com.jalal.reddit-browser     # run now, under launchd itself
tail -f ~/Library/Logs/reddit-browser.log
```

**Known, accepted race:** if GitHub's run overlaps a Mac push, the rebase (`-X theirs`) can keep
GitHub's RSS copy of a list under the Mac's fresh stamp. It lasts until the next Mac run (≤12 h),
and RSS rows are honest (rank, no fake upvotes).

### 2c. `core/scrape_top.py` — GitHub's Reddit backup

`main()` first reads `data/reddit_browser.json` and **skips every list the Mac saved in the last
36 h** (`reddit_common.fresh_keys`; a broken json means "nothing is fresh", never a crash). For
the rest, per sub × `month`/`year`, it tries three tiers and keeps the first that yields posts:
1. **JSON:** `old.reddit.com/r/{sub}/top.json?t={filter}&limit=50` with a macOS/Chrome `HEADERS`
   block; on 429 sleeps 30 s and retries once; skips stickied and video posts. Real scores
   (`score_real=True`), but GitHub's IPs get 403 "Blocked" here now.
2. **HTML:** `old.reddit.com/r/{sub}/top/?sort=top&t={filter}` via BeautifulSoup; real score only
   if the page shows it.
3. **RSS:** `www.reddit.com/r/{sub}/top/.rss?t={filter}&limit=50`. No scores. Carries self-post
   text (from `<div class="md">`). A 429 gets one retry (Retry-After, max 60 s) within a 480 s
   back-off budget per run, so the 30-min job timeout is safe. `parse_rss()` is pure (tested).

When there's no real score it **synthesizes one for ORDERING ONLY** ("Tiered Priority
Exponential Decay"), so high-signal subs float up:
- Base = `random.randint(*SUBREDDIT_TIERS[sub])` (fallback `"default"`):
  - **Tier 1** `(75k–100k)`: `bestof`, `explainlikeimfive`, `todayilearned`, `AskHistorians`
  - **Tier 2** `(40k–70k)`: `TrueReddit`, `dataisbeautiful`, `PersonalFinance`
  - **default** `(15k–35k)`: everything else
- Post at index `i`: `score = int(base * (0.88 ** i)) + random.randint(100, 999)`.
- **Do NOT change this math without the owner's permission.**
- **Never display it.** Every row carries `score_real`; the site shows the post's rank in its
  sub's top list ("#3 this month") instead. Why: on 26 Sep 2026 all 26 JSON fetches got 403, so
  every "82.4k upvotes" on the site was invented.
- Between subreddits: `time.sleep(random.uniform(6.5, 12.5))` (human jitter, see §5).

**The 13 tracked subs** (`core/reddit_common.py:SUBREDDITS`, NOT `config.py`):
`dataisbeautiful, todayilearned, bestof, getmotivated, UnethicalLifeProTips, LifeProTips,
TrueReddit, UpliftingNews, lifehacks, Productivity, PersonalFinance, explainlikeimfive,
AskHistorians`. To add/remove one, edit `SUBREDDITS` (and `SUBREDDIT_TIERS` for a non-default
base). **Removing a sub? Also `git rm -r data/r_<sub> data/r_<sub>_yearly`.** `server.py` now
ignores untracked subs anyway, but the dead files would sit in every deploy.

### 2d. `core/scrape_googlenews.py` — Bangladesh news, strictly filtered
- Sweeps 3 Google News RSS queries (`Bangladesh Economy`, `Bangladesh India`,
  `Bangladesh business`).
- Drops any item whose source is in `BLOCKED_SOURCES` (a long blocklist of Indian outlets).
- `fetch_with_retry()` tries each query 3 times (waits 5 s, 20 s) on 5xx/429/network errors;
  other 4xx fail at once. Added 26 Sep 2026 after all 3 queries 503'd and News sat a day old.
- Keeps an item **only if** its `title + description` matches one of `STRICT_FILTERS`'s phrase
  lists via **`\b` word-boundary regex** (so `fdi` won't match inside `offdir`). First matching
  category wins and is stored in `category`: `India–Bangladesh Relations`,
  `Bangladesh Economy`, `Good News`. (`config.py:NEWS_CATEGORIES` is a separate copy used only by
  the legacy `scrape_dailystar.py`.)
- `save_articles` dedups the appended CSV on `(article_id, category)` with `keep="last"`;
  `server.py` dedups the same key with `keep="first"`. Effectively identical; don't assume they
  match if you change one.

### 2e. `core/scrape_ritholtz.py` — AM Reads (hard rules, do not regress)
Two steps: fetch `https://ritholtz.com/category/links/` → find today's `am-reads` /
`weekend-reads` post URL (must start with `http` and contain `ritholtz.com/202`) → fetch that
post and extract articles.
- Only the **first `<a>` in each `<li>`** (ignores "see also" links); skip any href containing
  `ritholtz.com`; strip leading bullets/whitespace and zero-width characters from titles;
  **hard cap of 12 items**; falls back to a link-based pass if the `<li>` pass finds nothing.
- `article_id = md5(f"{url}_{title}")[:12]`.
- **Only today's list, only once (26 Sep 2026):**
  - `pub_date` = the post's real `article:published_time` in US/Eastern (it used to be the scrape
    time, so a Friday list scraped after midnight UTC read as Saturday).
  - In-post dedup by normalized URL **or** normalized title (`dedupe_articles`).
  - Promo lines dropped (`JUNK_TITLE_RE` / `JUNK_URL_RE`: "Video of the day", Masters in
    Business plugs, "Previous Post", "To learn how these reads are assembled"…).
  - Cross-day repeats: `data/ritholtz/seen.json` remembers every article key shown (45 days,
    seeded from git history). An article already shown by an EARLIER post is skipped; re-running
    the same post keeps it.
  - Unchanged post → the CSV is not rewritten (no empty commits from the morning job).
  - **Timing:** Ritholtz posts ~6:30 AM ET but the nightly job runs 11 PM ET, so it always caught
    the *previous* morning's list. `am_reads.yml` re-scrapes at 11:45 / 13:30 / 15:30 UTC and
    commits only on change.
  - The page shows only items dated today (US/Eastern); Sunday also shows Saturday's Weekend
    Reads; otherwise an empty state with an opt-in "Show <day>'s list" button.
- SatPost (`scrape_trung.py`) keeps ~20 back issues in its CSV; `server.py` serves only the last
  7 days of them.

---

## 3. Backend (`server.py`)

**Endpoints**
- `GET /` → `templates/index.html` (Jinja, keyword-arg `TemplateResponse`).
- `GET /manifest.json`, `/sw.js`, `/icon.png` (`server_assets/icon.png`) — the PWA files.
  `vercel.json` routes everything to FastAPI, so these need their own routes (all three 404'd
  before 26 Sep 2026).
- `GET /api/data` → `{monthly, yearly, news, ritholtz, totals, updated}`:
  - **Reddit** = every `data/r_*/posts.csv` whose sub is in `SUBREDDITS` (imported from
    `core/reddit_common.py`; `vercel.json` bundles `core/**` for this). Folder `_yearly` → Yearly,
    else Monthly. CSVs without `id`/`title` are skipped. Dedup on `(id, time_filter)`, sorted by
    `score` (the tier mix), stable. Each post gets its `rank` in its own sub's list.
    `shown_upvotes()` = the real `upvotes` when numeric, else `score` only if `score_real` (old
    JSON rows), else `""` (the card shows "#3 this month").
  - **Monthly** drops r/AskHistorians (it lives in Yearly) *before* the cap, then takes the top
    50. **Yearly** skips posts already in Monthly, then takes the top 50 (backfilling from further
    down). `totals.monthly` / `totals.yearly` = how many they were picked from (the page says
    "top 50 of 534").
  - **News** = every story from the last `NEWS_DAYS = 7` days, **no count cap** (the tab's number
    is the real volume). One card per headline (`title_key`: lowercase alphanumerics, 70 chars),
    keeping the EARLIEST copy so a story already marked read can't come back as new. Newest
    first; full `ts` so the page can say "3h ago". `totals.news_days = 7`.
  - **ritholtz** = `data/ritholtz/articles.csv` (`rth_` ids) + the last 7 days of
    `data/trung/articles.csv` (`trg_` ids), sorted by date, newest first, capped at 50.
  - **`updated`** = `{news, ritholtz, reddit}` (UTC ISO): the newest `scraped_at` in each news
    CSV, and the newest Mac save in `data/reddit_browser.json` (tracked subs only).
  - Items carry structured fields (`upvotes`, `rank`, `when`, `mins`, `ts`, `date`, `kind`,
    `category`, `source`, `domain`); `meta` is a legacy display string the page doesn't parse.
- `GET /api/status` → the health page for fleet-health and humans:
  `reddit_lists` (each `{list, saved, checked}`, **oldest `checked` first**; `""` = no stamp
  yet), `reddit_oldest` (oldest save), `reddit_missing` (tracked lists the Mac has never saved:
  an oldest-stamp check can't see those),
  `tracked_subs` (13; `null` means the `core` import failed on Vercel), `updated`, `counts`.

**Failure behavior (robustness, 26 Sep 2026):** every CSV goes through `read_csv_safe()` and
every tab is built inside its own `try`. A missing, empty or broken file costs only its own tab,
never the others; one odd Reddit row (e.g. an `inf` number) costs only that row
(`reddit_item()` runs per row). All of it is logged (logger `daily-reader`, visible in Vercel's runtime logs) instead
of vanishing in a bare `except: pass`. If `core.reddit_common` can't be imported, the server logs
it and shows every `data/r_*` list rather than going down.

Helpers: `format_score` (`82450 → 82.4k`), `calculate_reading_time` (~200 wpm), `clean_text`
(`html.unescape`, NaN-safe, fixes scraped spacing), `short_text` (500 chars at a word boundary),
`domain_of`, `title_key`, `newest_scrape`.

---

## 4. Run / test / deploy

### Local
```bash
python3.10 -m venv .venv && .venv/bin/pip install -r requirements-scraper.txt pytest httpx
# 3.10 = CI. pandas==2.1.4 has no wheels past Python 3.12; the owner's .venv is 3.14 with
# pandas 3 installed by hand, and the code works on both (CI proves the pinned one).
.venv/bin/uvicorn server:app --reload            # http://localhost:8000
.venv/bin/python core/scrape_top.py              # scrapers write into ./data/
.venv/bin/python core/scrape_ritholtz.py
.venv/bin/python core/scrape_googlenews.py
.venv/bin/python core/scrape_trung.py
python3 core/scrape_reddit_browser.py --only LifeProTips --visible   # needs Playwright
```

### Tests
- **`.venv/bin/python -m pytest tests -q`** — 33 tests, ~10 s, no network:
  - `tests/test_am_reads.py`: AM Reads cleanup/dedup helpers.
  - `tests/test_feeds.py`: RSS parsing + honest scores, the News retry (503/404), the live API's
    honesty/no-repeats rules on the committed data, the Mac scraper's rows and CSV round trip,
    tier ordering, the 36 h skip and broken stamps.
  - `tests/test_robustness.py`: the server against a throwaway `data/` (a broken News CSV
    doesn't touch Reddit, a dropped sub is hidden, one junk number costs one row, a Reddit crash
    still serves News, `/api/status` shape and `checked`), `page_ok` / `update_meta`, and **the
    Mac wrapper against a local bare git repo with a fake scraper**: first run, no-change vs
    failed scrape, the lock (live and dead), a push race with another job, a clone left
    mid-rebase, a stale `index.lock`, a broken clone, the log trim. It also pins the exact log
    patterns fleet-health greps for.
- **`python3 tests/e2e_site.py [base_url]`** — 35 real-browser checks (~40 s): every tab shows
  all the API's posts with the right label, real upvotes on cards, opening ≠ reading, the
  "Done with X?" prompt, undo, keys, stale notices (News 36 h, Reddit 48 h), footer stamps,
  phone layout, no JS errors. Needs Playwright (use `/opt/homebrew/bin/python3` on the Mac; the
  venv doesn't have it). Always a fresh throwaway headless browser. Run it against a local
  server before shipping UI changes, and against the live URL after.
- **CI:** `.github/workflows/tests.yml` runs pytest on every push to `main` that touches code
  (`paths-ignore: data/**`), and on PRs. Public repo, so the minutes are free.

### Deploy (Vercel)
- **Auto-deploys on every push to `main`** (including the robots' data commits).
- `vercel.json`: legacy `builds` API, `@vercel/python` on `server.py`, `config.includeFiles` =
  `templates/**, data/**, server_assets/**, core/**, manifest.json, sw.js`.
- Vercel installs only `requirements.txt`.
- After a deploy, check: `curl -s https://reddit-scraper-lyart.vercel.app/api/status` shows
  `"tracked_subs": 13`, then run `tests/e2e_site.py` against the live URL.

### CI: the scrape workflows
- `daily_scrape.yml`: Python 3.10, `pip install -r requirements-scraper.txt`, runs the four
  GitHub-side scrapers, `git add -f data/`, commits "Automated daily data update", pushes with a
  3-try rebase loop, then prints `DATA PUSHED: N data files` (fleet-health greps it). Nothing new
  → `NO DATA CHANGES`. `workflow_dispatch` always runs.
- **Two crons + dedupe guard (don't "simplify" away):** `0 3 * * *` is the real run; `0 9 * * *`
  is a retry added after 2026-07-09, when GitHub never assigned a runner to the 03:00 job. A guard
  skips *scheduled* runs when **`data/googlenews/`** was already committed today (UTC). It checked
  all of `data/` until 26 Sep 2026, but `am_reads.yml` commits every morning and the Mac commits
  twice a day, so the retry never ran when News failed. Checkout uses `fetch-depth: 50` (the guard
  needs history); `concurrency: daily-scrape` (no cancel) serializes a late 03:00 against 09:00.
- `am_reads.yml`: ritholtz + trung only, commits only on change.

### Dependency split (keep it, see §5)
- `requirements.txt` — Vercel minimal: `fastapi, uvicorn, Jinja2, pydantic, pandas==2.1.4,
  numpy==1.26.4`.
- `requirements-scraper.txt` — `-r requirements.txt` + `requests, beautifulsoup4, lxml`.
- `requirements-dev.txt` — `-r requirements-scraper.txt` + `streamlit` (legacy dashboard only).
- The Mac scraper needs only Python 3 + Playwright (`/opt/homebrew/bin/python3` has it).

### Secrets / env vars (named only — never commit values)
- None are needed by anything live. `REDDIT_CLIENT_ID/SECRET/USER_AGENT` (read by `config.py`)
  are only for the legacy PRAW path in `diagnostics/`. `SCRAPESERV_URL`, `DISCORD_WEBHOOK_URL`,
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DATABASE_URL` belong to legacy code.
  `.env.example` documents the Reddit/ScrapeServ vars; `.env` is gitignored.
- **The Firebase web config is committed in `templates/index.html`** (project `dailyreadersync`).
  A Firebase web API key is a public client identifier, not a secret; security is Firestore
  rules. Not a leak, but never add server-side secrets there.

---

## 5. Gotchas / hard rules (highest-value section)

1. **Vercel 250 MB lambda limit — keep `requirements.txt` minimal.** No `streamlit`, `lxml`,
   `beautifulsoup4`, `playwright` there. Scraper deps → `requirements-scraper.txt`.
2. **`vercel.json` must use the legacy `builds` API.** No top-level `functions` (schema
   conflict). Extra bundled files go in `config.includeFiles` **inside the `builds` entry**. A new
   folder `server.py` imports from (like `core/`) must be added there or it's missing on Vercel.
3. **Absolute paths only in `server.py`.** Derive from `BASE_DIR = Path(__file__).resolve().parent`.
4. **`TemplateResponse` takes keyword args:** `templates.TemplateResponse(request=request,
   name="index.html")`. Newer Starlette crashes on positional args.
5. **`index.html` is a Jinja template:** never write `{{`, `{%` or `{#` in its JS or CSS.
6. **Reddit from GitHub: never fixed sleeps.** Keep `random.uniform(6.5, 12.5)` between subs in
   `scrape_top.py`; if 429s grow, *widen* it.
7. **The scoring math is load-bearing — don't touch it** (§2c). Change only with permission.
8. **Never show an invented number.** Displayed upvotes come only from Reddit (`upvotes`, or
   `score` when `score_real`). Otherwise show the rank.
9. **`data/` needs `git add -f`, always.** `.gitignore` has `data/` followed by
   `!data/**/*.csv` / `!data/**/*.json`, but git never looks inside an ignored directory, so the
   `!` lines do nothing for new files. Every robot force-adds. A new file under `data/` that isn't
   force-added silently never ships.
10. **Write modes differ per scraper** (§2 table). Don't "fix" googlenews to overwrite: it keeps a
    rolling history on purpose.
11. **The `ritholtz` key carries two sources** (Ritholtz + SatPost).
12. **"Show read" hides read items from every tab except Favorites and search results.** Muting
    r/AskHistorians on Monthly is done server-side (§3); the old frontend `mutedKeywords` is gone.
13. **Keep the permalink double-prefix guard** (`https://www.reddit.comhttps://…`) in
    `server.py`: tiers build permalinks differently.
14. **The Mac job runs from its own clone**, updated by `git reset --hard origin/main` each run.
    Editing `mac/reddit-browser.sh` in PyCharm changes nothing until it's pushed. The plist is
    the exception: after changing it, `cp` it to `~/Library/LaunchAgents/`, then `launchctl
    bootout` + `bootstrap`.
15. **Don't change the wrapper's log lines without updating fleet-health** (§8) and
    `tests/test_robustness.py` (which pins them).

---

## 6. Known issues / legacy code (verified 26 Sep 2026)

- **`config.py:SUBREDDITS` is a different, stale list** (has `sobooksoc` and `Fitness`, lacks
  `bestof`/`AskHistorians`). Only the legacy `dashboard.py` reads it. The live list is
  `core/reddit_common.py:SUBREDDITS`.
- **`server_assets/style.css` is unused.** Nothing links to it (the page's CSS is inline in
  `index.html`); it still gets bundled.
- **Daily Star is inactive:** `config.py:DAILYSTAR_FEEDS` + `scrape_dailystar.py` aren't in any
  workflow and `server.py` doesn't read them. Google News replaced it.
- **`dashboard.py` (Streamlit) is a legacy local viewer**, not the deployed UI. It reads the same
  CSVs plus `data/read_posts.json`.
- **`scraper/async_scraper.py` has a broken import** (`from config import USER_AGENT, MIRRORS, …`,
  but those live in `scraper_config.py`). Unused experimental code.
- **`database.py` (SQLAlchemy) is unused.** It still runs `init_db()` on import and would create
  `data/reddit_daily.db`.
- **`diagnostics/` is a drawer of one-off tools, run by nothing:** `reddit_scraper.py` (PRAW,
  needs the API keys), `scraper_main.py`, `scheduler.py` (superseded by the workflows),
  `final_stress_test.py` / `verify_hierarchy.py` (import `scrape_top` as top-level, so only work
  from inside `core/`), `test_html.py` / `test_rss.py` (manual probes). `run.sh` calls
  `diagnostics/scraper_main.py`.
- **`.scrapeserv_clone/` is empty;** `docker-compose.yml` defines an optional ScrapeServ
  screenshot service and the Streamlit dashboard. Neither is needed.
- **`daily_morning.sh` / `run.sh` hardcode the owner's old local paths** (`~/PycharmProjects/Reddit
  Scraping`, a `venv`). Personal convenience scripts.

---

## 7. File / module map

**Live production path:**
- `server.py` — FastAPI: `/`, `/api/data`, `/api/status`, PWA files (§3).
- `templates/index.html` — the whole page (plain CSS tokens + Phosphor icons + Firebase; no
  Tailwind, no build step). 5 tabs with unread counts; progress row ("50 of 50 left · top 50 of
  534", "27 of 27 left · last 7 days") + Mark all read (with Undo); swipe left = read, right =
  favorite; search across tabs; text size + light/dark/auto; keys j/k/o/r/f/u(z); remembers tab
  and scroll; re-fetches when resumed after 20 min. **Opening a link must NOT mark it read** (the
  owner peeks without reading; only the tick / left swipe / `r` / Mark all read / the prompt's
  "Mark read" count). Opened-but-unread cards get a hollow dot + "Opened" tag (localStorage
  `dr_opened`, 21 days); coming back after 10+ s shows "Done with X? [Mark read]"; tap a blurb to
  expand; "New" tag = first seen on this device today (`dr_first_seen`). **Warning cards:** News
  when `updated.news` is 36 h+ old; Monthly/Yearly when `updated.reddit` is 48 h+ old (the Mac
  stopped; lists may be older and show ranks). Footer: when AM Reads, News and Reddit last
  landed. Sync write failures show a toast + "(offline)". Firebase layout:
  `sync_groups/{key}/favorites` + `read_posts`.
- `manifest.json` + `sw.js` — PWA; network-first service worker (cache `daily-reader-v2`, only
  the offline fallback).
- `server_assets/icon.png` — app icon.
- `core/reddit_common.py` — `SUBREDDITS`, tiers, freshness handshake (shared, stdlib only).
- `core/scrape_reddit_browser.py` — the real Reddit source (Mac mini).
- `mac/reddit-browser.sh` + `mac/com.jalal.reddit-browser.plist` — its launchd job.
- `core/scrape_top.py` — GitHub's Reddit backup (JSON → HTML → RSS).
- `core/scrape_ritholtz.py`, `core/scrape_googlenews.py`, `core/scrape_trung.py` — the other feeds.
- `vercel.json` — deploy config.
- `.github/workflows/daily_scrape.yml`, `am_reads.yml` — scrape + commit; `tests.yml` — pytest.
- `tests/` — §4.
- `data/**` — committed scrape output (the "database").

**Config:** `config.py` (paths, legacy `SUBREDDITS`, Daily Star feeds, timing constants);
`scraper_config.py` (legacy async/diagnostics settings).

**Legacy / inactive:** `dashboard.py`, `database.py`, `scrape_dailystar.py`, `scraper/`,
`scraper_client.py` (ScrapeServ client), `diagnostics/`, `daily_morning.sh`, `run.sh`,
`docker-compose.yml`, `.scrapeserv_clone/`, `server_assets/style.css` (§6).

---

## 8. Health checks and runbook

**Who watches it:** fleet-health (`~/PycharmProjects/github-notion-sync/fleet_health.py`, runs on
the Mac at 05:00 + 06:30) has three rows for this repo:

| Row | Probe | Red when |
|---|---|---|
| `reddit-scraper (daily data)` | GitHub run of `daily_scrape.yml` | no run in 36 h, or no `DATA PUSHED` / guard line |
| `reddit-browser (Mac 07:35/19:35 Reddit lists)` | last block of `~/Library/Logs/reddit-browser.log` | last `== … start` over 26 h old, or that block lacks `REDDIT PUSHED: N files` / `NO REDDIT CHANGES (scraper exit 0)` |
| `reddit-browser (live site: every Reddit list fresh)` | live `/api/status` | the OLDEST `reddit_lists[].checked` is over 36 h old (fleet reads UTC stamps as local time, so really 40–41 h: the third missed run) |

**Is it healthy right now?** (3 commands)
```bash
curl -s https://reddit-scraper-lyart.vercel.app/api/status | python3 -m json.tool | head -30
grep -E '^== |BROWSER SAVED|REDDIT PUSHED|NO REDDIT|FAILED|ACTIVE' ~/Library/Logs/reddit-browser.log | tail -8
launchctl print gui/$(id -u)/com.jalal.reddit-browser | grep -E 'state|last exit'
```

**When something's wrong:**
- **Mac job didn't run** (no new `== … start`): the Mac was asleep/off at 07:35 or 19:35, or the
  job isn't loaded. `launchctl print …` (above); reload per §2b. Run it now with
  `launchctl kickstart gui/$(id -u)/com.jalal.reddit-browser`.
- **`4 lists in a row failed` / `page showed 0 posts`**: Reddit is blocking the browser. Wait for
  the next run (the profile keeps its cookie; the warm-up usually passes). To look yourself:
  `python3 core/scrape_reddit_browser.py --only LifeProTips --visible` from the job clone. Never
  point it at a personal Chrome profile.
- **`browser missing`**: handled automatically (it installs Chromium). If the install fails:
  `/opt/homebrew/bin/python3 -m playwright install chromium`.
- **`ANOTHER RUN IS ACTIVE`** on every run: a lock from a crashed run is taken over after 40 min
  automatically. If it persists: `ls -la ~/.local/share/reddit-browser/run.lock`.
- **`PUSH FAILED after 3 tries`**: GitHub was down or rejected the push. The next run redoes the
  whole list from a fresh reset; nothing to clean up.
- **Site shows "#3 this month" instead of upvotes on some cards**: those lists came from GitHub's
  RSS backup (the Mac hasn't saved them in 36 h). `/api/status` → `reddit_missing` and the oldest
  `saved` stamps say which. `checked` newer than `saved` = the Mac reaches the page but the list
  is too short (under 5 posts) or all videos: nothing is broken.
- **`GIT SYNC FAILED` / `CLONE FAILED`**: GitHub unreachable (the next run retries; a deleted
  clone is re-cloned automatically).
- **A tab is suddenly empty**: check Vercel's runtime logs for `daily-reader` warnings (a broken
  CSV is logged there and costs only its own tab).
