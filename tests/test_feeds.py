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
    any_real = any("score_real" in (df := pd.read_csv(f)).columns and df["score_real"].astype(str).eq("True").any()
                   for f in glob.glob(os.path.join(ROOT, "data/r_*/posts.csv")))
    for item in d["monthly"] + d["yearly"]:
        assert "pts" not in item["meta"]
        assert item["rank"] >= 1
        if not any_real:
            assert item["upvotes"] == ""
    assert not any("AskHistorians" in i["source"] for i in d["monthly"])
    assert len(d["monthly"]) == 50
    monthly_ids = {i["id"] for i in d["monthly"]}
    assert not any(i["id"] in monthly_ids for i in d["yearly"])
    keys = [server.title_key(i["title"]) for i in d["news"]]
    assert len(keys) == len(set(keys))
    assert d["updated"]["news"].endswith("Z")
