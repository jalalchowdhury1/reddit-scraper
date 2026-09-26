"""Reddit top lists through a real (headless) browser on the Mac mini.

Why: Reddit blocks every plain request now. GitHub's IPs get 403/429, and even a
home IP gets a JavaScript challenge page on the JSON and HTML endpoints. A real
Chromium passes that challenge by itself after one warm-up page load, just like a
person's browser, and the new Reddit page carries everything as attributes on each
<shreddit-post>: real upvotes, comment count, title, link, and self-post text.
No login, no API key, no AI needed.

Backups, per list, when the page fails (each one checked for real on 26 Sep 2026):
  1. page  the new-Reddit page's <shreddit-post> elements (real upvotes + text)
  2. json  Reddit's own top.json, fetched with the same browser's cookies once its
           bot check is passed (real upvotes + text; without them it is 403)
  3. rss   the top-list RSS feed through the same browser (text, no upvotes)
Whatever comes back must pass list_problem() (right sub, right time window, upvotes
present, enough posts) or it isn't saved. A profile that won't open, or that
Reddit blocks 4 lists in a row, is swapped for a fresh throwaway one once.
old.reddit.com is no use: it sends logged-out visitors to a login page.

Runs at 07:35 + 19:35 from launchd (mac/reddit-browser.sh). Writes the same
data/r_<sub>[_yearly]/posts.csv files as scrape_top.py, plus
data/reddit_browser.json so GitHub's RSS fallback leaves fresh lists alone.

Stdlib + Playwright only (the Mac's /opt/homebrew/bin/python3 has no pandas).
usage: python3 core/scrape_reddit_browser.py [--profile DIR | --fresh-profile] [--only sub1,sub2]
                                            [--method page|json|rss] [--probe] [--visible]
  --probe   try EVERY method on each --only list (default LifeProTips), print what
            each one got, write nothing. Exit 1 if any method failed.
"""
import argparse
import asyncio
import csv
import json
import random
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent))
from reddit_common import SUBREDDITS, BROWSER_META, list_key, tier_base, tier_score, utc_now_iso

COLUMNS = ["id", "title", "selftext", "permalink", "score", "upvotes", "comments", "score_real"]
WANT = 50                # posts per list (same as the old JSON limit=50)
# A page with fewer posts than this is broken (challenge page, error page); keep
# the old file. A real list can be short: r/lifehacks had 7 posts for Sep 2026.
MIN_POSTS = 5
# No new list starts after this. One list can still take ~6 min in the worst case
# (every method slow or rate-limited), and the wrapper kills the run at 20 min.
RUN_DEADLINE_S = 12 * 60
# A top-of-the-month list holds posts from the last ~30 days, a yearly one the last
# ~365. Posts older than this (with slack) mean Reddit served some other list.
MAX_AGE_DAYS = {"month": 40, "year": 400}
METHODS = ("page", "json", "rss")
SHORT = "too short: "    # list_problem() prefix for a real list with few posts
DEFAULT_PROFILE = Path.home() / ".local/share/reddit-browser/profile"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

READ_POSTS_JS = """[...document.querySelectorAll('shreddit-post')].map(e => ({
  id: e.getAttribute('id') || '', score: e.getAttribute('score') || '',
  comments: e.getAttribute('comment-count') || '', title: e.getAttribute('post-title') || '',
  type: e.getAttribute('post-type') || '', link: e.getAttribute('permalink') || '',
  created: e.getAttribute('created-timestamp') || '', sub: e.getAttribute('subreddit-name') || '',
  body: (e.querySelector('[slot="text-body"]') || {}).innerText || ''}))"""


