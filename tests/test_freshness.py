"""/api/freshness (contract v1, 2 Oct 2026): ages of what the SCREEN serves, judged
here exactly as fleet-health's probe_freshness judges them.

Every fixture file is written by the producer's own code (write_list, update_meta,
stamp_github_meta, the GitHub Trending save) or with the producer's exact columns
(Ritholtz, Google News), so a renamed field breaks these tests, not the live site.

run: .venv/bin/python -m pytest tests -q
"""
import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))

import server
import scrape_github_trending as gt
from fastapi.testclient import TestClient
from scrape_reddit_browser import rows_from_page, update_meta, write_list
from scrape_top import stamp_github_meta

NOW = datetime(2026, 10, 2, 22, 0, tzinfo=timezone.utc)   # Friday 18:00 EDT

RITHOLTZ_COLS = ["article_id", "title", "url", "description", "pub_date", "author", "source_post", "scraped_at"]
NEWS_COLS = ["article_id", "title", "url", "description", "pub_date", "author", "category", "scraped_at"]


def judge(item):
    """fleet_health.probe_freshness's rule for one item: True = green."""
    inp, srv, grace, cap = item["inputAgeH"], item["servedAgeH"], item["graceH"], item.get("maxAgeH")
    if inp is not None and inp > grace and (srv is None or srv > inp + 0.25):
        return False
    if cap is not None and srv is not None and srv > cap:
        return False
    return True


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def mac_rows(sub, prefix, n=8):
    raw = [{"id": f"t3_{prefix}{i}", "score": str(900 - i), "comments": "2", "title": f"{sub} {i}",
            "type": "text", "link": f"/r/{sub}/comments/{prefix}{i}/x/", "body": "text"} for i in range(n)]
    return rows_from_page(raw, sub)


