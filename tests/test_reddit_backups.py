"""Reddit backup ladder: what counts as a real list, the Mac's page -> json -> rss
fallbacks, the fresh-profile fallback, the fleet-health canary lines, and GitHub's
batched RSS backup. No network: every Reddit reply here is canned.

run: .venv/bin/python -m pytest tests -q
"""
import asyncio
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))

import scrape_reddit_browser as rb
import scrape_top
from scrape_reddit_browser import epoch, list_problem, method_check_line, raw_from_json, raw_from_rss

NOW = datetime(2026, 9, 26, 20, 0, tzinfo=timezone.utc).timestamp()
DAY = 86400
# The exact line fleet-health's "reddit-browser backups" row greps for.
FLEET_METHODS_RE = r"METHOD CHECK: page ok · json ok · rss ok"


def post(i, sub="LifeProTips", score="100", age_days=3, **kw):
    return {"id": f"t3_p{i}", "title": f"post {i}", "type": "text", "link": f"/r/{sub}/comments/p{i}/x/",
            "score": score, "sub": sub, "created": NOW - age_days * DAY, "body": "", **kw}


def listing(n, sub="LifeProTips", after="t3_next"):
    return {"kind": "Listing", "data": {"after": after, "children": [
        {"kind": "t3", "data": {"name": f"t3_j{i}", "score": 900 - i, "num_comments": 7, "title": f"J &amp; {i}",
                                "is_self": i % 2 == 0, "is_video": i == 3, "permalink": f"/r/{sub}/comments/j{i}/x/",
                                "selftext": "body" if i % 2 == 0 else "", "created_utc": NOW - 2 * DAY,
                                "subreddit": sub, "stickied": i == 0}} for i in range(n)]}}


RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <entry><category term="LifeProTips" label="r/LifeProTips"/><id>t3_r1</id><title>LPT: one</title>
  <link href="https://www.reddit.com/r/LifeProTips/comments/r1/x/"/><published>2026-09-20T10:00:00+00:00</published>
  <content type="html">&lt;!-- SC_OFF --&gt;&lt;div class="md"&gt;&lt;p&gt;First &amp;amp; line.&lt;/p&gt; &lt;div&gt;&lt;p&gt;inner&lt;/p&gt;&lt;/div&gt;&lt;p&gt;Last.&lt;/p&gt;&lt;/div&gt;&lt;!-- SC_ON --&gt; submitted by &lt;a href="x"&gt;/u/a&lt;/a&gt;</content></entry>
 <entry><category term="LifeProTips" label="r/LifeProTips"/><id>t3_r2</id><title>A link</title>
  <link href="/r/LifeProTips/comments/r2/y/"/><published>2026-09-21T10:00:00+00:00</published>
  <content type="html">&lt;table&gt;&lt;tr&gt;&lt;td&gt;[link]&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;</content></entry>
