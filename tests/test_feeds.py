"""Reddit / News honesty + reliability tests (run: python -m pytest tests -q)."""
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "core"))
sys.path.insert(0, ROOT)

import requests
from scrape_top import parse_rss
from scrape_googlenews import fetch_with_retry

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>t3_abc123</id>
    <title>LPT: a self post</title>
    <link href="https://www.reddit.com/r/LifeProTips/comments/abc123/x/"/>
    <content type="html">&lt;!-- SC_OFF --&gt;&lt;div class="md"&gt;&lt;p&gt;First line.&lt;/p&gt; &lt;p&gt;Second line.&lt;/p&gt;&lt;/div&gt;&lt;!-- SC_ON --&gt; submitted by /u/someone</content>
  </entry>
  <entry>
    <id>t3_def456</id>
    <title>A link post</title>
    <link href="/r/LifeProTips/comments/def456/y/"/>
    <content type="html">&lt;table&gt;&lt;tr&gt;&lt;td&gt;[link]&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;</content>
  </entry>
</feed>"""


def test_rss_scores_are_flagged_not_real():
    posts = parse_rss(RSS, "LifeProTips")
    assert [p["id"] for p in posts] == ["abc123", "def456"]
    assert all(p["score_real"] is False for p in posts)
    assert posts[0]["score"] > posts[1]["score"]  # still orders the list


def test_rss_keeps_self_post_text_and_absolute_links():
    posts = parse_rss(RSS, "LifeProTips")
    assert posts[0]["selftext"] == "First line. Second line."
    assert posts[1]["selftext"] == ""
    assert posts[1]["permalink"].startswith("https://www.reddit.com/r/")


class FakeResp:
    def __init__(self, code):
        self.status_code = code
        self.content = b"<rss/>"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class FakeSession:
    def __init__(self, codes):
        self.codes = list(codes)
        self.calls = 0

    def get(self, url, timeout):
        self.calls += 1
        return FakeResp(self.codes.pop(0))


def test_news_retries_503_then_succeeds():
    s = FakeSession([503, 503, 200])
    waits = []
    assert fetch_with_retry(s, "u", sleep=waits.append).status_code == 200
    assert s.calls == 3 and waits == [5, 20]


def test_news_gives_up_after_three_503s():
    s = FakeSession([503, 503, 503])
    try:
        fetch_with_retry(s, "u", sleep=lambda _: None)
        assert False, "should raise"
    except RuntimeError as e:
        assert "503" in str(e)
    assert s.calls == 3


def test_news_404_is_not_retried():
    s = FakeSession([404])
    try:
        fetch_with_retry(s, "u", sleep=lambda _: None)
        assert False, "should raise"
    except requests.HTTPError:
        pass
    assert s.calls == 1


def test_api_is_honest_and_has_no_repeats():
    os.chdir(ROOT)
    import server
    d = server.get_data()
    # No invented upvotes: a number shows only if some CSV says it came from Reddit.
    import glob
    import pandas as pd
    def has_real(df):
        return (("score_real" in df.columns and df["score_real"].astype(str).eq("True").any())
                or ("upvotes" in df.columns and pd.to_numeric(df["upvotes"], errors="coerce").notna().any()))
    any_real = any(has_real(pd.read_csv(f)) for f in glob.glob(os.path.join(ROOT, "data/r_*/posts.csv")))
    for item in d["monthly"] + d["yearly"]:
        assert "pts" not in item["meta"]
        assert item["rank"] >= 1
        if not any_real:
            assert item["upvotes"] == ""
    assert not any("AskHistorians" in i["source"] for i in d["monthly"])
    assert len(d["monthly"]) == 50
    monthly_ids = {i["id"] for i in d["monthly"]}
    assert not any(i["id"] in monthly_ids for i in d["yearly"])
    # News = a date window, not a count cap; Reddit tabs say what they were picked from.
    import pandas as pd
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=server.NEWS_DAYS, hours=1)
    assert all(pd.Timestamp(i["ts"]) >= cutoff for i in d["news"])
    assert d["totals"]["monthly"] >= len(d["monthly"]) and d["totals"]["yearly"] >= len(d["yearly"])
    assert d["totals"]["news_days"] == server.NEWS_DAYS
    assert not glob.glob(os.path.join(ROOT, "data/r_Fitness*"))   # dropped sub: no stale leftovers
    keys = [server.title_key(i["title"]) for i in d["news"]]
    assert len(keys) == len(set(keys))
    assert d["updated"]["news"].endswith("Z")


# ---- Mac mini real-browser scraper (core/scrape_reddit_browser.py) ----
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
from scrape_reddit_browser import rows_from_page, write_list, update_meta
from reddit_common import fresh_keys, list_key


def test_browser_rows_keep_order_real_upvotes_and_text():
    raw = [
        {"id": "t3_aaa", "score": "23092", "comments": "812", "title": "First  post",
         "type": "text", "link": "/r/x/comments/aaa/first/", "body": " Body text \n"},
        {"id": "t3_vid", "score": "9999", "title": "A video", "type": "video", "link": "/r/x/v"},
        {"id": "t3_aaa", "score": "1", "title": "dupe", "type": "text", "link": "/r/x/aaa"},
        {"id": "t3_bbb", "score": "", "title": "Hidden score", "type": "link", "link": "https://www.reddit.com/r/x/bbb/"},
        {"id": "", "score": "5", "title": "no id"},
    ]
    rows = rows_from_page(raw, "todayilearned")
    assert [r["id"] for r in rows] == ["aaa", "bbb"]          # order kept, video + dupe + junk dropped
    assert rows[0]["upvotes"] == 23092
    assert all(r["score_real"] is False for r in rows)   # `score` is the tier number, never "real"
    assert rows[0]["title"] == "First post" and rows[0]["selftext"] == "Body text"
    assert rows[0]["permalink"] == "https://www.reddit.com/r/x/comments/aaa/first/"
    assert rows[1]["upvotes"] == ""                      # never show a number Reddit didn't give
    assert rows[1]["permalink"] == "https://www.reddit.com/r/x/bbb/"
    # Ordering score = the tier mix (TIL is Tier 1: 75k-100k), not the real upvotes.
    assert 75000 <= rows[0]["score"] <= 101000 and rows[0]["score"] > rows[1]["score"]


def test_tier_ordering_mixes_big_and_small_subs():
    # Real upvotes differ ~20x between subs; ordering by them filled Monthly with
    # r/todayilearned. The tier score keeps every sub's top posts near the top.
    til = rows_from_page([{"id": f"t3_t{i}", "score": str(20000 - i), "title": "t", "type": "text",
                           "link": "/x"} for i in range(50)], "todayilearned")
    lpt = rows_from_page([{"id": f"t3_l{i}", "score": str(900 - i), "title": "l", "type": "text",
                           "link": "/x"} for i in range(50)], "LifeProTips")
    top50 = sorted(til + lpt, key=lambda r: r["score"], reverse=True)[:50]
    assert sum(r["id"].startswith("l") for r in top50) >= 10


def test_browser_csv_reads_back_as_real_upvotes(tmp_path):
    import pandas as pd
    rows = rows_from_page([{"id": "t3_c1", "score": "1500", "comments": "3", "title": 'Quote "x", comma',
                            "type": "text", "link": "/r/x/c1", "body": "line1\nline2"}], "Test")
    path = write_list(rows, "r_Test_yearly", root=tmp_path)
    df = pd.read_csv(path)
    assert list(df.columns)[:5] == ["id", "title", "selftext", "permalink", "score"]
    assert df.loc[0, "title"] == 'Quote "x", comma' and df.loc[0, "selftext"] == "line1\nline2"
    assert not df["score_real"].astype(str).str.lower().isin(["true", "1"]).any()  # same test server.py uses
    import server
    row = df.fillna("").iloc[0]
    assert server.shown_upvotes(row) == "1.5k"                                        # the real number
    assert server.shown_upvotes({"upvotes": "", "score": 777, "score_real": True}) == "777"   # old JSON rows
    assert server.shown_upvotes({"upvotes": "", "score": 88000, "score_real": False}) == ""  # RSS: rank instead


def test_github_rss_skips_lists_the_mac_saved_recently(tmp_path):
    meta_path = tmp_path / "reddit_browser.json"
    update_meta({"r_LifeProTips": "2026-09-26T12:00:00Z"}, path=meta_path)
    update_meta({"r_bestof_yearly": "2026-09-24T12:00:00Z"}, path=meta_path)   # merges, doesn't replace
    lists = json.loads(meta_path.read_text())["lists"]
    assert set(lists) == {"r_LifeProTips", "r_bestof_yearly"}
    now = datetime(2026, 9, 27, 6, 0, tzinfo=timezone.utc)
    fresh = fresh_keys(lists, now)
    # A hand-edited or broken stamp must never crash the GitHub run (News runs after it).
    assert fresh_keys({"r_a": "2026-09-27T01:00:00", "r_b": "junk", "r_c": None}, now) == {}
    assert fresh_keys(["not", "a", "dict"], now) == {}
    assert list(fresh) == ["r_LifeProTips"] and round(fresh["r_LifeProTips"]) == 18   # 66 h old = stale
    assert list_key("bestof", "year") == "r_bestof_yearly" and list_key("bestof", "month") == "r_bestof"
