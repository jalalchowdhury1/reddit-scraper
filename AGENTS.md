# AGENTS.md — Daily Reader (Reddit & News Aggregator)

> **The single source of truth for anyone (human or AI) touching this repo.** Read it fully
> before changing code or deploying. `README.md` is the short GitHub landing page; when the two
> disagree, this file wins, and whoever notices fixes the other one. Last full accuracy pass
> against the code: 26 Sep 2026.

Live site: **https://reddit-scraper-lyart.vercel.app** · Health: **`/api/status`** ·
Repo: `github.com/jalalchowdhury1/reddit-scraper` (public) · Python + vanilla JS.

---

## 1. What this is

A **zero-cost personal reading page**. It pulls the top posts from 13 subreddits, Bangladesh
news, two newsletters and GitHub's trending top 10 into one page, and syncs "read" / "favorite" across devices with
Firebase.

**In 30 seconds:** robots save lists as CSV files into `data/` and push them to GitHub →
Vercel redeploys on every push → `server.py` turns the CSVs into one JSON answer → the page
(`templates/index.html`) shows it. Nothing is stored on the server; your read/favorite state
lives in the browser and in Firebase.

**The robots (who writes what):**

| Robot | When | Writes |
|---|---|---|
| **Mac mini** launchd `com.jalal.reddit-browser` → `mac/reddit-browser.sh` → `core/scrape_reddit_browser.py` | 07:35 + 19:35 local | `data/r_<sub>[_yearly]/posts.csv` with **real upvotes**, `data/reddit_browser.json` |
| GitHub `.github/workflows/reddit_backup.yml` | every 3 h (`:17`) | Reddit **only for lists the Mac hasn't saved in 36 h** (RSS, 6 per run, stalest first), `data/reddit_github.json` |
| GitHub `.github/workflows/daily_scrape.yml` | 03:00 UTC, retry 09:00 UTC | News, AM Reads, SatPost (no Reddit since 26 Sep 2026) |
| GitHub `.github/workflows/am_reads.yml` | 11:45 / 13:30 / 15:30 UTC | AM Reads + SatPost again (Ritholtz posts ~6:30 AM ET) |
| GitHub `.github/workflows/github_trending.yml` | every 6 h (`:41`) | `data/github_trending/repos.csv` (github.com/trending, today) |

### Data flow

```
Mac mini, 07:35 + 19:35 (real headless browser; Reddit blocks GitHub's IPs)
   └─ core/scrape_reddit_browser.py → data/r_<sub>[_yearly]/posts.csv + data/reddit_browser.json
   └─ git add -f … && commit && push           (its own clone, 3-try rebase loop)
GitHub Actions, every 3 h (reddit_backup.yml)
   └─ core/scrape_top.py --max-lists 6 → Reddit backup: lists the Mac missed for 36 h (RSS, no upvotes)
GitHub Actions, 03:00 UTC (+ 09:00 retry)
   └─ core/scrape_ritholtz.py   → data/ritholtz/articles.csv   (only today's list, no repeats)
   └─ core/scrape_googlenews.py → data/googlenews/articles.csv (append + dedup)
   └─ core/scrape_trung.py      → data/trung/articles.csv      (overwrite)
   └─ git add -f data/ && commit && push
GitHub Actions, every 6 h (github_trending.yml)
   └─ core/scrape_github_trending.py → data/github_trending/repos.csv (overwrite, only if list_problem() passes)
                                  │
                                  ▼  Vercel auto-deploys every push to main
Browser ─▶ server.py (FastAPI on Vercel) ─▶ GET /api/data
              ▼
   { monthly, yearly, news, ritholtz, github, totals, reddit_subs, updated }
              ▼
index.html: 6 tabs (Monthly / Yearly / News / AM Reads / GitHub / ★ Favorites)
   read + favorite state ↔ localStorage ↔ Firebase Firestore (cross-device)
```

