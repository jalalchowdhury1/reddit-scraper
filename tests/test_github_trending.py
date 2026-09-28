"""GitHub Trending: the page parser, the "don't save a wrong list" guard, and the
tab the server builds from data/github_trending/repos.csv.

run: .venv/bin/python -m pytest tests -q   (no network: the page is a saved copy)
"""
import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))

import scrape_github_trending as gt
import server
from fastapi.testclient import TestClient

PAGE = (ROOT / "tests/fixtures/github_trending.html").read_text()   # github.com/trending, 26 Sep 2026, 12 rows


# ---------- parser ----------

def test_parses_every_row_in_page_order_with_githubs_numbers():
    rows = gt.parse_trending(PAGE)
    assert len(rows) == 12
    assert [r["rank"] for r in rows] == list(range(1, 13))
    assert rows[0] == {"rank": 1, "repo": "paperclipai/paperclip", "url": "https://github.com/paperclipai/paperclip",
                       "description": "The open-source app everyone uses to manage agents at work",
                       "language": "TypeScript", "stars": 87484, "forks": 15444, "stars_today": 2608}
    assert rows[1]["repo"] == "vectorize-io/hindsight" and rows[1]["stars_today"] == 2147


def test_a_repo_without_description_or_language_is_kept_with_blanks():
    html = PAGE.replace('<span itemprop="programmingLanguage">TypeScript</span>', "", 1)
    first = gt.parse_trending(html)[0]
    assert first["language"] == "" and first["repo"] == "paperclipai/paperclip"
    assert gt.parse_trending(PAGE)[-1]["description"] == ""   # claude-code-action has none on the page


def test_to_int_reads_githubs_formats():
    assert gt.to_int("\n 87,484") == 87484
    assert gt.to_int("2,608 stars today") == 2608
    assert gt.to_int("") is None and gt.to_int(None) is None


# ---------- the guard: a wrong list is never saved ----------

def test_the_real_page_passes_the_guard():
    assert gt.list_problem(gt.parse_trending(PAGE)) == ""


def test_a_layout_change_is_refused():
    assert "layout" in gt.list_problem(gt.parse_trending("<html><body>new design</body></html>"))
    # Rows found but the star counts moved: refused, not saved as blanks.
    no_stars = PAGE.replace("stars today", "sterren vandaag").replace("/stargazers", "/fans")
    assert "star counts" in gt.list_problem(gt.parse_trending(no_stars))


def test_a_short_or_repeated_list_is_refused():
    rows = gt.parse_trending(PAGE)
    assert "only 4" in gt.list_problem(rows[:4])
    assert gt.list_problem(rows[:8]) == ""   # a short day (8 on 28 Sep 2026) is real, not broken
    assert "twice" in gt.list_problem(rows + rows[:1])


def test_main_keeps_the_old_file_when_the_page_is_wrong(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gt, "fetch", lambda: PAGE)
    assert gt.main() == 0
    saved = (tmp_path / gt.OUTPUT_FILE).read_text()
    assert "GITHUB TRENDING OK: 12 repos" in capsys.readouterr().out
    monkeypatch.setattr(gt, "fetch", lambda: "<html>login wall</html>")
    assert gt.main() == 1
    assert "GITHUB TRENDING FAILED" in capsys.readouterr().out
    assert (tmp_path / gt.OUTPUT_FILE).read_text() == saved


def test_a_short_day_is_topped_up_from_weekly_without_repeats(tmp_path, monkeypatch, capsys):
    rows = gt.parse_trending(PAGE)
    monkeypatch.chdir(tmp_path)
    urls = []
    monkeypatch.setattr(gt, "fetch", lambda url=gt.URL: urls.append(url) or url)
    weekly = [dict(r, repo=f"week/r{i}") for i, r in enumerate(rows)]
    monkeypatch.setattr(gt, "parse_trending", lambda html: rows[:8] if html == gt.URL else rows[6:7] + weekly)
    assert gt.main() == 0
    assert urls == [gt.URL, gt.WEEKLY_URL]
    saved = gt.pd.read_csv(tmp_path / gt.OUTPUT_FILE)
    assert list(saved["rank"]) == list(range(1, 11))
    assert list(saved["repo"][:8]) == [r["repo"] for r in rows[:8]]
    assert list(saved["repo"][8:]) == ["week/r0", "week/r1"]   # rows[6] already on today's list: skipped
    assert saved["stars_today"][8:].isna().all()                 # weekly counts are not "today"
    assert "added 2 from this week" in capsys.readouterr().out