def as_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def epoch(value):
    """Seconds since 1970 from a number (JSON) or an ISO stamp (page, RSS); None if neither.
    The page writes "2026-09-09T06:46:14.641000+0000", which Python 3.10 won't parse."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    s = str(value or "").strip().replace("Z", "+00:00")
    if len(s) > 5 and s[-5] in "+-" and s[-4:].isdigit():
        s = f"{s[:-2]}:{s[-2:]}"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt.timestamp() if dt.tzinfo else None


def raw_from_json(data) -> tuple:
    """Reddit's top.json -> (page-shaped post dicts, complete). complete = Reddit
    said there is no next page (`after` is null): a short list is really that short."""
    listing = data.get("data") if isinstance(data, dict) else None
    if not isinstance(listing, dict) or not isinstance(listing.get("children"), list):
        raise ValueError("not a Reddit listing")
    raw = []
    for child in listing["children"]:
        d = child.get("data") if isinstance(child, dict) and child.get("kind") == "t3" else None
        if not isinstance(d, dict) or d.get("stickied"):
            continue
        raw.append({"id": d.get("name") or d.get("id") or "", "score": d.get("score", ""),
                    "comments": d.get("num_comments", ""), "title": d.get("title") or "",
                    "type": "video" if d.get("is_video") else ("text" if d.get("is_self") else "link"),
                    "link": d.get("permalink") or "", "body": d.get("selftext") or "",
                    "created": d.get("created_utc"), "sub": d.get("subreddit") or ""})
    return raw, listing.get("after") is None


class _PostText(HTMLParser):
    """Text inside the first <div class="md"> of an RSS entry (the self-post body;
    link posts have none). Stdlib only: the Mac's Python has no BeautifulSoup."""

    def __init__(self):
        super().__init__()
        self.depth, self.done, self.parts = 0, False, []

    def handle_starttag(self, tag, attrs):
        if self.depth:
            self.depth += tag == "div"
        elif not self.done and tag == "div" and "md" in (dict(attrs).get("class") or "").split():
            self.depth = 1

    def handle_endtag(self, tag):
        if self.depth and tag == "div":
            self.depth -= 1
            self.done = self.depth == 0

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)


def raw_from_rss(content: bytes) -> list:
    """Reddit's top-list Atom feed -> page-shaped post dicts. RSS has no upvotes."""
    ns = {"a": "http://www.w3.org/2005/Atom"}
    raw = []
    for entry in ET.fromstring(content).findall("a:entry", ns):
        link = entry.find("a:link", ns)
        cat = entry.find("a:category", ns)
        text = _PostText()
        text.feed(entry.findtext("a:content", "", ns))
        raw.append({"id": entry.findtext("a:id", "", ns), "score": "", "comments": "",
                    "title": entry.findtext("a:title", "", ns), "type": "",
                    "link": link.get("href", "") if link is not None else "",
                    "body": " ".join(" ".join(text.parts).split()),
                    "created": entry.findtext("a:published", "", ns),
                    "sub": cat.get("term", "") if cat is not None else ""})
    return raw


def url_is_list(url: str, sub: str, t: str) -> bool:
    """True if `url` (after any redirects) is still r/sub's top list for t. Reddit
    adds challenge parameters to the URL, so only the path and `t=` are compared."""
    u = urlparse(url)
    return (u.path.lower().startswith(f"/r/{sub.lower()}/top")
            and parse_qs(u.query).get("t", [""])[0] == t)


def list_problem(raw: list, sub: str, t: str, url: str = "", upvotes: bool = True,
                 complete: bool = False, now: float = None) -> str:
    """'' if `raw` looks like r/sub's real top list for t, else why not. Each check
    stops a failure that would otherwise be saved silently: a redirect to another
    page or a login wall, another sub's posts, an older list, a layout change that
    drops the upvotes, a challenge page with a handful of posts. A real list with
    few posts (r/lifehacks had 7 in Sep 2026) passes only if `complete` proves it."""
    if url and not url_is_list(url, sub, t):
        return f"landed on {urlparse(url).path or url[:60]}, not the top list"
    if not raw:
        return "no posts"
    n = len(raw)
    other = sum(1 for p in raw if p.get("sub") and str(p["sub"]).lower() != sub.lower())
    if other * 5 > n:
        return f"{other} of {n} posts are from other subs"
    oldest_ok = (now or time.time()) - MAX_AGE_DAYS[t] * 86400
    old = sum(1 for p in raw if (e := epoch(p.get("created"))) is not None and e < oldest_ok)
    if old * 5 > n:
        return f"{old} of {n} posts are older than a {t}"
    if upvotes:
        have = sum(as_int(p.get("score")) is not None for p in raw)
        if have * 2 < n:
            return f"{have} of {n} posts show upvotes (page layout changed?)"
    if n < MIN_POSTS and not complete:
        return f"{SHORT}{n} posts"
    return ""


