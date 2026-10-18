"""Shared by scrape_top.py (GitHub, RSS fallback) and scrape_reddit_browser.py (Mac mini).

Stdlib only: the Mac runs the browser scraper on a Python that has Playwright but
not pandas.
"""
import json
import random
from datetime import datetime, timezone
from pathlib import Path

SUBREDDITS = [
    "dataisbeautiful", "todayilearned", "bestof",
    "getmotivated", "UnethicalLifeProTips", "LifeProTips",
    "UpliftingNews", "lifehacks", "Productivity",
    "PersonalFinance", "explainlikeimfive", "coolguides"
]

# Hard ceiling per tab for subs that would otherwise flood the feed (the owner's
# rule when adding r/coolguides, 18 Oct 2026: "strict rules so it's not way too
# much content"). server.py drops every post past the cap BEFORE the top-50 cut,
# so the page's quiet-sub refill (the reserve) can't sneak more in either.
# Keys are lowercase sub names. The scoring math below is untouched.
SUB_CAPS = {"coolguides": 2}
# ...and a floor: only posts with at least this many REAL upvotes (Reddit's own
# number; an RSS-backup row with no number never qualifies). On 18 Oct 2026 the
# month's best coolguides post had 128 upvotes, the year's ~6k: Monthly stays
# empty until a guide really takes off.
SUB_FLOORS = {"coolguides": 1000}

# Tiered priority for the made-up ORDERING scores (RSS/HTML fallbacks and the Mac
# browser). They decide the mix of subs in Monthly/Yearly; never shown as upvotes.
SUBREDDIT_TIERS = {
    # Tier 1: The Heavyweights (Highest priority)
    "bestof": (75000, 100000),
    "explainlikeimfive": (75000, 100000),
    "todayilearned": (75000, 100000),

    # Tier 2: High Signal
    "dataisbeautiful": (40000, 70000),
    "PersonalFinance": (40000, 70000),
    # Tier 2 so its best posts reliably make the top 50; SUB_CAPS + SUB_FLOORS
    # below keep it to 2 strong guides per tab (18 Oct 2026).
    "coolguides": (40000, 70000),

    # Tier 3: Default (Everything else)
    "default": (15000, 35000)
}


def tier_base(subreddit: str) -> int:
    lo, hi = SUBREDDIT_TIERS.get(subreddit, SUBREDDIT_TIERS["default"])
    return random.randint(lo, hi)


def tier_score(base: int, i: int) -> int:
    """Ordering score for the i-th post of a sub's top list. Same math as the
    RSS/HTML fallbacks in scrape_top.py: it interleaves the subs by tier and
    position so one giant sub can't fill the whole tab. Never displayed.
    Do NOT change this math without the owner's permission."""
    return int(base * (0.88 ** i)) + random.randint(100, 999)


# The Mac's real-browser scrape records when it saved each list. GitHub's RSS
# fallback leaves a list alone while it is fresher than this, so it never
# overwrites real upvotes with RSS's made-up ones.
BROWSER_META = Path("data/reddit_browser.json")
FRESH_HOURS = 36


def list_key(subreddit: str, time_filter: str) -> str:
    """Folder name under data/: r_<sub> for month, r_<sub>_yearly for year."""
    return f"r_{subreddit}{'_yearly' if time_filter == 'year' else ''}"


def load_meta(path: Path = BROWSER_META) -> dict:
    try:
        lists = json.loads(path.read_text()).get("lists", {})
    except (OSError, ValueError, AttributeError):
        return {}
    return lists if isinstance(lists, dict) else {}


def fresh_keys(meta: dict, now: datetime, hours: float = FRESH_HOURS) -> dict:
    """{list_key: age in hours} for lists the Mac saved within `hours`."""
    out = {}
    for key, stamp in (meta.items() if isinstance(meta, dict) else ()):
        try:
            then = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            age = (now - then).total_seconds() / 3600
        except (ValueError, TypeError):  # bad or timezone-less stamp = not fresh
            continue
        if 0 <= age < hours:
            out[key] = age
    return out


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
