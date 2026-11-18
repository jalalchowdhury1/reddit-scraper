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


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "comments_page_1x9aonz.json"


def items(*comments):
    """A post page's comments the way COMMENTS_JS returns them, top order. comments =
    body html strings, (author, html) pairs, or dicts of extra fields (depth, mod)."""
    from html import escape
    out = []
    for cm in comments:
        extra = {}
        if isinstance(cm, dict):
            extra, cm = cm, cm.pop("html")
        author, html = cm if isinstance(cm, tuple) else ("someone", cm)
        if not html.startswith("<"):
            html = f"<p>{escape(html, quote=False)}</p>"
        out.append({"author": author, "depth": "0", "mod": False,
                    "html": f'<div id="t1_x-post-rtjson-content">{html}</div>', **extra})
    return out


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


def run(coro):
    return asyncio.run(coro)


def test_fetch_loop_caches_limits_prunes_and_stops_on_failures(tmp_path):
    write_list(posts("LifeProTips", "p", 5), "r_LifeProTips", root=tmp_path)
    tc.save_cache({"gone": {"body": "left every list", "at": "2026-10-01T00:00:00Z"}}, tmp_path / "reddit_comments.json")
    asked = []

    async def fetch(page, pid):
        asked.append(pid)
        return items(f"comment for {pid}")

    stats = run(tc.fetch_top_comments(FakePage(), fetch, root=tmp_path, max_posts=3, pace=(0, 0)))
    cache = tc.load_cache(tmp_path / "reddit_comments.json")
    assert stats["new"] == 3 and stats["left"] == 2 and len(asked) == 3
    assert "gone" not in cache and cache["p0"]["body"] == "comment for p0" and cache["p0"]["ups"] is None   # never served
    assert asked[0] == "p0" and tc.post_url("p0") == "https://www.reddit.com/comments/p0/?sort=top"
    # Next run asks only the two it hasn't seen.
    asked.clear()
    run(tc.fetch_top_comments(FakePage(), fetch, root=tmp_path, pace=(0, 0)))
    assert len(asked) == 2

    # Three failures in a row stop the step (Reddit slowing down must not cost the next run).
    write_list(posts("LifeProTips", "q", 6), "r_LifeProTips_yearly", root=tmp_path)
    calls = []

    async def blocked(page, pid):
        calls.append(pid)
        raise RuntimeError("HTTP 403")

    stats = run(tc.fetch_top_comments(FakePage(), blocked, root=tmp_path, pace=(0, 0)))
    assert len(calls) == 3 and stats["failed"] == 3 and "3 failures" in stats["stopped"]
    assert "STOPPED" in tc.comments_line(stats)
    assert tc.load_cache(tmp_path / "reddit_comments.json")["p0"]["body"]   # old cache kept


def test_fetch_loop_time_budget(tmp_path):
    write_list(posts("LifeProTips", "t", 4), "r_LifeProTips", root=tmp_path)

    async def fetch(page, pid):
        return items("x")

    stats = run(tc.fetch_top_comments(FakePage(), fetch, root=tmp_path, budget_s=-1, pace=(0, 0)))
    assert stats["new"] == 0 and stats["stopped"] == "time budget"


def test_no_comment_is_cached_empty(tmp_path):
    write_list(posts("LifeProTips", "e", 1), "r_LifeProTips", root=tmp_path)

    async def fetch(page, pid):
        return items("[deleted]")

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
    tc.save_cache({"m0": {"body": "Top & best ?a=1&copy=2", "ups": 1234, "at": "x"},
                   "m1": {"body": "", "at": "x"},
                   "m2": {"body": "no ups", "ups": None, "at": "x"}}, site / "reddit_comments.json")
    cards = {i["id"]: i for i in server.get_data()["monthly"]}
    assert cards["m0"]["top_comment"] == "Top & best ?a=1&copy=2"   # served as-is, never unescaped twice
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

    async def fetch(page, pid):
        return items("x")

    run(tc.fetch_top_comments(FakePage(), fetch, root=tmp_path, subs={"lifeprotips"}, pace=(0, 0)))   # typo: no such folder
    run(tc.fetch_top_comments(FakePage(), fetch, root=tmp_path, subs={"LifeProTips"}, pace=(0, 0)))
    assert tc.load_cache(tmp_path / "reddit_comments.json")["z0"]["body"] == "keep me"


def test_pushback_is_never_cached(tmp_path):
    """A 429 burst must not hide the top posts' comments for days: next run asks them again."""
    write_list(posts("LifeProTips", "h", 6), "r_LifeProTips", root=tmp_path)
    asked = []

    async def slow_down(page, pid):
        raise RuntimeError("HTTP 429")

    stats = run(tc.fetch_top_comments(FakePage(), slow_down, root=tmp_path, pace=(0, 0)))
    assert stats["failed"] == 3 and stats["stopped"] and tc.load_cache(tmp_path / "reddit_comments.json") == {}

    async def fine(page, pid):
        asked.append(pid); return items("ok")

    run(tc.fetch_top_comments(FakePage(), fine, root=tmp_path, pace=(0, 0)))
    assert asked[:3] == ["h0", "h1", "h2"]


def test_admin_removed_media_italics_bullets():
    assert tc.pick_top(listing(c("[ Removed by Reddit ]", ups=900), c("real one"))) == {"body": "real one", "ups": 10}
    assert tc.clean_body("lol ![gif](giphy|abc123) and ![img](emote|t5_2|123)") == "lol [GIF] and [image]"
    assert tc.clean_body("it *could* work\n* one\n- two\n2*3*4 stays") == "it could work one two 2*3*4 stays"