</feed>"""


# ---------- what counts as a real list ----------

def test_epoch_reads_every_stamp_reddit_uses_even_on_python_310():
    assert epoch("2026-09-09T06:46:14.641000+0000") == epoch("2026-09-09T06:46:14.641+00:00")   # page
    assert epoch("2026-09-20T10:00:00+00:00") == datetime(2026, 9, 20, 10, tzinfo=timezone.utc).timestamp()
    assert epoch("2026-09-20T06:00:00-0400") == epoch("2026-09-20T10:00:00Z")
    assert epoch(1758880000.0) == 1758880000.0                                                   # JSON
    assert epoch("") is None and epoch(None) is None and epoch("junk") is None
    assert epoch("2026-09-20T10:00:00") is None and epoch(True) is None      # no zone = unknown, not local


def test_a_real_list_passes():
    assert list_problem([post(i) for i in range(50)], "LifeProTips", "month",
                        url="https://www.reddit.com/r/LifeProTips/top/?solution=x&js_challenge=1&t=month",
                        now=NOW) == ""
    # Reddit's own capitalisation of the sub differs from ours: still the right list.
    assert list_problem([post(i, sub="personalfinance") for i in range(9)], "PersonalFinance", "year",
                        url="https://www.reddit.com/r/personalfinance/top.json?t=year&limit=50", now=NOW) == ""


def test_a_redirect_or_login_wall_is_caught():
    raw = [post(i) for i in range(50)]
    for url in ("https://www.reddit.com/login/?dest=x", "https://www.reddit.com/r/LifeProTips/?t=month",
                "https://www.reddit.com/r/LifeProTips/top/?t=year", "https://www.reddit.com/r/Other/top/?t=month"):
        assert "not the top list" in list_problem(raw, "LifeProTips", "month", url=url, now=NOW), url


def test_another_subs_posts_are_caught():
    raw = [post(i) for i in range(40)] + [post(i, sub="popular") for i in range(40, 51)]
    assert "11 of 51 posts are from other subs" in list_problem(raw, "LifeProTips", "month", now=NOW)
    assert list_problem(raw[:45], "LifeProTips", "month", now=NOW) == ""       # 5 of 45 is noise, not a swap


def test_an_older_list_is_caught():
    all_time = [post(i, age_days=900) for i in range(50)]
    assert "older than a month" in list_problem(all_time, "LifeProTips", "month", now=NOW)
    assert "older than a year" in list_problem(all_time, "LifeProTips", "year", now=NOW)
    assert list_problem([post(i, age_days=200) for i in range(50)], "LifeProTips", "year", now=NOW) == ""
    assert list_problem([post(i, created="") for i in range(50)], "LifeProTips", "month", now=NOW) == ""


def test_a_layout_change_that_drops_the_upvotes_is_caught():
    no_scores = [post(i, score="") for i in range(50)]
    assert "show upvotes" in list_problem(no_scores, "LifeProTips", "month", now=NOW)
    assert list_problem(no_scores, "LifeProTips", "month", upvotes=False, now=NOW) == ""   # RSS never has them
    some_hidden = [post(i, score="" if i < 10 else "5") for i in range(50)]
    assert list_problem(some_hidden, "LifeProTips", "month", now=NOW) == ""


# ---------- the three readers' parsers ----------

def test_json_listing_becomes_page_shaped_posts():
    raw, complete = raw_from_json(listing(6))
    assert [p["id"] for p in raw] == ["t3_j1", "t3_j2", "t3_j3", "t3_j4", "t3_j5"]    # stickied dropped
    assert raw[0]["score"] == 899 and raw[1]["body"] == "body" and raw[1]["type"] == "text"
    assert raw[2]["type"] == "video" and raw[0]["sub"] == "LifeProTips" and complete is False
    rows = rb.rows_from_page(raw, "LifeProTips")
    assert [r["id"] for r in rows] == ["j1", "j2", "j4", "j5"] and rows[0]["upvotes"] == 899
    assert rows[0]["title"] == "J &amp; 1"      # raw_json=1 in the real URL means no &amp; to undo
    assert raw_from_json(listing(3, after=None))[1] is True


def test_junk_instead_of_json_raises_so_the_next_method_runs():
    for junk in ({}, [], {"data": {"children": "x"}}, "html"):
        try:
            raw_from_json(junk)
        except ValueError:
            continue
        raise AssertionError(f"accepted {junk!r}")


def test_rss_becomes_page_shaped_posts_with_text_and_no_upvotes():
    raw = raw_from_rss(RSS)
    assert [p["id"] for p in raw] == ["t3_r1", "t3_r2"] and raw[0]["sub"] == "LifeProTips"
    assert raw[0]["body"] == "First & line. inner Last." and raw[1]["body"] == ""
    assert raw[0]["score"] == "" and epoch(raw[0]["created"]) is not None
    rows = rb.rows_from_page(raw, "LifeProTips")
    assert rows[1]["permalink"] == "https://www.reddit.com/r/LifeProTips/comments/r2/y/" and rows[1]["upvotes"] == ""
    assert list_problem(raw, "LifeProTips", "month", upvotes=False, complete=True, now=NOW) == ""


# ---------- the ladder ----------

class FakePage:
    """Enough of a Playwright page for read_one(): warm-ups are counted, not loaded."""
    def __init__(self):
        self.warmups = 0

    async def goto(self, *a, **k):
        self.warmups += 1

    async def wait_for_timeout(self, ms):
        pass


def ladder(monkeypatch, **replies):
    """Stub each method: a list = those posts, an Exception = that error."""
    calls = []

    def reader(name):
        async def read(page, sub, t):
            calls.append(name)
            r = replies[name]
            if isinstance(r, Exception):
                raise r
            raw, upvotes, complete = r
            return {"raw": raw, "url": f"https://www.reddit.com/r/{sub}/top/?t={t}", "upvotes": upvotes,
                    "complete": complete}
        return read
    monkeypatch.setattr(rb, "READERS", {m: reader(m) for m in replies})
    return calls


def run_one(methods=rb.METHODS):
    page = FakePage()
    return asyncio.run(rb.read_one(page, "LifeProTips", "month", methods)), page


def fresh(n, **kw):
    return [post(i, created=time.time() - DAY, **kw) for i in range(n)]


def test_page_works_so_no_backup_is_touched(monkeypatch):
    calls = ladder(monkeypatch, page=(fresh(50), True, False), json=RuntimeError("x"), rss=RuntimeError("x"))
    r, _ = run_one()
    assert r["method"] == "page" and len(r["rows"]) == 50 and calls == ["page"] and r["tries"] == []


def test_blocked_page_falls_back_to_json_with_real_upvotes(monkeypatch):
    calls = ladder(monkeypatch, page=([], True, False), json=(fresh(50), True, False), rss=RuntimeError("x"))
    r, page = run_one()
    assert r["method"] == "json" and r["rows"][0]["upvotes"] == 100
    assert calls == ["page", "page", "json"] and page.warmups == 1        # page retried once after a warm-up
    assert r["page_blocked"] and r["tries"] == ["page: no posts"]


def test_layout_change_falls_back_past_json_to_rss(monkeypatch):
    calls = ladder(monkeypatch, page=(fresh(50, score=""), True, False), json=RuntimeError("HTTP 403"),
                   rss=(fresh(50, score=""), False, False))
    r, _ = run_one()
    assert r["method"] == "rss" and r["rows"][0]["upvotes"] == ""         # the site shows the rank instead
    assert calls == ["page", "page", "json", "rss"]
    assert "show upvotes" in r["tries"][0] and r["tries"][1] == "json: RuntimeError: HTTP 403"


def test_short_real_list_is_saved_via_json_without_retrying_the_page(monkeypatch):
    calls = ladder(monkeypatch, page=(fresh(3), True, False), json=(fresh(3), True, True), rss=RuntimeError("x"))
    r, page = run_one()
    assert r["method"] == "json" and len(r["rows"]) == 3 and page.warmups == 0 and calls == ["page", "json"]
    assert not r["page_blocked"] and r["reached"]


def test_everything_fails_keeps_the_old_file_and_says_why(monkeypatch):
    ladder(monkeypatch, page=([], True, False), json=RuntimeError("HTTP 403"), rss=RuntimeError("HTTP 429"))
    r, _ = run_one()
    assert r["method"] is None and r["rows"] == [] and not r["reached"] and r["page_blocked"]
    assert r["tries"] == ["page: no posts", "json: RuntimeError: HTTP 403", "rss: RuntimeError: HTTP 429"]


def test_all_videos_is_not_a_saved_list(monkeypatch):
    ladder(monkeypatch, page=(fresh(9, type="video"), True, False), json=(fresh(9, type="video"), True, False),
           rss=RuntimeError("x"))
    r, _ = run_one()
    assert r["method"] is None and r["reached"] and "none readable" in r["tries"][0]


def test_forcing_one_method_runs_only_that_one(monkeypatch):
    calls = ladder(monkeypatch, page=RuntimeError("x"), json=RuntimeError("x"), rss=(fresh(50), False, False))
    r, _ = run_one(("rss",))
    assert r["method"] == "rss" and calls == ["rss"]


def test_a_short_rss_list_alone_is_not_trusted(monkeypatch):
    # 3 entries could be a broken feed; saving it would wipe a 50-post file and
    # stamp the list fresh, so GitHub's backup would leave it alone for 36 h.
    ladder(monkeypatch, page=([], True, False), json=RuntimeError("HTTP 403"), rss=(fresh(3, score=""), False, True))
    r, _ = run_one()
    assert r["method"] is None and r["tries"][-1] == "rss: too short: 3 posts"


def test_a_short_rss_list_is_trusted_once_the_page_saw_it_short(monkeypatch):
    ladder(monkeypatch, page=(fresh(3), True, False), json=RuntimeError("HTTP 403"), rss=(fresh(3, score=""), False, True))
    r, _ = run_one()
    assert r["method"] == "rss" and len(r["rows"]) == 3


def test_a_page_that_keeps_failing_is_not_retried(monkeypatch):
    calls = ladder(monkeypatch, page=([], True, False), json=(fresh(50), True, False), rss=RuntimeError("x"))
    page = FakePage()
    r = asyncio.run(rb.read_one(page, "LifeProTips", "month", rb.METHODS, retry_page=False))
    assert r["method"] == "json" and calls == ["page", "json"] and page.warmups == 0


# ---------- a profile that won't open ----------

class FakeChromium:
    def __init__(self, bad):
        self.bad, self.opened = bad, []

    async def launch_persistent_context(self, path, **kw):
        self.opened.append(path)
        if path == self.bad:
            raise RuntimeError("ProcessSingleton: profile appears to be in use")
        return "ctx"


def test_a_stuck_profile_gets_its_locks_cleared_then_a_throwaway_one(tmp_path, capsys):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "SingletonLock").symlink_to("host-12345")                  # dangling, like a killed run leaves
    p = type("P", (), {})()
    p.chromium = FakeChromium(bad=str(profile))
    ctx, tmp = asyncio.run(rb.open_browser(p, profile, False))
    assert ctx == "ctx" and tmp is not None and tmp != profile
    assert p.chromium.opened == [str(profile), str(profile), str(tmp)]
    assert not (profile / "SingletonLock").is_symlink()                  # locks cleared before the retry
    assert "fresh throwaway profile" in capsys.readouterr().out
    tmp.rmdir()


def test_a_healthy_profile_is_kept(tmp_path):
    p = type("P", (), {})()
    p.chromium = FakeChromium(bad=None)
    assert asyncio.run(rb.open_browser(p, tmp_path / "profile", False)) == ("ctx", None)


# ---------- a whole run, browser stubbed ----------

class FakePlaywright:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def fake_run(monkeypatch, result, subs):
    """rb.run() with no browser: result(sub, t, session_no) gives read_one's answer."""
    mod = type(sys)("playwright.async_api")
    mod.async_playwright = FakePlaywright
    monkeypatch.setitem(sys.modules, "playwright", type(sys)("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.async_api", mod)
    sessions, calls = [], []

    async def new_session(p, profile, visible):
        sessions.append(profile)
        return "ctx", None, FakePage()

    async def close_session(ctx, tmp):
        pass

    async def read_one(page, sub, t, methods, retry_page=True):
        calls.append((f"{sub}/{t}", tuple(methods), retry_page))
        return result(sub, t, len(sessions))

    async def try_method(page, m, sub, t, complete_ok=True):
        return None, ""
    for name, fn in [("new_session", new_session), ("close_session", close_session), ("read_one", read_one),
                     ("try_method", try_method), ("write_list", lambda rows, key: None),
                     ("update_meta", lambda *a, **k: None)]:
        monkeypatch.setattr(rb, name, fn)
    return asyncio.run(rb.run(Path("profile"), subs, False)), calls, sessions


def outcome(method, page_blocked):
    return {"method": method, "rows": [{"selftext": "", "upvotes": 5}] if method else [],
            "tries": [] if method else ["page: no posts"], "reached": bool(method), "page_blocked": page_blocked}


def test_a_page_layout_change_still_leaves_time_for_json_on_every_list(monkeypatch):
    # The page finds no posts anywhere; json works. Page retries stop after 2 misses,
    # one fresh profile is tried after 4, and after 4 more the page is skipped.
    out, calls, sessions = fake_run(monkeypatch, lambda sub, t, n: outcome("json", True), list("abcdef"))
    assert sessions == [Path("profile"), None]                          # one fresh-profile switch
    assert [c[2] for c in calls[:4]] == [True, True, False, False]      # page retry dropped after 2 misses
    assert calls[7][1] == rb.METHODS and calls[8][1] == ("json", "rss")  # page skipped once fresh failed too
    assert len(calls) == 12 and set(out["via"].values()) == {"json"} and out["failed"] == []


def test_a_list_saved_via_rss_is_not_also_reported_as_kept_old(monkeypatch, capsys):
    # First profile: page blocked, RSS saves all 4. Fresh profile retries them and fails.
    out, calls, sessions = fake_run(monkeypatch, lambda sub, t, n: outcome("rss" if n == 1 else None, True), ["a", "b"])
    assert len(calls) == 8 and len(out["saved"]) == 4 and out["failed"] == []
    printed = capsys.readouterr().out
    assert printed.count("Stopping.") == 1                              # 4 misses on the fresh profile
    assert "json: not checked (Reddit blocked this run)" in printed     # no canary after a block


def test_the_deadline_is_announced_once(monkeypatch, capsys):
    monkeypatch.setattr(rb, "RUN_DEADLINE_S", -1)
    out, calls, _ = fake_run(monkeypatch, lambda sub, t, n: outcome("page", False), ["a", "b"])
    assert calls == [] and len(out["failed"]) == 4
    assert capsys.readouterr().out.count("limit: stopping") == 1


# ---------- the canary line fleet-health reads ----------

def test_method_check_line_is_green_only_when_every_method_works():
    assert re.search(FLEET_METHODS_RE, method_check_line(26, 26, {"json": "", "rss": ""}))
    assert re.search(FLEET_METHODS_RE, method_check_line(13, 26, {"json": "", "rss": ""}))
    line = method_check_line(12, 26, {"json": "", "rss": ""})
    assert not re.search(FLEET_METHODS_RE, line) and "page FAILING" in line
    line = method_check_line(26, 26, {"json": "RuntimeError: HTTP 403", "rss": ""})
    assert not re.search(FLEET_METHODS_RE, line) and "json FAILED" in line and "HTTP 403" in line
    assert not re.search(FLEET_METHODS_RE, method_check_line(0, 0, {"json": "", "rss": ""}))


# ---------- GitHub's backup: small batches, stalest first, then move on ----------

def test_github_backup_takes_stalest_lists_first_and_skips_its_own_recent_ones():
    now = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    all_keys = {f"r_{s}{y}" for s in scrape_top.SUBREDDITS for y in ("", "_yearly")}
    mac = {k: "2026-09-27T07:35:00Z" for k in all_keys}                          # Mac fine...
    mac["r_bestof"] = "2026-09-20T07:35:00Z"                                     # ...except these two
    mac["r_lifehacks_yearly"] = "2026-09-22T07:35:00Z"
    del mac["r_getmotivated"]                                                   # never saved
    todo = scrape_top.stale_lists(mac, {}, now)
    assert todo == [("getmotivated", "month"), ("bestof", "month"), ("lifehacks", "year")]
    # This backup refreshed r/bestof 2 h ago: it waits, the next stalest goes first.
    assert scrape_top.stale_lists(mac, {"r_bestof": "2026-09-27T10:00:00Z"}, now) == [
        ("getmotivated", "month"), ("lifehacks", "year")]
    # Refreshed 13 h ago: due again, but after lists nobody has touched for longer.
    assert scrape_top.stale_lists(mac, {"r_getmotivated": "2026-09-26T23:00:00Z"}, now)[-1] == ("getmotivated", "month")


def test_github_backup_stamps_its_own_file(tmp_path):
    path = tmp_path / "reddit_github.json"
    path.write_text("{broken")
    scrape_top.stamp_github_meta("r_bestof", path)
    scrape_top.stamp_github_meta("r_AskHistorians", path)
    assert set(scrape_top.load_github_meta(path)) == {"r_bestof", "r_AskHistorians"}
    assert scrape_top.load_github_meta(tmp_path / "missing.json") == {}


def test_github_backup_with_nothing_stale_still_proves_rss_works(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "data/reddit_browser.json").write_text(json.dumps({"lists": {
        f"r_{s}{y}": stamp for s in scrape_top.SUBREDDITS for y in ("", "_yearly")}}))
    monkeypatch.setattr(scrape_top, "fetch_via_rss", lambda sub, t: [{"id": "x"}] * 50)
    monkeypatch.setattr(sys, "argv", ["scrape_top.py", "--max-lists", "6"])
    scrape_top.main()
    out = capsys.readouterr().out
    assert "REDDIT BACKUP: refreshed 0 of 0" in out and re.search(r"GITHUB REDDIT CHECK: rss ok \(r/\w+: 50 posts\)", out)
    assert not list((tmp_path / "data").glob("r_*"))                            # the check writes nothing


def test_github_backup_refreshes_a_batch_and_says_how_many(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(scrape_top.time, "sleep", lambda s: None)
    got = []
    monkeypatch.setattr(scrape_top, "fetch_reddit_posts",
                        lambda sub, t: got.append((sub, t)) or ([] if sub == "todayilearned" else [
                            {"id": "a", "title": "t", "selftext": "", "permalink": "p", "score": 1, "score_real": False}]))
    monkeypatch.setattr(sys, "argv", ["scrape_top.py", "--max-lists", "3"])
    scrape_top.main()                                                            # no Mac json at all
    out = capsys.readouterr().out
    assert len(got) == 3 and "REDDIT BACKUP: refreshed 2 of 22 lists that needed it (tried 3)" in out
    assert "GITHUB REDDIT CHECK" not in out
    assert len(scrape_top.load_github_meta(tmp_path / "data/reddit_github.json")) == 2


def rss_feed(n, sub="LifeProTips"):
    when = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    entries = "".join(f'<entry><category term="{sub}"/><id>t3_g{i}</id><title>Post {i}</title>'
                      f'<link href="https://www.reddit.com/r/{sub}/comments/g{i}/x/"/><published>{when}</published>'
                      f'<content type="html">x</content></entry>' for i in range(n))
    return f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'.encode()


class FakeResponse:
    def __init__(self, content, url):
        self.status_code, self.content, self.url = 200, content, url

    def raise_for_status(self):
        pass


def test_github_backup_saves_only_a_real_top_list(monkeypatch):
    url = "https://www.reddit.com/r/LifeProTips/top/.rss?t=month&limit=50"
    for content, got_url, saved in [(rss_feed(30), url, 30),
                                    (rss_feed(30, sub="funny"), url, 0),                       # another sub
                                    (rss_feed(3), url, 0),                                     # near-empty feed
                                    (rss_feed(30), "https://www.reddit.com/login/?reason=lor2", 0)]:
        monkeypatch.setattr(scrape_top.requests, "get", lambda *a, **k: FakeResponse(content, got_url))
        assert len(scrape_top.fetch_via_rss("LifeProTips", "month")) == saved


def test_github_backup_script_actually_runs_main():
    # 26 Sep 2026: a lost `if __name__ == "__main__"` made the workflow a silent no-op.
    out = subprocess.run([sys.executable, str(ROOT / "core" / "scrape_top.py"), "--help"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and "--max-lists" in out.stdout