def method_check_line(page_saved: int, tried: int, backups: dict) -> str:
    """Last line of a run. fleet-health's reddit-browser backups row greps
    "METHOD CHECK: page ok · json ok · rss ok": the page method saved at least half
    the lists AND both backups just fetched a real list. Anything else names what broke."""
    page = "ok" if tried and page_saved * 2 >= tried else "FAILING"
    parts = [f"page {page}"] + [f"{m} {'ok' if not p else 'FAILED'}" for m, p in backups.items()]
    why = [f"{m}: {p}" for m, p in backups.items() if p]
    return (f"METHOD CHECK: {' · '.join(parts)}  (page saved {page_saved} of {tried} lists"
            + ("; " + "; ".join(why) if why else "") + ")")


def rows_from_page(raw: list, subreddit: str) -> list:
    """Page objects -> CSV rows, in Reddit's own top order, one per post.

    `upvotes` = the real number from Reddit (what the site shows). `score` = the
    same tier ordering score the RSS fallback uses (so score_real=False: a reader
    that doesn't know `upvotes` shows the rank, never the made-up number), because real upvotes differ
    ~20x between subs: ordering by them made Monthly 46 of 50 r/todayilearned.
    Videos are skipped, like the old JSON path did (this is a reading list).
    """
    rows, seen = [], set()
    base = tier_base(subreddit)
    for p in raw:
        pid = str(p.get("id", "")).removeprefix("t3_").strip()
        title = " ".join(str(p.get("title", "")).split())
        if not pid or not title or pid in seen or p.get("type") == "video":
            continue
        seen.add(pid)
        link = str(p.get("link", ""))
        upvotes = as_int(p.get("score"))
        rows.append({
            "id": pid,
            "title": title,
            "selftext": str(p.get("body", "")).strip(),
            "permalink": link if link.startswith("http") else f"https://www.reddit.com{link}",
            "score": tier_score(base, len(rows)),
            "upvotes": upvotes if upvotes is not None else "",
            "comments": as_int(p.get("comments")) or 0,
            "score_real": False,  # `score` is the tier number; the real one is `upvotes`
        })
    return rows


def write_list(rows: list, key: str, root: Path = Path("data")) -> Path:
    folder = root / key
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "posts.csv"
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)
    return path


def update_meta(saved: dict, path: Path = BROWSER_META, checked: dict = None, via: dict = None):
    """Merge {list_key: iso time} into data/reddit_browser.json.

    lists   = when each list was last SAVED. GitHub's RSS backup skips those under 36 h.
    checked = when the Mac last reached each list's real page, saved or not. A real list
              can be too short to save (MIN_POSTS); this still proves the job reached it,
              so fleet-health grades `checked` and doesn't page over a quiet sub.
    via     = which method saved each list last (page, json or rss); /api/status shows it."""
    try:
        meta = json.loads(path.read_text())
    except (OSError, ValueError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}

    def merged(name, new):
        old = meta.get(name) if isinstance(meta.get(name), dict) else {}
        return dict(sorted({**old, **new}.items()))
    meta = {"note": "When the Mac mini's real browser last saved (lists) and last reached "
                    "(checked) each Reddit list, and how it read it (via: page, json or rss). "
                    "GitHub's RSS fallback skips lists saved in the last 36 h.",
            "updated": utc_now_iso(), "lists": merged("lists", saved),
            "checked": merged("checked", {**saved, **(checked or {})}),
            "via": merged("via", via or {})}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=1) + "\n")