Ritholtz **and** SatPost (Trung) items both go into the **`ritholtz`** key and show together on
the **AM Reads** tab (`AM READS` / `WEEKEND READS` vs `SATPOST` in each item's meta).

---

## 2. The scrapers (`core/`)

| Script | Runs on | Source | Output | Write mode |
|---|---|---|---|---|
| `core/scrape_reddit_browser.py` | **Mac mini** (launchd) | headless Chromium: top page → top.json → RSS | `data/r_<sub>/posts.csv`, `data/r_<sub>_yearly/posts.csv`, `data/reddit_browser.json` | **overwrite** per list, only when a method passed every check |
| `core/scrape_top.py` | GitHub (every 3 h) | Reddit RSS → JSON | same Reddit files, `data/reddit_github.json` | **overwrite**, only lists the Mac left stale for 36 h |
| `core/scrape_ritholtz.py` | GitHub (daily + am_reads) | ritholtz.com AM Reads / Weekend Reads | `data/ritholtz/articles.csv` (+ `seen.json`) | **overwrite**, only when the post changed |
| `core/scrape_googlenews.py` | GitHub (daily) | Google News RSS (Bangladesh) | `data/googlenews/articles.csv` | **append + dedup** on `(article_id, category)` |
| `core/scrape_trung.py` | GitHub (daily + am_reads) | readtrung.com Substack RSS (SatPost) | `data/trung/articles.csv` | **overwrite** |
| `core/scrape_github_trending.py` | GitHub (every 6 h) | github.com/trending HTML (today, all languages) | `data/github_trending/repos.csv` | **overwrite**, only when `list_problem()` passes |

`core/reddit_common.py` (stdlib only) holds what the Reddit scrapers share: **`SUBREDDITS`
(the authoritative list, 13 entries)**, `SUBREDDIT_TIERS`, `tier_score()`, and the Mac/GitHub
freshness handshake (`data/reddit_browser.json`, `FRESH_HOURS = 36`).
Nothing in `diagnostics/` or `scraper/` runs anywhere (see §6).

### 2a. `core/scrape_reddit_browser.py` — the real Reddit source (Mac mini, since 26 Sep 2026)

**Why a browser:** Reddit blocks every plain request now. GitHub's IPs get 403/429, and even the
owner's home IP gets a JavaScript bot check on the JSON and HTML endpoints. A real headless
Chromium (Playwright) passes that check by itself on the first subreddit page it opens (the URL
gets `js_challenge=1`; the home-page warm-up alone does not trigger it). The new Reddit page
carries each post as a `<shreddit-post>` with attributes `id`, `score`, `comment-count`,
`post-title`, `post-type`, `permalink`, `created-timestamp`, `subreddit-name`; self-post text
sits in `[slot="text-body"]` (ads are a separate `shreddit-ad-post`). So: real upvotes, real
text, no login, no key, no AI. **The official OAuth API was tried and never worked for the
owner. Don't suggest it again.**

**The backup ladder** (each rung checked live on 26 Sep 2026). Per list, first one that passes wins:

| # | Method | Where | Gives | Covers |
|---|---|---|---|---|
| 1 | `page`: the new-Reddit top page (`via_page`) | Mac | real upvotes + text | normal days |
| 2 | `json`: `top.json?raw_json=1` through the same browser (`via_json`) | Mac | real upvotes + text | a page layout change (no `shreddit-post`, no `score`) |
| 3 | `rss`: `top/.rss` through the same browser (`via_rss`) | Mac | text, **no upvotes** (site shows the rank) | JSON gone too |
| 4 | a fresh throwaway profile | Mac | retries 1-3 | a profile that won't open, or one Reddit blocks (4 page misses in a row) |
| 5 | GitHub RSS (`reddit_backup.yml`) | GitHub | text, no upvotes | the Mac down, or its IP blocked, for 36 h+ |

Rungs 1-3 share the Mac's IP: they fix page/layout trouble, not an IP block (a burst of test runs
on 26 Sep got JSON 403 and RSS 429 for a while). Rung 5 is on another IP for that case.
`old.reddit.com` is no longer a rung: it sends logged-out visitors to a login page (and 403s
GitHub). JSON needs the cookies from Reddit's bot check; on a 403 `via_json` loads the list page
once and asks again (proven: home page = 2 cookies + 403, after one list page = 14 cookies + 200).