def test_failures_are_cached_and_404s_dont_stop_the_step(tmp_path):
    write_list(posts("LifeProTips", "g", 5), "r_LifeProTips", root=tmp_path)
    asked = []

    async def fetch(page, pid):
        asked.append(pid)
        if len(asked) <= 3:
            raise RuntimeError("HTTP 404")
        return items("fine")

    stats = run(tc.fetch_top_comments(FakePage(), fetch, root=tmp_path, pace=(0, 0)))
    assert stats["failed"] == 3 and stats["new"] == 2 and not stats["stopped"]
    cache = tc.load_cache(tmp_path / "reddit_comments.json")
    assert cache["g0"]["body"] == "" and "404" in cache["g0"]["failed"]
    asked.clear()
    run(tc.fetch_top_comments(FakePage(), fetch, root=tmp_path, pace=(0, 0)))
    assert asked == []   # misses wait EMPTY_RETRY_DAYS like empties


# ---------- the post page (17 Nov 2026: Reddit ended RSS, every .rss url 404s) ----------

def test_page_real_reply_skips_mod_sticky_and_replies():
    """Real COMMENTS_JS reply saved 17 Nov (trimmed): [0] r/dataisbeautiful's OC sticky from
    a mod's account (is-mod-distinguished), [1] the real top comment, [2] a reply to it."""
    got = tc.pick_top_page(json.loads(FIXTURE.read_text())["comments"])
    assert got["ups"] is None and got["body"].startswith("I doubt it's possible to do that fairly")


def test_page_skips_bots_notices_replies_and_deleted():
    got = tc.pick_top_page(items(
        {"html": "pinned rules", "mod": True},
        ("AutoModerator", "Please read the rules"),
        ("SomeHelperBot", "beep"),
        ("a_mod", '<p>Your post broke <a href="/r/LifeProTips/wiki/rules">rule 2</a></p>'),
        ("a_mod", "<p>I am a bot, and this action was performed automatically.</p>"),
        {"html": "a reply, not top-level", "depth": "1"},
        ("[deleted]", "[deleted]"),
        "[removed]",
        "[ Removed by Reddit ]",
        '<p>The <strong>real</strong> answer, see <a href="https://x.com/a">this</a>.</p>',
    ))
    assert got == {"body": "The real answer, see this.", "ups": None}


def test_page_html_spoilers_media_quotes_and_cut():
    html = ('<blockquote><p>quoted</p></blockquote><p>a <span class="md-spoiler-text">Snape <em>kills</em> '
            'him</span> b</p><ul><li>one</li><li>two &amp; three</li></ul>'
            '<p><a href="https://preview.redd.it/x.gif?w=1">https://preview.redd.it/x.gif?w=1</a> '
            '<a href="https://i.redd.it/y.png">https://i.redd.it/y.png</a></p>')
    assert tc.pick_top_page(items(html))["body"] == "quoted a [spoiler] b one two & three [GIF] [image]"
    long = tc.pick_top_page(items("word " * 200))["body"]
    assert len(long) <= tc.MAX_CHARS + 1 and long.endswith("…")
    assert tc.pick_top_page([]) == {} and tc.pick_top_page(items("[deleted]")) == {}


class NavPage(FakePage):
    """A browser page for read_post_page: goto() answers `status`, the page holds `got`."""
    def __init__(self, status, got):
        self.statuses = list(status) if isinstance(status, tuple) else [status]
        self.got, self.urls = got, []

    async def goto(self, url, **kw):
        self.urls.append(url)
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return type("R", (), {"status": status, "headers": {"retry-after": "1"}})()

    async def wait_for_selector(self, sel, **kw):
        if not self.got.get("comments"):
            raise TimeoutError("no comments")

    async def evaluate(self, js):
        return self.got


def test_read_post_page_statuses_and_challenge():
    page = NavPage(200, {"post": True, "comments": items("hi")})
    assert run(tc.read_post_page(page, "ab")) == items("hi") and page.urls == ["https://www.reddit.com/comments/ab/?sort=top"]
    assert run(tc.read_post_page(NavPage(200, {"post": True, "comments": []}), "ab")) == []   # no comments yet
    page = NavPage((429, 200), {"post": True, "comments": items("hi")})        # one 429: wait, ask again
    assert run(tc.read_post_page(page, "ab")) == items("hi") and len(page.urls) == 2
    for status, got, why in ((404, {}, "HTTP 404"), (403, {}, "HTTP 403"), ((429, 429), {}, "HTTP 429"),
                             (200, {"post": False, "comments": []}, "not a post page")):
        with pytest.raises(RuntimeError, match=why):
            run(tc.read_post_page(NavPage(status, got), "ab"))


def test_challenge_page_is_pushback_not_a_cached_miss(tmp_path):
    """The 17 Nov failure mode, replayed: every read fails the same way -> 3 in a row stop the
    step and nothing is cached as "no comment"."""
    write_list(posts("LifeProTips", "k", 5), "r_LifeProTips", root=tmp_path)
    page = NavPage(200, {"post": False, "comments": []})
    stats = run(tc.fetch_top_comments(page, root=tmp_path, pace=(0, 0)))
    assert stats["failed"] == 3 and "3 failures" in stats["stopped"] and "not a post page" in stats["stopped"]
    assert tc.load_cache(tmp_path / "reddit_comments.json") == {}