async def warm_up(page):
    """A first look at reddit.com, like a person arriving. Reddit's JS bot check itself
    runs on the first subreddit page (the URL gets js_challenge=1); the browser passes
    it on its own while via_page waits for the posts."""
    await page.goto("https://www.reddit.com/", wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(6000)


async def via_page(page, sub: str, t: str) -> dict:
    """Method 1: the new-Reddit top page, scrolled like a person until ~50 posts show."""
    await page.goto(f"https://www.reddit.com/r/{sub}/top/?t={t}",
                    wait_until="domcontentloaded", timeout=45000)
    try:
        await page.wait_for_selector("shreddit-post", timeout=15000)
    except Exception:
        return {"raw": [], "url": page.url, "upvotes": True, "complete": False}
    # The page shows 25 and loads more as you scroll, like a person scrolling.
    last, still = 0, 0
    for _ in range(10):
        n = await page.evaluate("document.querySelectorAll('shreddit-post').length")
        if n >= WANT:
            break
        still = still + 1 if n == last else 0
        if still >= 3:
            break
        last = n
        await page.evaluate("(() => { const p = [...document.querySelectorAll('shreddit-post')].pop();"
                            " if (p) p.scrollIntoView({block: 'end'}); })()")
        await page.mouse.wheel(0, 2500 + random.randint(0, 1500))
        await page.wait_for_timeout(1200 + random.randint(0, 800))
    raw = (await page.evaluate(READ_POSTS_JS))[:WANT + 10]
    return {"raw": raw, "url": page.url, "upvotes": True, "complete": False}


async def fetch(page, url: str):
    """GET with the browser's own cookies (the solved challenge). Plain requests get 403.
    429 = "slow down": wait what Reddit asks (capped at 20 s) and try once more."""
    r = await page.context.request.get(url, timeout=20000)
    if r.status == 429:
        try:
            wait = min(20, max(3, int(float(r.headers.get("retry-after", 10)))))
        except ValueError:
            wait = 10
        await page.wait_for_timeout(wait * 1000)
        r = await page.context.request.get(url, timeout=20000)
    if r.status != 200:
        raise RuntimeError(f"HTTP {r.status}")
    return r


async def via_json(page, sub: str, t: str) -> dict:
    """Method 2: Reddit's top.json through the browser. Real upvotes and text, and
    it doesn't care how the page looks. raw_json=1 = titles without &amp; escapes.
    It needs the cookies Reddit's bot check hands out, and that check runs on the
    first subreddit page, not the home page (seen 26 Sep 2026: home page = 2 cookies
    and 403; after one list page = 14 cookies and 200). So on a 403, load the list
    page once and ask again."""
    url = f"https://www.reddit.com/r/{sub}/top.json?t={t}&limit={WANT}&raw_json=1"
    try:
        r = await fetch(page, url)
    except RuntimeError as e:
        if "HTTP 403" not in str(e):
            raise
        await page.goto(f"https://www.reddit.com/r/{sub}/top/?t={t}", wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(5000)
        r = await fetch(page, url)
    raw, complete = raw_from_json(await r.json())
    return {"raw": raw, "url": r.url, "upvotes": True, "complete": complete}


async def via_rss(page, sub: str, t: str) -> dict:
    """Method 3: the top-list RSS feed through the browser. Real order and text, no
    upvotes (the site then shows each post's rank). Asked for 50: fewer MAY mean
    that's all, but a broken feed looks the same, so read_one trusts a short RSS
    list only when the page or JSON also saw that list short."""
    r = await fetch(page, f"https://www.reddit.com/r/{sub}/top/.rss?t={t}&limit={WANT}")
    raw = raw_from_rss(await r.body())
    return {"raw": raw, "url": r.url, "upvotes": False, "complete": len(raw) < WANT}


READERS = {"page": via_page, "json": via_json, "rss": via_rss}


async def try_method(page, method: str, sub: str, t: str, complete_ok: bool = True) -> tuple:
    """(got, problem). problem '' = got["raw"] passed list_problem().
    complete_ok=False ignores the method's "that's the whole list" claim."""
    try:
        got = await READERS[method](page, sub, t)
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:100]}"
    return got, list_problem(got["raw"], sub, t, got["url"], got["upvotes"],
                             got["complete"] and complete_ok)


