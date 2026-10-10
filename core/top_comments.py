"""Each Reddit post's top comment, for the cards (10 Oct 2026).

On TIL / ELI5 / LPT the best part is often the top comment, so the card shows it
and you don't have to open the post. The Mac mini's browser job reads them AFTER
it has saved the lists (core/scrape_reddit_browser.py), through the same browser
and cookies, one post at a time at a person's pace:

  GET <permalink>.json?sort=top&limit=10&depth=1&raw_json=1

Cached in data/reddit_comments.json, so each post costs ONE request, ever: a run
only asks about posts it hasn't seen (best tier score first = the ones the site
shows), at most MAX_PER_RUN of them, inside BUDGET_S, and stops after 3 failures
in a row (Reddit slowing us down must never cost the next run its lists). Posts
that leave every list are dropped from the cache. A post with no usable comment
yet is asked again after EMPTY_RETRY_DAYS.

Stdlib only (the Mac's python3 has Playwright but no pandas).
"""
import csv
import json
import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

COMMENTS_FILE = Path("data/reddit_comments.json")
MAX_PER_RUN = 40   # 10 Oct first fill: Reddit 429s after ~100 in a burst, and the lists ran just before
BUDGET_S = 4 * 60
EMPTY_RETRY_DAYS = 2
MAX_CHARS = 400
SKIP_AUTHORS = {"automoderator"}
GONE = re.compile(r"^\[\s*(deleted|removed( by reddit)?)\s*\]$", re.I)   # incl. admin "[ Removed by Reddit ]"


def clean_body(text: str, limit: int = MAX_CHARS) -> str:
    """Reddit markdown -> one plain line: links keep their text, no ** / quotes, cut at a word."""
    t = re.sub(r">!.*?!<", "[spoiler]", str(text or ""), flags=re.S)       # never reveal a spoiler on the card
    t = re.sub(r"!\[(gif|img)\]\([^)]*\)", lambda m: "[GIF]" if m.group(1) == "gif" else "[image]", t)   # media/emotes
    t = re.sub(r"\[([^\]]+)\]\((?:[^()]|\([^)]*\))*\)", r"\1", t)   # [text](url) -> text
    t = re.sub(r"(\*\*|__|~~|\^)", "", t)
    t = re.sub(r"(?m)^\s*(&gt;|>)+\s?", "", t)          # quoted lines
    t = re.sub(r"(?m)^\s*#+\s*", "", t)                 # headings
    t = re.sub(r"(?m)^\s*[*+-]\s+", "", t)              # bullets
    t = re.sub(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])", r"\1", t)   # *italics*
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
    return t


def pick_top(listing) -> dict:
    """[post listing, comment listing] -> {"body", "ups"} of the first real comment
    (Reddit's top order), skipping stickied/mod/AutoModerator and deleted ones. {} if none."""
    try:
        children = listing[1]["data"]["children"]
    except (IndexError, KeyError, TypeError):
        raise ValueError("not a comment listing")
    for c in children:
        d = c.get("data") or {}
        if c.get("kind") != "t1" or d.get("stickied") or d.get("distinguished") == "moderator":
            continue
        if str(d.get("author", "")).lower() in SKIP_AUTHORS:
            continue
        body = clean_body(d.get("body", ""))
        if not body or GONE.match(body):
            continue
        ups = d.get("ups", d.get("score"))
        # Reddit says 1 while a new comment's score is hidden: that's not a real number.
        real = isinstance(ups, int) and not isinstance(ups, bool) and not d.get("score_hidden")
        return {"body": body, "ups": ups if real else None}
    return {}


def load_cache(path: Path = COMMENTS_FILE) -> dict:
    try:
        posts = json.loads(path.read_text()).get("posts", {})
    except (OSError, ValueError, AttributeError):
        return {}
    return posts if isinstance(posts, dict) else {}


def save_cache(posts: dict, path: Path = COMMENTS_FILE):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "note": "Each Reddit post's top comment, read by the Mac mini's browser job "
                "(core/top_comments.py). body '' = no usable comment yet.",
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "posts": dict(sorted(posts.items()))}, indent=1, ensure_ascii=False) + "\n")
    tmp.replace(path)


