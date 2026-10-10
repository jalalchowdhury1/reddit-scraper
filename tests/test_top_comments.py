"""Top comments (10 Oct 2026): the parser, the cache rules, the fetch loop's
limits, and the server attaching them to cards. No network.

run: .venv/bin/python -m pytest tests -q
"""
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))

import server
import top_comments as tc
from scrape_reddit_browser import rows_from_page, write_list


def listing(*comments):
    return [{"kind": "Listing", "data": {"children": [{"kind": "t3", "data": {}}]}},
            {"kind": "Listing", "data": {"children": list(comments)}}]


def c(body, ups=10, **extra):
    return {"kind": "t1", "data": {"body": body, "ups": ups, "author": "someone", **extra}}


def test_pick_top_skips_sticky_mod_automod_and_deleted():
    got = tc.pick_top(listing(
        c("Rule reminder", stickied=True),
        c("Mod note", distinguished="moderator"),
        {"kind": "t1", "data": {"body": "bot", "author": "AutoModerator", "ups": 1}},
        c("[deleted]"),
        c("[removed]"),
        {"kind": "more", "data": {}},
        c("The **real** answer, see [this](https://x.com/a_(b)).", ups=4321),
    ))
    assert got == {"body": "The real answer, see this.", "ups": 4321}


def test_pick_top_empty_and_garbage():
    assert tc.pick_top(listing()) == {}
    with pytest.raises(ValueError):
        tc.pick_top({"error": 403})


def test_clean_body_quotes_headings_and_cut():
    assert tc.clean_body("> quoted\n\n# Head\nline  two") == "quoted Head line two"
    long = "word " * 200
    out = tc.clean_body(long, limit=50)
    assert len(out) <= 51 and out.endswith("…") and not out[:-1].endswith(" ")


def posts(sub, prefix, n, comments="5"):
    raw = [{"id": f"t3_{prefix}{i}", "score": str(2000 - i), "comments": comments, "title": f"{sub} {i}",
            "type": "text", "link": f"/r/{sub}/comments/{prefix}{i}/x/", "body": ""} for i in range(n)]
    return rows_from_page(raw, sub)


def test_candidates_best_score_first_dedup_and_zero_comments(tmp_path):
    write_list(posts("LifeProTips", "a", 3), "r_LifeProTips", root=tmp_path)
    write_list(posts("LifeProTips", "a", 3), "r_LifeProTips_yearly", root=tmp_path)   # same ids
    write_list(posts("todayilearned", "z", 2, comments="0"), "r_todayilearned", root=tmp_path)
    got = tc.candidates(tmp_path)
    ids = [pid for pid, _ in got]
    assert sorted(ids) == ["a0", "a1", "a2"]           # deduped, 0-comment posts left out
    assert all(link.startswith("https://www.reddit.com/r/LifeProTips/comments/") for _, link in got)
    assert tc.candidates(tmp_path, subs={"todayilearned"}) == []


