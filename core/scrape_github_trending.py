"""
GitHub Trending scraper
=======================
Reads https://github.com/trending (today, all languages) and saves every repo on
it, in GitHub's own order, to data/github_trending/repos.csv. The site shows the
top 10 (server.py GITHUB_TOP).

There is no official trending API, so this parses the page. Its layout is stable
(one <article class="Box-row"> per repo), but if it changes, list_problem()
refuses the new list and yesterday's file stays: a wrong list is worse than an
old one. Runs on GitHub Actions (github_trending.yml); GitHub doesn't block its
own runners the way Reddit does.

    python core/scrape_github_trending.py          # writes data/github_trending/repos.csv
"""
import os
import re
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import requests
from bs4 import BeautifulSoup

URL = "https://github.com/trending"
OUTPUT_DIR = "data/github_trending"
OUTPUT_FILE = f"{OUTPUT_DIR}/repos.csv"
MIN_REPOS = 5           # today's page lists ~8-25; under 5 = the layout broke
SHOW = 10               # the site shows 10 (server.py GITHUB_TOP); a short day is topped up from weekly
WEEKLY_URL = URL + "?since=weekly"
HEADERS = {"User-Agent": "Mozilla/5.0 (DailyReader; +https://reddit-scraper-lyart.vercel.app)"}
COLUMNS = ["rank", "repo", "url", "description", "language", "stars", "forks", "stars_today", "scraped_at"]


def to_int(text) -> int | None:
    """'87,484' -> 87484; '2,608 stars today' -> 2608; junk -> None."""
    m = re.search(r"\d[\d,]*", str(text or ""))
    return int(m.group(0).replace(",", "")) if m else None


def parse_trending(html: str) -> list:
    """Every repo row on the trending page, in page order, as dicts."""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for art in soup.select("article.Box-row"):
        link = art.select_one("h2 a[href]")
        if not link:
            continue
        repo = link["href"].strip("/")
        if repo.count("/") != 1:   # not owner/name: a sponsor block or a layout change
            continue
        desc = art.select_one("p")
        lang = art.select_one('[itemprop="programmingLanguage"]')
        stars = art.select_one('a[href$="/stargazers"]')
        forks = art.select_one('a[href$="/forks"]')
        today = next((s for s in art.select("span") if re.search(r"stars? (today|this week|this month)", s.get_text())), None)
        rows.append({
            "rank": len(rows) + 1,
            "repo": repo,
            "url": f"https://github.com/{repo}",
            "description": " ".join(desc.get_text().split()) if desc else "",
            "language": lang.get_text(strip=True) if lang else "",
            "stars": to_int(stars.get_text()) if stars else None,
            "forks": to_int(forks.get_text()) if forks else None,
            "stars_today": to_int(today.get_text()) if today else None,
        })
    return rows


def list_problem(rows: list) -> str:
    """Why this list must NOT be saved, or '' when it looks like the real page."""
    if len(rows) < MIN_REPOS:
        return f"only {len(rows)} repos (need {MIN_REPOS}): the page layout probably changed"
    if len({r["repo"] for r in rows}) != len(rows):
        return "the same repo twice"
    if sum(r["stars"] is None for r in rows) > len(rows) // 2 or sum(r["stars_today"] is None for r in rows) > len(rows) // 2:
        return "star counts missing: the page layout probably changed"
    return ""


def fetch(url: str = URL, tries: int = 3, waits=(5, 20)) -> str:
    """The page's HTML. 5xx/429/network errors are retried; other 4xx fail at once."""
    for i in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code < 400:
                return r.text
            if r.status_code != 429 and r.status_code < 500:
                r.raise_for_status()
            err = f"HTTP {r.status_code}"
        except requests.HTTPError:
            raise
        except requests.RequestException as e:
            err = str(e)
        if i < tries - 1:
            print(f"  try {i + 1} failed ({err}); waiting {waits[min(i, len(waits) - 1)]}s")
            time.sleep(waits[min(i, len(waits) - 1)])
    raise RuntimeError(f"{url} failed {tries} times: {err}")


def save(rows: list, path: str = OUTPUT_FILE) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    df = pd.DataFrame([{**r, "scraped_at": now} for r in rows], columns=COLUMNS)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)


def top_up(rows: list, weekly: list, want: int = SHOW) -> list:
    """Today's list, filled to `want` with this week's trending repos not already on it.
    Fill-ins get no stars_today (their number is a weekly count, not today's)."""
    have = {r["repo"] for r in rows}
    out = list(rows)
    for w in weekly:
        if len(out) >= want:
            break
        if w["repo"] not in have:
            out.append({**w, "rank": len(out) + 1, "stars_today": None})
            have.add(w["repo"])
    return out


def main() -> int:
    print(f"Fetching {URL} ...")
    try:
        rows = parse_trending(fetch())
    except Exception as e:
        print(f"GITHUB TRENDING FAILED: {e}")
        return 1
    problem = list_problem(rows)
    if problem:
        print(f"GITHUB TRENDING FAILED: {problem}; keeping the old list")
        return 1
    if len(rows) < SHOW:
        # GitHub's daily page is sometimes short (8 repos on 28 Sep 2026).
        try:
            weekly = parse_trending(fetch(WEEKLY_URL))
            before = len(rows)
            rows = top_up(rows, weekly)
            print(f"  today listed only {before}; added {len(rows) - before} from this week's trending")
        except Exception as e:
            print(f"  today listed only {len(rows)}; weekly top-up failed ({e}), saving the short list")
    save(rows)
    top = ", ".join(r["repo"] for r in rows[:3])
    print(f"GITHUB TRENDING OK: {len(rows)} repos (top: {top})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