def test_a_short_day_still_saves_when_weekly_fails(tmp_path, monkeypatch, capsys):
    rows = gt.parse_trending(PAGE)
    monkeypatch.chdir(tmp_path)
    def fetch(url=gt.URL):
        if url == gt.WEEKLY_URL:
            raise RuntimeError("HTTP 503")
        return url
    monkeypatch.setattr(gt, "fetch", fetch)
    monkeypatch.setattr(gt, "parse_trending", lambda html: rows[:8])
    assert gt.main() == 0
    assert len(gt.pd.read_csv(tmp_path / gt.OUTPUT_FILE)) == 8
    assert "weekly top-up failed" in capsys.readouterr().out


def test_main_reports_a_network_failure(monkeypatch, capsys):
    def boom():
        raise RuntimeError("https://github.com/trending failed 3 times: HTTP 503")
    monkeypatch.setattr(gt, "fetch", boom)
    assert gt.main() == 1
    assert "GITHUB TRENDING FAILED: https://github.com/trending failed 3 times" in capsys.readouterr().out


class Reply:
    def __init__(self, code, text="ok"):
        self.status_code, self.text = code, text

    def raise_for_status(self):
        raise requests.HTTPError(f"HTTP {self.status_code}")


def test_fetch_retries_503_but_not_404(monkeypatch):
    calls = []
    monkeypatch.setattr(gt.time, "sleep", lambda s: None)
    replies = iter([Reply(503), Reply(429), Reply(200, "page")])
    monkeypatch.setattr(gt.requests, "get", lambda *a, **k: calls.append(1) or next(replies))
    assert gt.fetch() == "page" and len(calls) == 3
    calls.clear()
    monkeypatch.setattr(gt.requests, "get", lambda *a, **k: calls.append(1) or Reply(404))
    with pytest.raises(requests.HTTPError):
        gt.fetch()
    assert len(calls) == 1


def test_script_entry_point_runs_main():
    # A lost `if __name__ == "__main__"` would make the workflow a silent green no-op.
    assert 'if __name__ == "__main__":\n    sys.exit(main())' in (ROOT / "core/scrape_github_trending.py").read_text()


# ---------- server: the GitHub tab ----------

@pytest.fixture
def gh_site(tmp_path, monkeypatch):
    """server.py on a throwaway data/ with today's saved trending page."""
    monkeypatch.chdir(tmp_path)
    gt.save(gt.parse_trending(PAGE))
    monkeypatch.setattr(server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(server, "BROWSER_META", tmp_path / "data/reddit_browser.json")
    monkeypatch.setattr(server, "GITHUB_META", tmp_path / "data/reddit_github.json")
    return tmp_path / gt.OUTPUT_FILE


def test_tab_is_githubs_top_10_in_order_with_real_numbers(gh_site):
    d = TestClient(server.app).get("/api/data").json()
    gh = d["github"]
    assert len(gh) == 10 and d["totals"]["github"] == 12
    assert [i["rank"] for i in gh] == list(range(1, 11))
    assert gh[0]["title"] == "paperclipai/paperclip" and gh[0]["url"] == "https://github.com/paperclipai/paperclip"
    assert gh[0]["stars"] == "87.5k" and gh[0]["stars_today"] == "2,608"
    assert gh[0]["source"] == "GitHub · TypeScript" and gh[0]["domain"] == "github.com"
    assert d["updated"]["github"].endswith("Z")


def test_ids_have_no_slash_for_firestore(gh_site):
    # Read state is one Firestore doc per id; a '/' would split the path.
    ids = [i["id"] for i in server.get_data()["github"]]
    assert ids[0] == "gh_paperclipai_paperclip"
    assert all("/" not in i and i.startswith("gh_") for i in ids) and len(set(ids)) == 10


def test_missing_numbers_stay_blank_and_one_bad_row_costs_one_row(gh_site):
    lines = gh_site.read_text().splitlines()
    first = lines[1].split(",")
    first[5] = ""                     # stars missing
    lines[1] = ",".join(first)
    lines[2] = "notanumber,owner/repo,x,,,1,1,1,2026-09-26T12:00:00"   # rank junk: row dropped
    lines.append("13,just-a-name,x,,,1,1,1,2026-09-26T12:00:00")       # not owner/name: dropped
    gh_site.write_text("\n".join(lines) + "\n")
    gh = server.get_data()["github"]
    assert gh[0]["stars"] == "" and gh[0]["stars_today"] == "2,608"
    assert "owner/repo" not in [i["title"] for i in gh] and "just-a-name" not in [i["title"] for i in gh]
    assert len(gh) == 10


def test_broken_github_file_leaves_other_tabs_alone(gh_site):
    gh_site.write_bytes(b"\x00\xff garbage \"unclosed\n\x01,,\n")
    d = server.get_data()
    assert d["github"] == [] and d["totals"]["github"] == 0
    assert set(d) >= {"monthly", "yearly", "news", "ritholtz", "github"}


def test_status_counts_the_github_tab(gh_site):
    s = TestClient(server.app).get("/api/status").json()
    assert s["counts"]["github"] == 10 and s["updated"]["github"]
