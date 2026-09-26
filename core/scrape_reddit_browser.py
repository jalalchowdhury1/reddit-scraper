"""Reddit top lists through a real (headless) browser on the Mac mini.

Why: Reddit blocks every plain request now. GitHub's IPs get 403/429, and even a
home IP gets a JavaScript challenge page on the JSON and HTML endpoints. A real
Chromium passes that challenge by itself after one warm-up page load, just like a
person's browser, and the new Reddit page carries everything as attributes on each
<shreddit-post>: real upvotes, comment count, title, link, and self-post text.
No login, no API key, no AI needed.

Runs daily from launchd (mac/reddit-browser.sh). Writes the same
data/r_<sub>[_yearly]/posts.csv files as scrape_top.py, plus
data/reddit_browser.json so GitHub's RSS fallback leaves fresh lists alone.

Stdlib + Playwright only (the Mac's /opt/homebrew/bin/python3 has no pandas).
usage: python3 core/scrape_reddit_browser.py [--profile DIR] [--only sub1,sub2] [--visible]
"""
import argparse
import asyncio
import csv
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from reddit_common import SUBREDDITS, BROWSER_META, list_key, tier_base, tier_score, utc_now_iso

COLUMNS = ["id", "title", "selftext", "permalink", "score", "upvotes", "comments", "score_real"]
WANT = 50                # posts per list (same as the old JSON limit=50)
MIN_POSTS = 10           # page showed fewer posts than this = broken page; keep the old file
RUN_DEADLINE_S = 15 * 60
DEFAULT_PROFILE = Path.home() / ".local/share/reddit-browser/profile"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

READ_POSTS_JS = """[...document.querySelectorAll('shreddit-post')].map(e => ({
  id: e.getAttribute('id') || '', score: e.getAttribute('score') || '',
  comments: e.getAttribute('comment-count') || '', title: e.getAttribute('post-title') || '',
  type: e.getAttribute('post-type') || '', link: e.getAttribute('permalink') || '',
  body: (e.querySelector('[slot="text-body"]') || {}).innerText || ''}))"""


def as_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


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


def update_meta(saved: dict, path: Path = BROWSER_META):
    """Merge {list_key: iso time} into data/reddit_browser.json."""
    try:
        meta = json.loads(path.read_text())
    except (OSError, ValueError):
        meta = {}
    lists = meta.get("lists", {}) if isinstance(meta.get("lists"), dict) else {}
    lists.update(saved)
    meta = {"note": "When the Mac mini's real browser last saved each Reddit list. "
                    "GitHub's RSS fallback skips lists saved in the last 36 h.",
            "updated": utc_now_iso(), "lists": dict(sorted(lists.items()))}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=1) + "\n")


async def warm_up(page):
    """First visit gets Reddit's JS challenge; the browser solves it on its own."""
    await page.goto("https://www.reddit.com/", wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(6000)


async def read_list(page, sub: str, t: str) -> list:
    await page.goto(f"https://www.reddit.com/r/{sub}/top/?t={t}",
                    wait_until="domcontentloaded", timeout=45000)
    try:
        await page.wait_for_selector("shreddit-post", timeout=15000)
    except Exception:
        return []
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
    return (await page.evaluate(READ_POSTS_JS))[:WANT + 10]


async def run(profile: Path, subs: list, visible: bool) -> dict:
    from playwright.async_api import async_playwright  # lazy: tests import this file without it

    saved, failed = {}, []
    deadline = time.monotonic() + RUN_DEADLINE_S
    profile.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(profile), headless=not visible, viewport={"width": 1280, "height": 900},
            locale="en-US", timezone_id="America/New_York", user_agent=UA)
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            try:
                await warm_up(page)
            except Exception as e:  # each list warms up again on its own if it needs to
                print(f"  ⚠️ warm-up: {type(e).__name__}: {str(e)[:120]}")
            misses_in_a_row = 0
            for sub in subs:
                for t in ("month", "year"):
                    key = list_key(sub, t)
                    if time.monotonic() > deadline:
                        print(f"⏱️ {RUN_DEADLINE_S // 60}-min limit: stopping before {key}")
                        failed.append(key)
                        continue
                    t0 = time.monotonic()
                    # Health = posts on the page, not rows kept: r/lifehacks is mostly
                    # videos, so 50 posts on the page can leave only 6 readable rows.
                    raw = []
                    for attempt in (1, 2):  # challenge page, slow load or hiccup: warm up again, retry once
                        try:
                            if attempt == 2:
                                await warm_up(page)
                            raw = await read_list(page, sub, t)
                        except Exception as e:
                            print(f"  ❌ {key} (try {attempt}): {type(e).__name__}: {str(e)[:120]}")
                            raw = []
                        if len(raw) >= MIN_POSTS:
                            break
                    rows = rows_from_page(raw, sub)
                    if len(raw) >= MIN_POSTS and rows:
                        write_list(rows, key)
                        saved[key] = utc_now_iso()
                        update_meta({key: saved[key]})  # stamp each list now: a killed run keeps its stamps
                        misses_in_a_row = 0
                        with_text = sum(bool(r["selftext"]) for r in rows)
                        print(f"  ✅ {key}: {len(rows)} posts ({len(raw) - len(rows)} videos/dupes skipped), "
                              f"{with_text} with text, top {rows[0]['upvotes'] or '?'} upvotes "
                              f"({time.monotonic() - t0:.1f}s)")
                    else:
                        failed.append(key)
                        misses_in_a_row += 1
                        print(f"  ⚠️ {key}: page showed {len(raw)} posts ({len(rows)} readable), old file kept")
                        if misses_in_a_row >= 4:
                            print("🛑 4 lists in a row failed: Reddit is probably blocking this browser. Stopping.")
                            deadline = 0
                    await page.wait_for_timeout(random.randint(3000, 7000))  # human pace
        finally:
            try:
                await ctx.close()
            except Exception as e:
                print(f"  ⚠️ browser close: {type(e).__name__}")
    return {"saved": saved, "failed": failed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", type=Path, default=DEFAULT_PROFILE,
                    help="throwaway browser profile just for this job (keeps Reddit's cookie)")
    ap.add_argument("--only", default="", help="comma list of subreddits (default: all)")
    ap.add_argument("--visible", action="store_true", help="show the browser window")
    a = ap.parse_args()
    subs = [s for s in a.only.split(",") if s] or SUBREDDITS
    print("=" * 50)
    print(f"🖥️ Reddit via real browser: {len(subs)} subs x month/year  ({utc_now_iso()})")
    print("=" * 50)
    result = asyncio.run(run(a.profile, subs, a.visible))
    total = len(result["saved"]) + len(result["failed"])
    print(f"BROWSER SAVED: {len(result['saved'])} of {total} lists"
          + (f" (kept old: {', '.join(result['failed'])})" if result["failed"] else ""))
    sys.exit(0 if result["saved"] else 1)


if __name__ == "__main__":
    main()