def candidates(root: Path = Path("data"), subs=None) -> list:
    """[(id, permalink)] for every post in the saved lists, best tier score first
    (the server orders the tabs by that score, so these are the ones on screen).
    Posts with 0 comments are left out."""
    rows = {}
    for f in sorted(root.glob("r_*/posts.csv")):
        sub = f.parent.name[2:].removesuffix("_yearly")
        if subs is not None and sub not in subs:
            continue
        try:
            with f.open(newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    pid, link = str(r.get("id", "")).strip(), str(r.get("permalink", "")).strip()
                    if not pid or "/comments/" not in link or str(r.get("comments", "")).strip() == "0":
                        continue
                    try:
                        score = float(r.get("score") or 0)
                    except ValueError:
                        score = 0
                    if pid not in rows or score > rows[pid][0]:
                        rows[pid] = (score, link if link.startswith("http") else "https://www.reddit.com" + link)
        except (OSError, csv.Error):
            continue
    return [(pid, link) for pid, (_, link) in sorted(rows.items(), key=lambda kv: -kv[1][0])]


def due(entry, now: datetime) -> bool:
    """True when a post still needs asking: never asked, or asked, empty, and EMPTY_RETRY_DAYS old."""
    if not isinstance(entry, dict):
        return True
    if entry.get("body"):
        return False
    try:
        at = datetime.fromisoformat(str(entry.get("at", "")).replace("Z", "+00:00"))
    except ValueError:
        return True
    return now - at >= timedelta(days=EMPTY_RETRY_DAYS)


def comments_line(stats: dict) -> str:
    """The one log line: TOP COMMENTS: 41 new, 3 none yet, 0 failed (210 cached, 12 left)."""
    line = (f"TOP COMMENTS: {stats['new']} new, {stats['empty']} none yet, {stats['failed']} failed "
            f"({stats['cached']} cached, {stats['left']} left)")
    return line + (f" STOPPED: {stats['stopped']}" if stats.get("stopped") else "")


async def fetch_top_comments(page, fetch, root: Path = Path("data"), subs=None,
                             max_posts: int = MAX_PER_RUN, budget_s: float = BUDGET_S,
                             pace=(3000, 5000)) -> dict:
    """Ask Reddit for the top comment of up to max_posts uncached posts. `fetch` =
    the scraper's fetch(page, url) (browser cookies, one 429 wait). Writes the cache
    after every post, so a run killed midway keeps what it got."""
    path = root / COMMENTS_FILE.name
    cache = load_cache(path)
    # Prune against EVERY saved list, so an --only run can't drop the other subs' comments
    # (and a mistyped sub can't empty the cache).
    live = {pid for pid, _ in candidates(root)}
    cache = {k: v for k, v in cache.items() if k in live}   # posts that left every list go
    todo = candidates(root, subs)
    now = datetime.now(timezone.utc)
    queue = [(pid, link) for pid, link in todo if due(cache.get(pid), now)]
    stats = {"new": 0, "empty": 0, "failed": 0, "stopped": ""}
    deadline, fails = time.monotonic() + budget_s, 0
    asked = 0
    for pid, link in queue:
        if asked >= max_posts:
            break
        if time.monotonic() > deadline:
            stats["stopped"] = "time budget"
            break
        asked += 1
        url = link.split("?")[0].rstrip("/") + ".json?sort=top&limit=10&depth=1&raw_json=1"
        try:
            r = await fetch(page, url)
            top = pick_top(await r.json())
        except Exception as e:
            stats["failed"] += 1
            # A gone post (404) or a page that isn't a comment listing is THAT post's problem:
            # cache the miss like an empty one (asked again in EMPTY_RETRY_DAYS), so it can't sit
            # at the top of every run. 403/429/timeouts mean Reddit is pushing back: never cached
            # (that would hide the best, most-visible posts' comments for days), and 3 in a row
            # stop the step.
            post_problem = "HTTP 404" in str(e) or isinstance(e, ValueError)
            if post_problem:
                cache[pid] = {"body": "", "failed": f"{type(e).__name__}: {str(e)[:60]}",
                              "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
                save_cache(cache, path)
            fails = fails if post_problem else fails + 1
            if fails >= 3:
                stats["stopped"] = f"3 failures in a row ({type(e).__name__}: {str(e)[:60]})"
                break
            continue
        fails = 0
        cache[pid] = {**top, "body": top.get("body", ""), "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        stats["new" if top else "empty"] += 1
        save_cache(cache, path)
        await page.wait_for_timeout(random.randint(*pace))
    save_cache(cache, path)
    stats["cached"] = sum(1 for v in cache.values() if isinstance(v, dict) and v.get("body"))
    stats["left"] = sum(1 for pid, _ in todo if due(cache.get(pid), datetime.now(timezone.utc)))
    return stats