def write_csv(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A healthy site at NOW: every producer ran on time."""
    data = tmp_path / "data"
    for key, prefix in (("r_LifeProTips", "m"), ("r_LifeProTips_yearly", "y"),
                        ("r_bestof", "b"), ("r_bestof_yearly", "c")):
        write_list(mac_rows(key[2:].removesuffix("_yearly"), prefix), key, root=data)
    mac_save = iso(NOW - timedelta(hours=2, minutes=25))            # the 19:35 ET run
    keys = ["r_LifeProTips", "r_LifeProTips_yearly", "r_bestof", "r_bestof_yearly"]
    update_meta({k: mac_save for k in keys}, path=data / "reddit_browser.json",
                checked={k: mac_save for k in keys}, via={k: "page" for k in keys})
    write_csv(data / "ritholtz/articles.csv", RITHOLTZ_COLS, [
        {"article_id": f"a{i}", "title": f"Read {i}", "url": f"https://ex.com/{i}", "description": "d",
         "pub_date": "2026-10-02T06:30:08-04:00", "author": "X",
         "source_post": "https://ritholtz.com/2026/10/10-friday-am-reads-518/",
         "scraped_at": "2026-10-02T11:00:59.308056"} for i in range(3)])
    write_csv(data / "googlenews/articles.csv", NEWS_COLS, [
        {"article_id": "n1", "title": "Headline", "url": "https://ex.com/n", "description": "",
         "pub_date": "2026-10-02T05:00:00+00:00", "author": "BSS", "category": "Bangladesh Economy",
         "scraped_at": "2026-10-02T09:18:43.643443"}])
    gh_rows = [{"rank": i, "repo": f"o/r{i}", "url": f"https://github.com/o/r{i}", "description": "",
                "language": "Python", "stars": 10, "forks": 1, "stars_today": 5} for i in range(1, 12)]
    monkeypatch.setattr(gt, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: NOW - timedelta(hours=4))}))
    gt.save(gh_rows, path=str(data / "github_trending/repos.csv"))
    monkeypatch.setattr(server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(server, "BROWSER_META", data / "reddit_browser.json")
    monkeypatch.setattr(server, "GITHUB_META", data / "reddit_github.json")
    return data


def items(now=NOW):
    return {i["name"]: i for i in server.freshness_items(now)}


def test_healthy_site_is_green_on_every_tab(site):
    got = items()
    assert set(got) == {"reddit-monthly", "reddit-yearly", "news", "am-reads", "satpost", "github-trending"}
    assert got["reddit-monthly"]["servedAgeH"] == 2.4 and got["reddit-yearly"]["servedAgeH"] == 2.4
    assert got["news"]["servedAgeH"] == 12.7
    assert got["am-reads"]["servedAgeH"] == 11.5      # Friday 06:30:08 EDT -> 18:00 EDT
    assert got["github-trending"]["servedAgeH"] == 4.0
    assert all(judge(i) for i in got.values()), got


def test_endpoint_shape_no_store_and_no_content(site, monkeypatch):
    monkeypatch.setattr(server, "freshness_items", lambda: [{"name": "x", "inputAgeH": None,
                                                              "servedAgeH": 1.0, "graceH": 0}])
    r = TestClient(server.app).get("/api/freshness")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json() == {"app": "reddit-scraper", "v": 1, "items": [{"name": "x", "inputAgeH": None,
                                                                    "servedAgeH": 1.0, "graceH": 0}]}


def test_real_endpoint_has_only_ages_and_names(site):
    body = TestClient(server.app).get("/api/freshness").json()
    for i in body["items"]:
        assert set(i) <= {"name", "inputAgeH", "servedAgeH", "graceH", "maxAgeH"}
        assert all(v is None or isinstance(v, (int, float)) for k, v in i.items() if k != "name")


def test_storage_error_is_500(site, monkeypatch):
    def boom():
        raise OSError("disk")
    monkeypatch.setattr(server, "get_data", boom)
    r = TestClient(server.app).get("/api/freshness")
    assert r.status_code == 500 and "error" in r.json()


def test_mac_reaching_reddit_but_keeping_the_old_file_is_stale(site):
    """The writer-stamp trap: `checked` moves on every run, `lists` (the save) does not."""
    old = iso(NOW - timedelta(hours=60))
    update_meta({"r_bestof": old}, path=site / "reddit_browser.json",
                checked={"r_bestof": iso(NOW - timedelta(hours=2))})
    got = items()
    assert got["reddit-monthly"]["servedAgeH"] == 60.0
    assert not judge(got["reddit-monthly"]) and judge(got["reddit-yearly"])


def test_github_backup_refill_counts_as_served(site, monkeypatch):
    update_meta({"r_bestof_yearly": iso(NOW - timedelta(hours=60))}, path=site / "reddit_browser.json")
    assert not judge(items()["reddit-yearly"])
    import scrape_top
    monkeypatch.setattr(scrape_top, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: NOW - timedelta(hours=1))}))
    stamp_github_meta("r_bestof_yearly", path=site / "reddit_github.json")
    got = items()["reddit-yearly"]
    assert got["servedAgeH"] == 2.4 and judge(got)   # oldest is now the Mac's 2.4 h lists


def test_dropped_list_stamp_does_not_hide_a_stale_one(site):
    """Only lists the tab actually shows count: AskHistorians never shows on Monthly."""
    update_meta({"r_AskHistorians": iso(NOW - timedelta(hours=500))}, path=site / "reddit_browser.json")
    assert judge(items()["reddit-monthly"])


def test_news_not_refreshed_is_stale(site):
    write_csv(site / "googlenews/articles.csv", NEWS_COLS, [
        {"article_id": "n1", "title": "Headline", "url": "https://ex.com/n", "description": "",
         "pub_date": "2026-09-30T05:00:00+00:00", "author": "BSS", "category": "Bangladesh Economy",
         "scraped_at": "2026-09-30T03:10:00.1"}])
    assert not judge(items()["news"])


def test_github_trending_not_refreshed_is_stale(site, monkeypatch):
    monkeypatch.setattr(gt, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: NOW - timedelta(hours=20))}))
    gt.save([{"rank": i, "repo": f"o/r{i}", "url": "u", "description": "", "language": "", "stars": 1,
              "forks": 1, "stars_today": 1} for i in range(1, 12)], path=str(site / "github_trending/repos.csv"))
    assert not judge(items()["github-trending"])


def test_am_reads_missed_weekday_is_red_next_morning(site):
    # Thursday's list still served at Friday 13:00 EDT (Friday's slot is due) -> red
    write_csv(site / "ritholtz/articles.csv", RITHOLTZ_COLS, [
        {"article_id": "a1", "title": "Read", "url": "https://ex.com/1", "description": "",
         "pub_date": "2026-10-01T06:30:02-04:00", "author": "", "source_post":
         "https://ritholtz.com/2026/10/10-thursday-am-reads-513/", "scraped_at": "2026-10-01T11:00:00"}])
    assert judge(items(datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc))["am-reads"])     # Fri 05:00 EDT
    assert not judge(items(datetime(2026, 10, 2, 17, 0, tzinfo=timezone.utc))["am-reads"])


def test_am_reads_weekend_reads_carry_sunday_and_monday_dawn(site):
    write_csv(site / "ritholtz/articles.csv", RITHOLTZ_COLS, [
        {"article_id": "a1", "title": "Read", "url": "https://ex.com/1", "description": "",
         "pub_date": "2026-10-03T06:30:00-04:00", "author": "", "source_post":
         "https://ritholtz.com/2026/10/10-weekend-reads-110/", "scraped_at": "2026-10-03T11:00:00"}])
    assert judge(items(datetime(2026, 10, 4, 23, 0, tzinfo=timezone.utc))["am-reads"])    # Sunday night
    assert judge(items(datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc))["am-reads"])     # Mon 05:00 EDT
    assert not judge(items(datetime(2026, 10, 5, 17, 0, tzinfo=timezone.utc))["am-reads"])  # Monday missed


def test_am_reads_cap_follows_dst():
    # 09 Nov 2026 is EST: Monday 13:00 EST = 18:00 UTC -> Monday's 06:30 slot due, 6.5 h + 1
    assert server.am_reads_max_age_h(datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc)) == 7.5
    assert server.am_reads_max_age_h(datetime(2026, 10, 5, 17, 0, tzinfo=timezone.utc)) == 7.5