def test_due_rules():
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    old = (now - timedelta(days=tc.EMPTY_RETRY_DAYS, minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    new = (now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert tc.due(None, now) and tc.due({"body": "", "at": old}, now) and tc.due({"body": "", "at": "junk"}, now)
    assert not tc.due({"body": "x", "at": old}, now) and not tc.due({"body": "", "at": new}, now)


class FakePage:
    async def wait_for_timeout(self, ms):
        pass


class Resp:
    def __init__(self, data):
        self.data = data

    async def json(self):
        return self.data


def run(coro):
    return asyncio.run(coro)


def test_fetch_loop_caches_limits_prunes_and_stops_on_failures(tmp_path):
    write_list(posts("LifeProTips", "p", 5), "r_LifeProTips", root=tmp_path)
    tc.save_cache({"gone": {"body": "left every list", "at": "2026-10-01T00:00:00Z"}}, tmp_path / "reddit_comments.json")
    asked = []

    async def fetch(page, url):
        asked.append(url)
        return Resp(listing(c(f"comment for {url.split('/comments/')[1][:2]}", ups=7)))

    stats = run(tc.fetch_top_comments(FakePage(), fetch, root=tmp_path, max_posts=3, pace=(0, 0)))
    cache = tc.load_cache(tmp_path / "reddit_comments.json")
    assert stats["new"] == 3 and stats["left"] == 2 and len(asked) == 3
    assert "gone" not in cache and cache["p0"]["body"] == "comment for p0" and cache["p0"]["ups"] == 7
    assert all(u.endswith(".json?sort=top&limit=10&depth=1&raw_json=1") for u in asked)
    # Next run asks only the two it hasn't seen.
    asked.clear()
    run(tc.fetch_top_comments(FakePage(), fetch, root=tmp_path, pace=(0, 0)))
    assert len(asked) == 2

    # Three failures in a row stop the step (Reddit slowing down must not cost the next run).
    write_list(posts("LifeProTips", "q", 6), "r_LifeProTips_yearly", root=tmp_path)
    calls = []

    async def blocked(page, url):
        calls.append(url)
        raise RuntimeError("HTTP 403")

    stats = run(tc.fetch_top_comments(FakePage(), blocked, root=tmp_path, pace=(0, 0)))
    assert len(calls) == 3 and stats["failed"] == 3 and "3 failures" in stats["stopped"]
    assert "STOPPED" in tc.comments_line(stats)
    assert tc.load_cache(tmp_path / "reddit_comments.json")["p0"]["body"]   # old cache kept


def test_fetch_loop_time_budget(tmp_path):
    write_list(posts("LifeProTips", "t", 4), "r_LifeProTips", root=tmp_path)

    async def fetch(page, url):
        return Resp(listing(c("x")))

    stats = run(tc.fetch_top_comments(FakePage(), fetch, root=tmp_path, budget_s=-1, pace=(0, 0)))
    assert stats["new"] == 0 and stats["stopped"] == "time budget"


def test_no_comment_is_cached_empty(tmp_path):
    write_list(posts("LifeProTips", "e", 1), "r_LifeProTips", root=tmp_path)

    async def fetch(page, url):
        return Resp(listing(c("[deleted]")))

    stats = run(tc.fetch_top_comments(FakePage(), fetch, root=tmp_path, pace=(0, 0)))
    assert stats["empty"] == 1 and tc.load_cache(tmp_path / "reddit_comments.json")["e0"]["body"] == ""


# ---------- server ----------

@pytest.fixture
def site(tmp_path, monkeypatch):
    data = tmp_path / "data"
    write_list(posts("LifeProTips", "m", 4), "r_LifeProTips", root=data)
    monkeypatch.setattr(server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(server, "BROWSER_META", data / "reddit_browser.json")
    monkeypatch.setattr(server, "TOP_COMMENTS", data / "reddit_comments.json")
    return data


def test_server_attaches_top_comments(site):
    tc.save_cache({"m0": {"body": "Top &amp; best", "ups": 1234, "at": "x"},
                   "m1": {"body": "", "at": "x"},
                   "m2": {"body": "no ups", "ups": None, "at": "x"}}, site / "reddit_comments.json")
    cards = {i["id"]: i for i in server.get_data()["monthly"]}
    assert cards["m0"]["top_comment"] == "Top & best"
    assert "top_comment" not in cards["m1"] and "top_comment" not in cards["m3"]
    assert cards["m2"]["top_comment"] == "no ups"
    assert not any("top_comment_ups" in i for i in cards.values())   # a frozen snapshot = not shown


@pytest.mark.parametrize("junk", ["{not json", json.dumps([1, 2]), json.dumps({"posts": "x"}),
                                  json.dumps({"posts": {"m0": "str", "m1": {"body": 5}}})])
def test_server_broken_comments_file_costs_only_comments(site, junk):
    (site / "reddit_comments.json").write_text(junk)
    d = server.get_data()
    assert len(d["monthly"]) == 4 and not any("top_comment" in i for i in d["monthly"])


def test_hidden_scores_bools_and_spoilers():
    assert tc.pick_top(listing(c("new one", ups=1, score_hidden=True)))["ups"] is None
    assert tc.pick_top(listing(c("bool", ups=True)))["ups"] is None
    assert tc.clean_body(">!Snape kills Dumbledore!< but also >!multi\nline!<") == "[spoiler] but also [spoiler]"


def test_an_only_run_keeps_other_subs_comments(tmp_path):
    write_list(posts("LifeProTips", "a", 2), "r_LifeProTips", root=tmp_path)
    write_list(posts("todayilearned", "z", 2), "r_todayilearned", root=tmp_path)
    tc.save_cache({"z0": {"body": "keep me", "at": "2026-10-01T00:00:00Z"}}, tmp_path / "reddit_comments.json")

    async def fetch(page, url):
        return Resp(listing(c("x")))

    run(tc.fetch_top_comments(FakePage(), fetch, root=tmp_path, subs={"lifeprotips"}, pace=(0, 0)))   # typo: no such folder
    run(tc.fetch_top_comments(FakePage(), fetch, root=tmp_path, subs={"LifeProTips"}, pace=(0, 0)))
    assert tc.load_cache(tmp_path / "reddit_comments.json")["z0"]["body"] == "keep me"


def test_failures_are_cached_and_404s_dont_stop_the_step(tmp_path):
    write_list(posts("LifeProTips", "g", 5), "r_LifeProTips", root=tmp_path)
    asked = []

    async def fetch(page, url):
        asked.append(url)
        if len(asked) <= 3:
            raise RuntimeError("HTTP 404")
        return Resp(listing(c("fine")))

    stats = run(tc.fetch_top_comments(FakePage(), fetch, root=tmp_path, pace=(0, 0)))
    assert stats["failed"] == 3 and stats["new"] == 2 and not stats["stopped"]
    cache = tc.load_cache(tmp_path / "reddit_comments.json")
    assert cache["g0"]["body"] == "" and "404" in cache["g0"]["failed"]
    asked.clear()
    run(tc.fetch_top_comments(FakePage(), fetch, root=tmp_path, pace=(0, 0)))
    assert asked == []   # misses wait EMPTY_RETRY_DAYS like empties