def install_browser() -> bool:
    """A Playwright upgrade (brew/pip) can leave its browser missing: download
    it once, like `python3 -m playwright install chromium`, then carry on."""
    import subprocess
    print("  🔧 browser missing: running `playwright install chromium`")
    r = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                       capture_output=True, text=True, timeout=600)
    print("  🔧 install " + ("ok" if r.returncode == 0 else f"failed: {r.stderr.strip()[-200:]}"))
    return r.returncode == 0


def clear_profile_locks(profile: Path):
    """A run killed mid-scrape leaves Chromium's Singleton* links behind, and the next
    launch refuses the profile as "already in use"."""
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            (profile / name).unlink()
        except OSError:
            pass


async def open_browser(p, profile, visible: bool) -> tuple:
    """(context, throwaway dir or None). The saved profile keeps Reddit's cookie between
    runs; if it won't open (a lock from a killed run, a corrupt profile) clear its locks
    and try once more, then use a fresh throwaway profile so the run still happens.
    profile=None goes straight to a throwaway one."""
    kwargs = dict(headless=not visible, viewport={"width": 1280, "height": 900},
                  locale="en-US", timezone_id="America/New_York", user_agent=UA)

    async def launch(path):
        try:
            return await p.chromium.launch_persistent_context(str(path), **kwargs)
        except Exception as e:
            if "Executable doesn't exist" not in str(e) or not install_browser():
                raise
            return await p.chromium.launch_persistent_context(str(path), **kwargs)

    if profile is not None:
        for attempt in (1, 2):
            try:
                profile.mkdir(parents=True, exist_ok=True)
                return await launch(profile), None
            except Exception as e:
                print(f"  ⚠️ profile won't open (try {attempt}): {type(e).__name__}: {str(e)[:120]}")
                clear_profile_locks(profile)
    tmp = Path(tempfile.mkdtemp(prefix="reddit-browser-"))
    print("  🆕 using a fresh throwaway profile (new cookies)")
    try:
        return await launch(tmp), tmp
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


async def new_session(p, profile, visible: bool) -> tuple:
    ctx, tmp = await open_browser(p, profile, visible)
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    try:
        await warm_up(page)
    except Exception as e:  # each list warms up again on its own if it needs to
        print(f"  ⚠️ warm-up: {type(e).__name__}: {str(e)[:120]}")
    return ctx, tmp, page


async def close_session(ctx, tmp):
    try:
        await ctx.close()
    except Exception as e:
        print(f"  ⚠️ browser close: {type(e).__name__}")
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)


