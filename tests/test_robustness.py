"""Robustness tests: a broken or missing file never empties the wrong tab, and the
Mac mini's job survives overlaps, push races, half-done rebases and a big log.

run: .venv/bin/python -m pytest tests -q   (the wrapper tests need bash, git, timeout)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))

import server
from fastapi.testclient import TestClient
from reddit_common import SUBREDDITS
from scrape_reddit_browser import MIN_POSTS, page_ok, rows_from_page, update_meta, write_list


# ---------- server: one bad file costs one tab, never the others ----------

def mac_posts(sub, prefix, n=8):
    """What the Mac's browser sees on one top page, as rows."""
    raw = [{"id": f"t3_{prefix}{i}", "score": str(2000 - i), "comments": "5", "title": f"{sub} post {i}",
            "type": "text", "link": f"/r/{sub}/comments/{prefix}{i}/x/", "body": "some text"}
           for i in range(n)]
    return rows_from_page(raw, sub)


def fresh_news_csv():
    now = datetime.now(timezone.utc)
    rows = ["article_id,title,url,description,pub_date,author,category,scraped_at"]
    for i in range(3):
        when = (now - timedelta(hours=i + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append(f"n{i},Headline number {i},https://example.com/{i},Blurb,{when},WSJ,business,{when}")
    return "\n".join(rows) + "\n"


@pytest.fixture
def site(tmp_path, monkeypatch):
    """server.py pointed at a throwaway data/ folder: 1 tracked sub, 1 dropped sub."""
    data = tmp_path / "data"
    write_list(mac_posts("LifeProTips", "m"), "r_LifeProTips", root=data)
    write_list(mac_posts("LifeProTips", "y"), "r_LifeProTips_yearly", root=data)
    write_list(mac_posts("Fitness", "f", 3), "r_Fitness", root=data)          # no longer tracked
    (data / "reddit_browser.json").write_text(json.dumps({"lists": {
        "r_LifeProTips": "2026-09-26T11:35:00+00:00",
        "r_LifeProTips_yearly": "2026-09-25T23:35:00+00:00",
        "r_Fitness": "2026-09-27T00:00:00+00:00",                             # newest, but untracked
    }}))
    monkeypatch.setattr(server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(server, "BROWSER_META", data / "reddit_browser.json")
    return data


def put(data, rel, text):
    p = data / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text) if isinstance(text, str) else p.write_bytes(text)


def test_broken_news_and_missing_am_reads_leave_reddit_alone(site):
    put(site, "googlenews/articles.csv", b"\x00\xff garbage \"unclosed\n\x01,,\n")
    d = server.get_data()
    assert d["news"] == [] and d["ritholtz"] == []
    assert len(d["monthly"]) == 8 and len(d["yearly"]) == 8
    assert d["monthly"][0]["upvotes"] == "2.0k" and d["monthly"][0]["rank"] == 1


def test_dropped_sub_is_hidden_and_its_stamp_ignored(site):
    d = server.get_data()
    assert not any(i["source"] == "r/Fitness" for i in d["monthly"] + d["yearly"])
    assert d["updated"]["reddit"] == "2026-09-26T11:35:00+00:00"   # newest TRACKED stamp


def test_csv_without_a_title_column_is_skipped(site):
    put(site, "r_todayilearned/posts.csv", "id,score\n1,5\n2,4\n")
    d = server.get_data()
    assert len(d["monthly"]) == 8
    assert not any(i["source"] == "r/todayilearned" for i in d["monthly"])


def test_one_junk_number_costs_one_row_not_both_tabs(site):
    put(site, "r_LifeProTips/posts.csv",
        (site / "r_LifeProTips/posts.csv").read_text() + "zz1,Huge post,,/r/x/,1e400,1e400,3,False\n")
    d = server.get_data()
    assert len(d["monthly"]) == 9 and len(d["yearly"]) == 8
    huge = next(i for i in d["monthly"] if i["id"] == "zz1")
    assert huge["upvotes"] == ""                          # rank shown, never "inf"


def test_reddit_crash_still_serves_news(site, monkeypatch):
    put(site, "googlenews/articles.csv", fresh_news_csv())
    monkeypatch.setattr(server, "load_reddit_frames", lambda: 1 / 0)
    d = server.get_data()
    assert d["monthly"] == [] and d["yearly"] == []
    assert len(d["news"]) == 3


def test_status_endpoint_lists_oldest_first_and_names_missing_lists(site):
    s = TestClient(server.app).get("/api/status").json()
    assert [r["list"] for r in s["reddit_lists"]] == ["r_LifeProTips_yearly", "r_LifeProTips"]
    assert s["reddit_lists"][0] == {"list": "r_LifeProTips_yearly", "saved": "2026-09-25T23:35:00+00:00",
                                    "checked": ""}          # old json: no `checked` yet
    assert s["reddit_oldest"] == "2026-09-25T23:35:00+00:00"
    assert s["tracked_subs"] == len(SUBREDDITS)
    assert len(s["reddit_missing"]) == 2 * len(SUBREDDITS) - 2
    assert "r_todayilearned_yearly" in s["reddit_missing"] and "r_LifeProTips" not in s["reddit_missing"]
    assert s["counts"] == {"monthly": 8, "yearly": 8, "news": 0, "ritholtz": 0}


def test_status_grades_checked_so_a_short_list_is_not_stale(site):
    # r/lifehacks can have < MIN_POSTS posts: the Mac reaches it but doesn't save it.
    update_meta({"r_LifeProTips": "2026-09-26T11:35:00+00:00"}, site / "reddit_browser.json")
    update_meta({}, site / "reddit_browser.json", checked={"r_lifehacks": "2026-09-26T11:36:00+00:00"})
    rows = {r["list"]: r for r in server.status()["reddit_lists"]}
    assert rows["r_lifehacks"] == {"list": "r_lifehacks", "saved": "", "checked": "2026-09-26T11:36:00+00:00"}
    assert rows["r_LifeProTips"]["checked"] == rows["r_LifeProTips"]["saved"]   # saved implies reached
    assert "r_lifehacks" in server.status()["reddit_missing"]                   # still never saved


def test_broken_browser_json_means_no_stamps_not_a_crash(site):
    (site / "reddit_browser.json").write_text("{not json")
    s = server.status()
    assert s["reddit_lists"] == [] and s["reddit_oldest"] == "" and s["updated"]["reddit"] == ""
    assert len(s["reddit_missing"]) == 2 * len(SUBREDDITS)
    assert len(server.get_data()["monthly"]) == 8          # the lists themselves still show


# ---------- Mac scraper: what counts as a real page ----------

def test_page_ok_accepts_small_real_lists_and_rejects_broken_pages():
    small = [{"id": f"t3_s{i}", "title": f"t{i}", "type": "text"} for i in range(MIN_POSTS)]
    assert page_ok(small, rows_from_page(small, "lifehacks"))         # r/lifehacks: 7 posts in Sep 2026
    few = small[:MIN_POSTS - 1]
    assert not page_ok(few, rows_from_page(few, "lifehacks"))         # a challenge/error page
    videos = [dict(p, type="video") for p in small * 10]
    assert not page_ok(videos, rows_from_page(videos, "lifehacks"))   # nothing readable


def test_update_meta_merges_and_survives_a_broken_file(tmp_path):
    meta = tmp_path / "reddit_browser.json"
    meta.write_text("{broken")
    update_meta({"r_A": "2026-09-26T00:00:00+00:00"}, meta)
    update_meta({"r_B": "2026-09-26T01:00:00+00:00"}, meta)
    assert json.loads(meta.read_text())["lists"] == {"r_A": "2026-09-26T00:00:00+00:00",
                                                     "r_B": "2026-09-26T01:00:00+00:00"}
    update_meta({}, meta, checked={"r_C": "2026-09-26T02:00:00+00:00"})
    m = json.loads(meta.read_text())
    assert "r_C" not in m["lists"] and set(m["checked"]) == {"r_A", "r_B", "r_C"}
    meta.write_text("[1, 2]")                               # valid JSON, wrong shape
    update_meta({"r_D": "x"}, meta)
    assert json.loads(meta.read_text())["lists"] == {"r_D": "x"}


# ---------- Mac wrapper (mac/reddit-browser.sh) against a local git "GitHub" ----------

WRAPPER = ROOT / "mac" / "reddit-browser.sh"
# The exact patterns fleet-health's reddit-browser row greps for: if the log
# format drifts, these tests fail before the monitor goes blind.
FLEET_BLOCK_RE = r"^== (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) start"
FLEET_SUCCESS_RE = r"REDDIT PUSHED: [1-9]\d* files|NO REDDIT CHANGES \(scraper exit 0\)"

FAKE_SCRAPER = '''"""Stands in for the real browser scrape in tests/test_robustness.py."""
import json, os, pathlib, subprocess, sys
if os.environ.get("FAKE_FAIL"):
    print("BROWSER SAVED: 0 of 1 lists"); sys.exit(1)
rows = os.environ.get("FAKE_ROWS", "a")
p = pathlib.Path("data/r_Test/posts.csv"); p.parent.mkdir(parents=True, exist_ok=True)
p.write_text("id,title\\n" + rows + ",Title\\n")
pathlib.Path("data/reddit_browser.json").write_text(json.dumps({"lists": {"r_Test": rows}}))
race = os.environ.get("FAKE_RACE")
if race:  # another job (GitHub's scrape) pushes while this one is scraping
    pathlib.Path(race, "news.txt").write_text(rows)
    for cmd in (["add", "news.txt"], ["commit", "-qm", "other job"], ["push", "-q", "origin", "HEAD:main"]):
        subprocess.run(["git", "-C", race] + cmd, check=True)
print("BROWSER SAVED: 1 of 1 lists")
'''

needs_tools = pytest.mark.skipif(
    not all(shutil.which(t, path="/opt/homebrew/bin:/usr/bin:/bin") for t in ("bash", "git", "timeout")),
    reason="wrapper tests need bash, git and timeout on the wrapper's PATH")


def git(*args, cwd=None, env=None, check=True):
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=check, capture_output=True, text=True)


@pytest.fixture
def mac(tmp_path):
    """A bare repo standing in for GitHub, plus the env that points the wrapper at it."""
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    seed = tmp_path / "seed"
    (seed / "core").mkdir(parents=True)
    (seed / "core" / "scrape_reddit_browser.py").write_text(FAKE_SCRAPER)
    (seed / ".gitignore").write_text("data/\n")                     # like the real repo
    (seed / "README.md").write_text("seed\n")
    git("init", "-q", "-b", "main", cwd=seed, env=env)
    git("add", "-A", cwd=seed, env=env)
    git("commit", "-qm", "seed", cwd=seed, env=env)
    bare = tmp_path / "origin.git"
    git("clone", "-q", "--bare", str(seed), str(bare), env=env)
    base, log = tmp_path / "base", tmp_path / "logs" / "reddit-browser.log"
    env.update(REDDIT_BROWSER_BASE=str(base), REDDIT_BROWSER_LOG=str(log), REDDIT_BROWSER_REMOTE=str(bare),
               REDDIT_BROWSER_PY=sys.executable, REDDIT_BROWSER_RETRY_SLEEP="0")

    class Mac:
        def run(self, **extra):
            r = subprocess.run(["bash", str(WRAPPER)], env={**env, **extra}, timeout=120)
            return r.returncode, log.read_text() if log.exists() else ""

        def last_block(self):
            text = log.read_text()
            return text[list(re.finditer(FLEET_BLOCK_RE, text, re.M))[-1].start():]

        def other_clone(self, name="other"):
            path = tmp_path / name
            git("clone", "-q", str(bare), str(path), env=env)
            return path

        def origin_file(self, path):
            return git("--git-dir", str(bare), "show", f"main:{path}", env=env, check=False).stdout

        def origin_log(self):
            return git("--git-dir", str(bare), "log", "--format=%s", "main", env=env).stdout

    m = Mac()
    m.env, m.base, m.log, m.clone = env, base, log, base / "reddit-scraper"
    return m


@needs_tools
def test_wrapper_first_run_clones_commits_pushes_in_the_monitored_format(mac):
    rc, _ = mac.run()
    block = mac.last_block()
    assert rc == 0, block
    assert re.search(r"REDDIT PUSHED: 2 files in \w+ \(scraper exit 0\)", block)
    assert re.search(FLEET_SUCCESS_RE, block)
    assert mac.origin_file("data/r_Test/posts.csv") == "id,title\na,Title\n"   # data/ is gitignored: add -f
    assert not (mac.base / "run.lock").exists()


@needs_tools
def test_wrapper_no_change_is_green_but_a_failed_scrape_is_not(mac):
    mac.run()
    rc, _ = mac.run()
    assert rc == 0 and "NO REDDIT CHANGES (scraper exit 0)" in mac.last_block()
    rc, _ = mac.run(FAKE_FAIL="1")
    block = mac.last_block()
    assert rc == 1 and "NO REDDIT CHANGES (scraper exit 1)" in block
    assert not re.search(FLEET_SUCCESS_RE, block)            # fleet-health goes red


@needs_tools
def test_wrapper_skips_while_another_run_holds_the_lock_and_takes_over_a_dead_one(mac):
    lock = mac.base / "run.lock"
    lock.mkdir(parents=True)
    rc, _ = mac.run()
    assert rc == 0 and "ANOTHER RUN IS ACTIVE" in mac.last_block()
    assert lock.exists() and mac.origin_file("data/r_Test/posts.csv") == ""   # never touched
    old = time.time() - 3600                                                   # killed an hour ago
    os.utime(lock, (old, old))
    rc, _ = mac.run()
    assert rc == 0 and "old lock from a killed run" in mac.last_block()
    assert "REDDIT PUSHED" in mac.last_block() and not lock.exists()


@needs_tools
def test_wrapper_rebases_and_retries_when_another_job_pushed_first(mac):
    other = mac.other_clone()
    rc, _ = mac.run(FAKE_RACE=str(other), FAKE_ROWS="b")
    assert rc == 0, mac.last_block()
    assert mac.origin_log().split("\n")[:2] == ["Reddit via Mac browser: 2 files", "other job"]
    assert mac.origin_file("news.txt") == "b" and mac.origin_file("data/r_Test/posts.csv") == "id,title\nb,Title\n"


@needs_tools
def test_wrapper_recovers_a_clone_left_mid_rebase(mac):
    mac.run()
    other = mac.other_clone()
    (other / "README.md").write_text("theirs\n")
    git("commit", "-qam", "theirs", cwd=other, env=mac.env)
    git("push", "-q", "origin", "HEAD:main", cwd=other, env=mac.env)
    (mac.clone / "README.md").write_text("ours\n")
    git("commit", "-qam", "ours", cwd=mac.clone, env=mac.env)
    git("fetch", "-q", "origin", cwd=mac.clone, env=mac.env)
    git("rebase", "origin/main", cwd=mac.clone, env=mac.env, check=False)     # conflicts, stops
    assert (mac.clone / ".git" / "rebase-merge").exists() or (mac.clone / ".git" / "rebase-apply").exists()
    rc, _ = mac.run(FAKE_ROWS="c")
    assert rc == 0, mac.last_block()
    assert mac.origin_file("data/r_Test/posts.csv") == "id,title\nc,Title\n"
    assert mac.origin_file("README.md") == "theirs\n"         # the half-done local commit is dropped


@needs_tools
def test_wrapper_clears_a_stale_git_lock_and_reclones_a_broken_clone(mac):
    mac.run()
    (mac.clone / ".git" / "index.lock").write_text("")          # git killed mid-write
    rc, _ = mac.run(FAKE_ROWS="d")
    assert rc == 0 and "REDDIT PUSHED" in mac.last_block(), mac.last_block()
    assert "cloning it again" not in mac.last_block()           # cleared in place, no re-clone
    shutil.rmtree(mac.clone / ".git" / "objects")              # clone damaged beyond repair
    rc, _ = mac.run(FAKE_ROWS="e")
    block = mac.last_block()
    assert rc == 0 and "clone looks broken: cloning it again" in block, block
    assert mac.origin_file("data/r_Test/posts.csv") == "id,title\ne,Title\n"


@needs_tools
def test_wrapper_trims_a_big_log_in_place(mac):
    mac.log.parent.mkdir(parents=True)
    mac.log.write_text(("old line " + "x" * 60 + "\n") * 10000)                # ~700 KB
    rc, text = mac.run()
    assert rc == 0
    assert len(text.splitlines()) < 3100 and "REDDIT PUSHED" in mac.last_block()