**What every method's result must pass** (`list_problem()`, else it isn't saved): still on
`/r/<sub>/top` with `t=<month|year>` after redirects (catches a login wall or a bounce to the
sub's front page); at most 1 in 5 posts from another sub; at most 1 in 5 older than 40 days
(month) / 400 days (year) (catches an all-time list); at least half the posts show upvotes on
`page`/`json` (catches a layout change that drops them); at least `MIN_POSTS = 5` posts, unless
the method proves the list is complete (JSON `after: null`; or RSS returning fewer than the 50
asked for, trusted only when the page or JSON also saw that list short, because a broken feed
looks the same). That last rule is how r/lifehacks (6-8 posts in Sep 2026) now gets saved.

What one run does (~5–6 min):
- Warm-up load of reddit.com, then for each of the 13 subs × `month`/`year`: open
  `/r/<sub>/top/?t=<month|year>`, scroll like a person until 50 posts (max 10 scrolls, stops after
  3 scrolls with nothing new), read the attributes. Videos are skipped (it's a reading list).
- The page gets one retry after a fresh warm-up (not when it was merely short, and not once it
  has missed 2 lists in a row: the retry would only eat the backups' time), then `json`,
  then `rss` (the ladder above). A backup that saves prints `↪ <list>: page: <why>` first and
  `✅ … via json|rss`. All fail → `⚠️ <list>: old file kept. page: …; json: …; rss: …`.
- **4 page misses in a row** (no real list at all) → one switch to a fresh throwaway profile,
  which retries the lists that failed or only got RSS. **4 lists in a row failing every method**
  after that = stop (hammering makes a block worse). If the page misses 4 more lists in a row on
  the fresh profile, the rest of the run skips it (`⏭️ … json, rss only`): a layout change costs
  ~50 s a list in page timeouts, which would push the last lists past the deadline. No new list
  starts after 12 min (`RUN_DEADLINE_S`; one slow list can take ~6 min and the wrapper kills the
  run at 20). Each JSON/RSS request times out at 20 s.
- Human pace: 3–7 s between pages. JSON/RSS answer a 429 by waiting (Retry-After, max 20 s) once.
- `data/reddit_browser.json` gets three maps per list, written **right away** (a run killed
  midway keeps what it did): `lists` = last **saved** (GitHub's backup keys off this),
  `checked` = last time Reddit served the list's real list, saved or not (a challenge page has no
  posts), and `via` = which method saved it (`page`/`json`/`rss`). `/api/status` shows `via`,
  or `github rss` when GitHub's backup refilled the list after the Mac's last save.
  fleet-health grades `checked`.
- Profile trouble: if `~/.local/share/reddit-browser/profile` won't open, it deletes Chromium's
  `Singleton*` lock links (left by a killed run) and tries again, then falls back to a fresh
  throwaway profile (`🆕 using a fresh throwaway profile`), deleted at the end.
- If Playwright was upgraded and its browser is missing ("Executable doesn't exist"), it runs
  `python3 -m playwright install chromium` once and carries on.
- **Ends with the backup check:** fetches the first sub's monthly list via `json` and `rss`
  (nothing written) and prints `METHOD CHECK: page ok · json ok · rss ok  (page saved N of M
  lists)`, or names what failed (`page FAILING` = the page saved under half the lists). fleet-health
  greps this line, so a dead backup shows up before the day it's needed.
- Prints `BROWSER SAVED: N of M lists` (+ which kept their old file). Exit 1 if it saved none.
- Stdlib + Playwright only: the Mac's `/opt/homebrew/bin/python3` has Playwright but no pandas.
- Manual runs (write into `./data/` of the current folder, so run them from a scratch folder
  unless you mean it): `python3 core/scrape_reddit_browser.py [--only sub1,sub2] [--visible]
  [--profile DIR | --fresh-profile] [--method page|json|rss]`.
  **`--probe`** tries every method on each `--only` list (default LifeProTips), prints what each
  got, writes nothing, exit 1 if any failed: the first thing to run when Reddit looks broken.

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
4. Checks `python3` can `import playwright`. A brew Python upgrade (3.14 → 3.15) leaves it behind,
   so it runs `pip install --break-system-packages playwright` once (`🔧 playwright missing for
   Python X: installing it` → `🔧 playwright installed` / `INSTALL FAILED`).
5. Runs the scraper under `timeout 1200` with `python3 -u` (unbuffered: a killed run still leaves
   its lines in the log), profile `~/.local/share/reddit-browser/profile` (a throwaway profile
   just for this job; it keeps Reddit's cookie).
6. `git add -f data/r_*/posts.csv` (+ the json if present). Nothing changed →
   `NO REDDIT CHANGES (scraper exit N)` and exits with the scraper's code.
7. Commits, then pushes with a 3-try loop (`git pull --rebase -X theirs` between tries, because
   GitHub's jobs push to the same branch). Success line:
   `REDDIT PUSHED: N files in <sha> (scraper exit N)`, then `== … done`.

Failure lines: `LOCK FAILED`, `CLONE FAILED`, `GIT SYNC FAILED`, `COMMIT FAILED`,
`PUSH FAILED after 3 tries`.
Log: `~/Library/Logs/reddit-browser.log`. The wrapper trims it in place (past ~500 KB, keeps the
last 3000 lines). `REDDIT_BROWSER_*` env vars exist only so the tests can point it at a local
git repo and a fake python.

**Install / reinstall** (after the code is on `origin/main`; also in the plist's top comment):
```bash
git clone https://github.com/jalalchowdhury1/reddit-scraper.git ~/.local/share/reddit-browser/reddit-scraper
cp mac/com.jalal.reddit-browser.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jalal.reddit-browser.plist
launchctl kickstart gui/$(id -u)/com.jalal.reddit-browser     # run now, under launchd itself
tail -f ~/Library/Logs/reddit-browser.log
```

**Known, accepted race:** if GitHub's backup run overlaps a Mac push, the rebase (`-X theirs`)
can keep GitHub's RSS copy of a list under the Mac's fresh stamp. It lasts until the next Mac run
(≤12 h), and RSS rows are honest (rank, no fake upvotes).

### 2c. `core/scrape_top.py` — GitHub's Reddit backup (`reddit_backup.yml`, every 3 h)

What reaches Reddit from GitHub's IPs (tested from a runner on 26 Sep 2026): **RSS only**, and
only until rate-limited (first call 200, later ones 429). JSON is 403 (plain or via a browser),
a real browser gets "You've been blocked by network security", old.reddit is 403. So:
- `main()` reads the Mac's `data/reddit_browser.json` and its own `data/reddit_github.json`
  (a broken json = "nothing is fresh", never a crash). A list needs a refresh when the Mac hasn't
  saved it in 36 h **and** this backup hasn't refreshed it in 12 h (`GITHUB_REFRESH_HOURS`).
  `stale_lists()` sorts them stalest first (never saved = first). `--max-lists 6` per run: small
  batches stay under the rate limit, and 8 runs a day still cover all 26 lists within a day.
  Its own stamps are what make the batches move on instead of redoing the same six.
- Per list: **RSS** `www.reddit.com/r/{sub}/top/.rss?t={filter}&limit=50` (no scores; self-post
  text from `<div class="md">`; a 429 gets one retry, Retry-After max 60 s, within a 480 s
  budget), then **JSON** `old.reddit.com/r/{sub}/top.json` as a second try in case Reddit ever
  lets GitHub back in (real scores, `score_real=True`). Both answers must pass the Mac's
  `list_problem()` (imported from `scrape_reddit_browser.py`, stdlib only) with no short-list
  proof, so under 5 posts is never saved here. `parse_rss()` is pure (tested). The old.reddit
  HTML tier was removed on 26 Sep 2026 (login wall).
- Prints `REDDIT BACKUP: refreshed N of M lists that needed it (tried K)`. With nothing to do it
  reads one list's RSS (the sub rotates every 3 h), writes nothing, and prints
  `GITHUB REDDIT CHECK: rss ok (r/<sub>: 50 posts)` / `rss FAILED`. fleet-health greps these.
- Hard stop at 12 min (`RUN_DEADLINE_S`; the job's timeout is 20). The workflow commits
  `data/r_*/posts.csv` + `data/reddit_github.json` with the same 3-try rebase loop and prints
  `REDDIT BACKUP PUSHED: N files` (or `NO REDDIT BACKUP CHANGES`).

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
- Exit code (27 Sep 2026): `main()` exits **1** when nothing was saved (every query failed, or
  nothing passed the filters) or the save raised; its last line is
  `GOOGLE NEWS: saved N articles (T total rows, F/3 queries failed)` or
  `GOOGLE NEWS FAILED: …`. Before this, a run where all 3 queries died exited 0 (26 Sep).
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

### 2f. `core/scrape_github_trending.py` — GitHub tab (added 27 Sep 2026)
- No official trending API, so it parses `https://github.com/trending` (one
  `<article class="Box-row">` per repo). Saves **every** repo on the page (usually 15-25) in
  GitHub's own order: `rank, repo, url, description, language, stars, forks, stars_today,
  scraped_at`. The site shows the top 10 (`server.py:GITHUB_TOP`).
- `list_problem()` refuses a list with fewer than 10 repos, a repeated repo, or star counts
  missing on most rows (= the layout changed). Refused or failed fetch → exit 1, the old file
  stays, the workflow run goes red. Same rule as Reddit: a wrong list is worse than an old one.
- `fetch()` retries 5xx/429/network errors 3 times (waits 5 s, 20 s); other 4xx fail at once.
- Log lines: `GITHUB TRENDING OK: N repos (top: …)` / `GITHUB TRENDING FAILED: <why>`; the
  workflow prints `GITHUB TRENDING PUSHED: <sha>` or `NO CHANGE`.
- Runs on GitHub Actions: GitHub doesn't block its own runners. Star counts move every run, so
  expect a data commit (= a Vercel deploy) every 6 h.
- GitHub's order is **not** "most stars today" (e.g. #3 can have fewer than #4). The tab keeps
  GitHub's order on purpose: "top 10" means what github.com/trending shows.

---

## 3. Backend (`server.py`)

**Endpoints**
- `GET /` → `templates/index.html` (Jinja, keyword-arg `TemplateResponse`).
- `GET /manifest.json`, `/sw.js`, `/icon.png` (`server_assets/icon.png`) — the PWA files.
  `vercel.json` routes everything to FastAPI, so these need their own routes (all three 404'd
  before 26 Sep 2026).
- `GET /api/data` → `{monthly, yearly, news, ritholtz, github, totals, reddit_subs, updated}`:
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
  - **github** = `data/github_trending/repos.csv` sorted by `rank`, rows that aren't `owner/name`
    or have no numeric rank dropped, deduped by repo, top `GITHUB_TOP = 10`. Card: `title` =
    `owner/name`, `id` = `gh_owner_name` lowercased (**no `/`**: read state is one Firestore doc
    per id and a slash would split the path), `rank`, `stars` ("87.5k"), `stars_today`
    ("2,608"), `language`; numbers blank when the page didn't give them. `totals.github` = repos
    on the page ("top 10 of 15").
  - **`reddit_subs`** = the tracked subs (sorted). The page forgets kept unread posts whose sub
    isn't in it, so removing a sub also clears it from every device's kept list.
  - **`updated`** = `{news, ritholtz, reddit, github}` (UTC ISO): the newest `scraped_at` in each
    news/GitHub CSV, and the newest Mac save in `data/reddit_browser.json` (tracked subs only).
  - Items carry structured fields (`upvotes`, `rank`, `when`, `mins`, `ts`, `date`, `kind`,
    `category`, `source`, `domain`); `meta` is a legacy display string the page doesn't parse.
- `GET /api/status` → the health page for fleet-health and humans:
  `reddit_lists` (each `{list, saved, checked, via}`, **oldest `checked` first**; `""` = no stamp
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
.venv/bin/python core/scrape_github_trending.py
python3 core/scrape_reddit_browser.py --only LifeProTips --visible   # needs Playwright
```

### Tests
- **`.venv/bin/python -m pytest tests -q`** — 86 tests, under a minute, no network:
  - `tests/test_am_reads.py`: AM Reads cleanup/dedup helpers.
  - `tests/test_feeds.py`: RSS parsing + honest scores, the News retry (503/404), the live API's
    honesty/no-repeats rules on the committed data, the Mac scraper's rows and CSV round trip,
    tier ordering, the 36 h skip and broken stamps.
  - `tests/test_robustness.py`: the server against a throwaway `data/` (a broken News CSV
    doesn't touch Reddit, a dropped sub is hidden, one junk number costs one row, a Reddit crash
    still serves News, `/api/status` shape, `checked` and `via`, `reddit_subs`), the short-list
    rule, `update_meta`, and **the Mac wrapper against a local bare git repo with a fake
    scraper**: first run, no-change vs failed scrape, the lock (live and dead), a push race with
    another job, a clone left mid-rebase, a stale `index.lock`, a broken clone, the log trim, and
    the Playwright reinstall after a Python upgrade (fake `python3`). It also pins the exact log
    patterns fleet-health greps for.
  - `tests/test_github_trending.py`: the parser on a saved copy of the real page
    (`tests/fixtures/github_trending.html`, 12 rows), `list_problem()` (layout change, moved
    star counts, short or repeated list), `main()` keeps the old file on a bad page, the fetch
    retry (503/429 retried, 404 not), the `__main__` guard, and the server's tab (top 10 in
    order, real numbers, slash-free ids, one bad row costs one row, a broken file costs only
    this tab, `/api/status` counts).
  - `tests/test_reddit_backups.py`: the backup ladder with canned replies. `list_problem()`
    (redirect/login wall, other subs, an older list, lost upvotes, the short-list proof), the
    JSON and RSS parsers, every ladder path (page ok; blocked → json; layout change → rss; short
    → json without a retry; all fail; all videos; `--method`; a short RSS list trusted only after
    the page saw it short; no page retry once it keeps failing), a whole `run()` with the browser
    stubbed (layout change → page skipped, no double count after the fresh-profile retry, the
    deadline and block messages once), the stuck-profile fallback, the
    `METHOD CHECK` line, and GitHub's side (stalest first, own stamps, the RSS check line, only
    a real top list saved, and that `python core/scrape_top.py` really runs `main()`).
- **`python3 tests/e2e_site.py [base_url]`** — 68 real-browser checks (~90 s): every tab shows
  all the API's posts with the right label, the GitHub tab (API's top 10 in GitHub's order,
  "top 10 of N", GitHub's star counts, read + Undo, keys 5/6, its 24 h stale notice), real upvotes on cards, opening ≠ reading, the
  "Done with X?" prompt, undo, keys, stale notices (News 36 h, Reddit 48 h), footer stamps,
  kept unread posts (the API response is edited to drop two: both stay under their label and
  in the counts; reading one removes it; the eye button shows it again; Undo still works after
  a data reload; "Mark these read" clears them; one that left 30+ days ago expires; a post the
  server moves between tabs shows once; no duplicates once back; a removed sub's posts go),
  phone layout (all 6 tabs in the bottom bar, on screen and tappable; header tucks and returns;
  a real CDP touch pull refreshes, a short one doesn't, offline says so; the today line counts
  a tick and Undo; streak math), desktop shows chips not the bar, no JS errors. Against the
  local dev server some steps are slow (uvicorn answers one `/api/data` at a time, ~0.7 s
  each, so parallel pages queue); the checks wait for data instead of fixed sleeps. Needs Playwright (use `/opt/homebrew/bin/python3` on the Mac; the
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
- `reddit_backup.yml` (every 3 h at :17): §2c. Python 3.10, `concurrency: reddit-backup`,
  timeout 20 min. Public repo, so the minutes are free.
- `daily_scrape.yml`: Python 3.10, `pip install -r requirements-scraper.txt`, runs the three
  GitHub-side feed scrapers (Reddit moved to `reddit_backup.yml` on 26 Sep 2026, so News never
  waits on Reddit), `git add -f data/`, commits "Automated daily data update", pushes with a
  3-try rebase loop, then prints `DATA PUSHED: N data files` (fleet-health greps it). Nothing new
  → `NO DATA CHANGES`. `workflow_dispatch` always runs.
  **Scraper failures (27 Sep 2026):** the scrape step runs all three with `set +e`, prints
  `scraper exits: ritholtz=R googlenews=G trung=T`, the commit step still pushes what the
  others wrote, and a LAST step (`Fail the run if a scraper failed`) prints
  `SCRAPERS FAILED: googlenews=1` and exits 1 — so a dead feed turns the run red (and, for
  News, the 09:00 retry re-runs because `data/googlenews/` wasn't committed).
- **Two crons + dedupe guard (don't "simplify" away):** `0 3 * * *` is the real run; `0 9 * * *`
  is a retry added after 2026-07-09, when GitHub never assigned a runner to the 03:00 job. A guard
  skips *scheduled* runs when **`data/googlenews/`** was already committed today (UTC). It checked
  all of `data/` until 26 Sep 2026, but `am_reads.yml` commits every morning and the Mac commits
  twice a day, so the retry never ran when News failed. Checkout uses `fetch-depth: 50` (the guard
  needs history); `concurrency: daily-scrape` (no cancel) serializes a late 03:00 against 09:00.
- `am_reads.yml`: ritholtz + trung only, commits only on change.
- `github_trending.yml` (every 6 h at :41): §2f. Python 3.10, `concurrency: github-trending`,
  timeout 10 min, commits `data/github_trending/` only on change, same 3-try rebase loop.

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
   `scrape_top.py`; if 429s grow, *widen* it or lower `--max-lists`, never raise it.
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
15. **Don't change the wrapper's log lines, `METHOD CHECK`, `REDDIT BACKUP` or `GITHUB REDDIT
    CHECK` without updating fleet-health** (§8) and the tests that pin them
    (`tests/test_robustness.py`, `tests/test_reddit_backups.py`).
16. **Every Reddit method must pass `list_problem()`** before anything is written. A new method
    goes into the ladder behind the same checks, never around them: a fetch that "works" but
    returns the wrong list is worse than keeping yesterday's file.

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
  Tailwind, no build step). 6 tabs with unread counts: header chips on wide screens, a
  glass **bottom tab bar** (`#tabbar`, icon + label + badge) on phones (<=700 px) where the chips
  are hidden; both navs render the same `data-tab` buttons (tests must click
  `[data-tab="x"]:visible`, the first match is the hidden one). Phones only: the header
  **tucks away while scrolling down** (`header.tucked`) and returns on scroll up, near the top,
  or a tab switch (`showHeader`); `body::before` keeps a strip behind the iPhone clock.
  **Pull down at the top to refresh** (touch handlers on `document`; only when scrollY <= 0 and
  the drag is down + mostly vertical, so card swipes are untouched): `loadData(false)` returns
  `'fresh' | 'offline' | 'failed'` (20 s cap); the toast says "Refreshed · N new", "nothing
  new", "You're offline. Showing the last saved copy." (sw.js tags its cached `/api/data` with
  `X-Offline-Copy: 1`) or "Couldn't refresh". **Today line** under the date: "N cleared today ·
  K-day streak" / "Clear one to keep your K-day streak" (K >= 2), from the synced read ticks'
  `readAt` per Eastern day (`countReadDays`, run per read-list change and in `setRead`, not per
  render: thousands of ticks). Progress row ("50 of 50 left · top 50 of
  534", "27 of 27 left · last 7 days") + Mark all read (with Undo); swipe left = read, right =
  favorite; search across tabs; text size + light/dark/auto; keys j/k/o/r/f/u(z), 1-6 = tabs; remembers tab
  and scroll; re-fetches when resumed after 20 min. **Opening a link must NOT mark it read** (the
  owner peeks without reading; only the tick / left swipe / `r` / Mark all read / the prompt's
  "Mark read" count). Opened-but-unread cards get a hollow dot + "Opened" tag (localStorage
  `dr_opened`, 21 days); coming back after 10+ s shows "Done with X? [Mark read]"; tap a blurb to
  expand; "New" tag = first seen on this device today (`dr_first_seen`; Monthly, Yearly and
  GitHub). **GitHub tab:** GitHub's top 10 under "Trending today on GitHub", meta
  "#1 · +2,608 stars today · 87.5k stars"; no kept-unread logic (a repo that leaves trending
  just goes). **Unread posts are kept
  until read** (the owner's call, 26 Sep 2026): the random part of the tier score reshuffles the
  top 50 on every scrape (measured: ~8 Monthly and ~3 Yearly posts swap out per run), so the page
  remembers every Monthly/Yearly post it has shown (localStorage `dr_kept`, per device). One that
  drops out while unread stays at the bottom of its tab under "Still unread from earlier lists ·
  N" with a "Mark these read" button, and counts in the badge and label ("top 47 of 534 + 3
  kept"). It leaves the list when read (read state syncs, so reading it on the phone clears it
  everywhere) and behaves like any read post: the eye button shows it, the tick or Undo brings it
  back. Storage rules (`trackKept`): an entry records `gone` = the first day it was missing;
  deleted 30 days after that (`KEEP_DAYS`, counted from leaving, not from first seen, because
  Yearly posts often sit in the list for a month), or 2 days after it was read
  (`READ_GRACE_DAYS`, so a reload right after marking read can't lose it before Undo), or at once
  when it's live in the OTHER tab (the server moves posts between Monthly and Yearly) or its sub
  is no longer in `/api/data`'s `reddit_subs`. Kept posts only appear once the cloud read list
  has loaded (or sync failed), so read posts never flash up as unread. **Warning cards:** News
  when `updated.news` is 36 h+ old; Monthly/Yearly when `updated.reddit` is 48 h+ old (the Mac
  stopped; lists may be older and show ranks); GitHub when `updated.github` is 24 h+ old (4
  missed runs). Footer: when AM Reads, News, Reddit and GitHub last landed. Sync write failures show a toast + "(offline)". Firebase layout:
  `sync_groups/{key}/favorites` + `read_posts`.
- `manifest.json` + `sw.js` — PWA; network-first service worker (cache `daily-reader-v2`, only
  the offline fallback; an offline `/api/data` copy carries `X-Offline-Copy: 1`).
- `server_assets/icon.png` — app icon.
- `core/reddit_common.py` — `SUBREDDITS`, tiers, freshness handshake (shared, stdlib only).
- `core/scrape_reddit_browser.py` — the real Reddit source (Mac mini).
- `mac/reddit-browser.sh` + `mac/com.jalal.reddit-browser.plist` — its launchd job.
- `core/scrape_top.py` — GitHub's Reddit backup (RSS → JSON, batched, every 3 h).
- `core/scrape_ritholtz.py`, `core/scrape_googlenews.py`, `core/scrape_trung.py` — the other feeds.
- `core/scrape_github_trending.py` — the GitHub tab (§2f).
- `vercel.json` — deploy config.
- `.github/workflows/reddit_backup.yml`, `daily_scrape.yml`, `am_reads.yml`,
  `github_trending.yml` — scrape + commit;
  `tests.yml` — pytest.
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
the Mac at 05:00 + 06:30) has five rows for this repo:

| Row | Probe | Red when |
|---|---|---|
| `reddit-scraper (daily data)` | GitHub run of `daily_scrape.yml` | no run in 36 h, or no `DATA PUSHED` / guard line |
| `reddit-browser (Mac 07:35/19:35 Reddit lists)` | last block of `~/Library/Logs/reddit-browser.log` | last `== … start` over 26 h old, or that block lacks `REDDIT PUSHED: N files` / `NO REDDIT CHANGES (scraper exit 0)` |
| `reddit-browser (live site: every Reddit list fresh)` | live `/api/status` | the OLDEST `reddit_lists[].checked` is over 36 h old (the third missed run in a row). Fleet converts these UTC `…Z` stamps to local time since 2026-09-26; before that they read 4–5 h too young |
| `reddit-browser (backup methods: page, json, rss all work)` | last block of the same log | the block lacks `METHOD CHECK: page ok · json ok · rss ok`: the Mac is running on a backup, or a backup stopped working. The rows above stay green in both cases |
| `reddit-backup (GitHub RSS every 3 h)` | GitHub run of `reddit_backup.yml` | no run in 8 h, or neither `GITHUB REDDIT CHECK: rss ok` nor `REDDIT BACKUP: refreshed <1+>` |

**Is it healthy right now?** (3 commands)
```bash
curl -s https://reddit-scraper-lyart.vercel.app/api/status | python3 -m json.tool | head -30
grep -E '^== |BROWSER SAVED|METHOD CHECK|REDDIT PUSHED|NO REDDIT|FAILED|ACTIVE' ~/Library/Logs/reddit-browser.log | tail -8
launchctl print gui/$(id -u)/com.jalal.reddit-browser | grep -E 'state|last exit'
```

**When something's wrong:**
- **Mac job didn't run** (no new `== … start`): the Mac was asleep/off at 07:35 or 19:35, or the
  job isn't loaded. `launchctl print …` (above); reload per §2b. Run it now with
  `launchctl kickstart gui/$(id -u)/com.jalal.reddit-browser`.
- **First step for anything Reddit:** from a scratch folder,
  `python3 ~/.local/share/reddit-browser/reddit-scraper/core/scrape_reddit_browser.py --probe --fresh-profile`
  shows which methods work right now (writes nothing). Don't run it in a loop: a burst of runs
  gets the Mac's IP rate-limited for a while (JSON 403, RSS 429), which looks like a block.
- **`METHOD CHECK: page FAILING`** with lists saved `via json`: the page layout changed. The site
  still has real upvotes; fix `READ_POSTS_JS` / `via_page` (compare with `--probe`).
  **`json FAILED`** / **`rss FAILED`**: that backup broke; the site is fine today, fix it before
  the day it's needed. Every list `via rss` = both page and JSON are down: ranks, no upvotes.
- **`the page failed 4 lists in a row` / `failed every method`**: Reddit is blocking this Mac
  (after the fresh profile too). Wait for the next run; GitHub's RSS backup (another IP) takes
  over lists that go 36 h stale. To look yourself add `--visible` to the probe. Never point it at
  a personal Chrome profile.
- **`profile won't open` / `fresh throwaway profile`** every run: the job's profile is damaged.
  `mv ~/.local/share/reddit-browser/profile ~/.local/share/reddit-browser/profile.bad`; the next
  run makes a new one (it only holds Reddit's cookie).
- **`playwright INSTALL FAILED`**: `/opt/homebrew/bin/python3 -m pip install --break-system-packages playwright`
  by hand and read its error.
- **`GITHUB REDDIT CHECK: rss FAILED`** (fleet row `reddit-backup`): GitHub's IPs lost RSS too.
  The Mac is unaffected; if it recurs for days, GitHub has no way into Reddit left, and the
  only cover for a dead Mac is the stale warning on the site.
- **`browser missing`**: handled automatically (it installs Chromium). If the install fails:
  `/opt/homebrew/bin/python3 -m playwright install chromium`.
- **`ANOTHER RUN IS ACTIVE`** on every run: a lock from a crashed run is taken over after 40 min
  automatically. If it persists: `ls -la ~/.local/share/reddit-browser/run.lock`.
- **`PUSH FAILED after 3 tries`**: GitHub was down or rejected the push. The next run redoes the
  whole list from a fresh reset; nothing to clean up.
- **Site shows "#3 this month" instead of upvotes on some cards**: those lists came from an RSS
  rung: the Mac's (`/api/status` → `via: rss`) or GitHub's (the Mac hasn't saved them in 36 h;
  `reddit_missing` and the oldest `saved` stamps say which). `checked` newer than `saved` = the
  Mac reaches the list but it is all videos, or short with no method proving it complete:
  nothing is broken.
- **`GIT SYNC FAILED` / `CLONE FAILED`**: GitHub unreachable (the next run retries; a deleted
  clone is re-cloned automatically).
- **A tab is suddenly empty**: check Vercel's runtime logs for `daily-reader` warnings (a broken
  CSV is logged there and costs only its own tab).