async def read_one(page, sub: str, t: str, methods, retry_page: bool = True) -> dict:
    """Try each method in turn until one passes list_problem(). Returns
    method (None = all failed), rows, tries (what failed, in order), reached (Reddit
    served the real list at least once, maybe just too short) and page_blocked (the
    page method got no real list at all: the sign of a blocked browser).
    retry_page=False skips the page's second try: when it has failed list after
    list, the retry only burns the time the backups need."""
    out = {"method": None, "rows": [], "tries": [], "reached": False, "page_blocked": False}
    short_seen = False  # page or JSON saw this list real but short: a short RSS list is believable
    for method in methods:
        for attempt in ((1, 2) if method == "page" and retry_page else (1,)):
            if attempt == 2:  # challenge page, slow load or hiccup: warm up again, retry once
                try:
                    await warm_up(page)
                except Exception:
                    pass
            got, problem = await try_method(page, method, sub, t, complete_ok=method != "rss" or short_seen)
            if not problem or problem.startswith(SHORT):
                break
        real = not problem or problem.startswith(SHORT)
        short_seen = short_seen or problem.startswith(SHORT)
        out["reached"] = out["reached"] or real
        out["page_blocked"] = out["page_blocked"] or (method == "page" and not real)
        if not problem:
            rows = rows_from_page(got["raw"], sub)
            if rows:
                out.update(method=method, rows=rows)
                return out
            problem = f"{len(got['raw'])} posts, none readable (all videos?)"
        out["tries"].append(f"{method}: {problem}")
    return out


async def run(profile, subs: list, visible: bool, methods=METHODS) -> dict:
    from playwright.async_api import async_playwright  # lazy: tests import this file without it

    saved, failed, via = {}, [], {}
    deadline = time.monotonic() + RUN_DEADLINE_S
    queue = [(sub, t) for sub in subs for t in ("month", "year")]
    async with async_playwright() as p:
        ctx, tmp, page = await new_session(p, profile, visible)
        try:
            misses, page_misses, fresh_tried = 0, 0, profile is None
            stop, use = "", methods  # stop: "deadline" or "blocked"
            for sub, t in queue:  # grows once if a fresh profile retries the misses
                key = list_key(sub, t)
                if not stop and time.monotonic() > deadline:
                    stop = "deadline"
                    print(f"⏱️ {RUN_DEADLINE_S // 60}-min limit: stopping before {key}")
                if stop:
                    if key not in failed and key not in saved:
                        failed.append(key)
                    continue
                t0 = time.monotonic()
                # The page failed 4 lists in a row even on a fresh profile: stop trying
                # it this run, so the backups get the time (a layout change costs
                # ~50 s a list in page timeouts, and 26 lists would miss the deadline).
                if use is methods and fresh_tried and page_misses >= 4 and len(methods) > 1:
                    use = tuple(m for m in methods if m != "page")
                    print(f"⏭️ the page keeps failing: {', '.join(use)} only for the rest of this run")
                r = await read_one(page, sub, t, use, retry_page=page_misses < 2)
                method, rows = r["method"], r["rows"]
                if "page" in use:
                    page_misses = page_misses + 1 if r["page_blocked"] else 0
                if method:
                    for note in r["tries"]:
                        print(f"  ↪ {key}: {note}")
                    write_list(rows, key)
                    saved[key], via[key] = utc_now_iso(), method
                    update_meta({key: saved[key]}, via={key: method})  # stamp each list now: a killed run keeps its stamps
                    failed = [k for k in failed if k != key]
                    misses = 0
                    with_text = sum(bool(x["selftext"]) for x in rows)
                    print(f"  ✅ {key}: {len(rows)} posts, {with_text} with text, top "
                          f"{rows[0]['upvotes'] or '?'} upvotes{'' if method == 'page' else ' via ' + method} "
                          f"({time.monotonic() - t0:.1f}s)")
                else:
                    if r["reached"]:  # Reddit served the real list (a challenge page has no posts), just a short one
                        update_meta({}, checked={key: utc_now_iso()})
                    if key not in failed and key not in saved:  # saved via RSS before a fresh-profile retry
                        failed.append(key)
                    misses += 1
                    print(f"  ⚠️ {key}: old file kept. " + "; ".join(r["tries"]))
                # Blocked? One fresh throwaway profile (new cookies) before giving up.
                # It retries the lists that failed or only got RSS (no upvotes).
                if page_misses >= 4 and not fresh_tried:
                    fresh_tried, page_misses, misses = True, 0, 0
                    print("🔄 the page failed 4 lists in a row: switching to a fresh throwaway profile")
                    await close_session(ctx, tmp)
                    ctx, tmp, page = await new_session(p, None, visible)
                    done = queue[:queue.index((sub, t)) + 1]
                    queue.extend(x for x in done if list_key(*x) in failed or via.get(list_key(*x)) == "rss")
                elif misses >= 4:
                    print("🛑 4 lists in a row failed every method: Reddit is probably blocking this Mac. Stopping.")
                    stop = "blocked"
                await page.wait_for_timeout(random.randint(3000, 7000))  # human pace
            # Prove the backups still work every run, so a dead one shows up on the
            # fleet board before the day it's needed.
            check_sub = subs[0]
            backups = {}
            for m in ("json", "rss"):
                if stop == "blocked" or time.monotonic() > deadline + 120:  # stay inside the wrapper's 20 min
                    backups[m] = "not checked (Reddit blocked this run)" if stop == "blocked" else "not checked (out of time)"
                    continue
                got, problem = await try_method(page, m, check_sub, "month")
                backups[m] = problem if not problem.startswith(SHORT) else ""
            page_saved = sum(1 for m in via.values() if m == "page")
            print(method_check_line(page_saved, len(set(saved) | set(failed)), backups))
        finally:
            await close_session(ctx, tmp)
    return {"saved": saved, "failed": failed, "via": via}


async def probe(profile, subs: list, visible: bool) -> bool:
    """Every method on every list, nothing written. True if all of them worked."""
    from playwright.async_api import async_playwright

    ok = True
    async with async_playwright() as p:
        ctx, tmp, page = await new_session(p, profile, visible)
        try:
            for sub in subs:
                for t in ("month", "year"):
                    for m in METHODS:
                        got, problem = await try_method(page, m, sub, t)
                        raw = got["raw"] if got else []
                        ups = sum(as_int(x.get("score")) is not None for x in raw)
                        ok = ok and not problem
                        print(f"  {'✅' if not problem else '❌'} {list_key(sub, t)} via {m}: "
                              f"{len(raw)} posts, {ups} with upvotes, "
                              f"{sum(bool(x.get('body')) for x in raw)} with text"
                              + (f"  PROBLEM: {problem}" if problem else ""))
                        await page.wait_for_timeout(random.randint(1500, 3000))
        finally:
            await close_session(ctx, tmp)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", type=Path, default=DEFAULT_PROFILE,
                    help="browser profile just for this job (keeps Reddit's cookie)")
    ap.add_argument("--fresh-profile", action="store_true", help="use a throwaway profile instead")
    ap.add_argument("--only", default="", help="comma list of subreddits (default: all)")
    ap.add_argument("--method", choices=METHODS, help="use only this method (to test a backup)")
    ap.add_argument("--probe", action="store_true", help="try every method, write nothing")
    ap.add_argument("--visible", action="store_true", help="show the browser window")
    a = ap.parse_args()
    profile = None if a.fresh_profile else a.profile
    if a.probe:
        subs = [s for s in a.only.split(",") if s] or ["LifeProTips"]
        print(f"🔎 Reddit method probe: {', '.join(subs)} x month/year x {', '.join(METHODS)}  ({utc_now_iso()})")
        sys.exit(0 if asyncio.run(probe(profile, subs, a.visible)) else 1)
    subs = [s for s in a.only.split(",") if s] or SUBREDDITS
    print("=" * 50)
    print(f"🖥️ Reddit via real browser: {len(subs)} subs x month/year  ({utc_now_iso()})")
    print("=" * 50)
    result = asyncio.run(run(profile, subs, a.visible, (a.method,) if a.method else METHODS))
    total = len(set(result["saved"]) | set(result["failed"]))
    print(f"BROWSER SAVED: {len(result['saved'])} of {total} lists"
          + (f" (kept old: {', '.join(result['failed'])})" if result["failed"] else ""))
    sys.exit(0 if result["saved"] else 1)


if __name__ == "__main__":
    main()
