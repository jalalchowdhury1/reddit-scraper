"""AM Reads + SatPost exit codes (25 Oct 2026): a real failure (blocked, 403, a
Cloudflare 'Just a moment' page, no post found) exits 1 with one fixed last line, so
the workflows go red; 'no new post today' (a Sunday, before 06:30 ET) stays 0.

run: .venv/bin/python -m pytest tests -q
"""
import json
import os
import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import scrape_ritholtz as rt
import scrape_trung as tr

SAT_POST = "https://ritholtz.com/2026/10/weekend-reads-683/"
CHALLENGE = ('<!DOCTYPE html><html><head><title>Just a moment...</title></head><body>'
             '<script src="https://challenges.cloudflare.com/x.js"></script></body></html>')


class Resp:
    def __init__(self, body, code=200):
        self.content = body.encode()
        self.status_code = code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error")


class Session:
    def __init__(self, pages):
        self.pages, self.headers = pages, {}

    def get(self, url, timeout=None):
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        return page if isinstance(page, Resp) else Resp(page)


def post_html(n=3):
    items = "".join(f'<li><a href="https://ex.com/{i}">WSJ</a> Title {i} : blurb {i}</li>' for i in range(n))
    return ('<meta property="article:published_time" content="2026-10-24T10:30:00+00:00">'
            f'<div class="entry-content"><ul>{items}</ul></div>')


def run_rt(monkeypatch, tmp_path, capsys, pages):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rt.requests, "Session", lambda: Session(pages))
    monkeypatch.setattr(rt.time, "sleep", lambda s: None)
    code = rt.main()
    return code, capsys.readouterr().out.strip().splitlines()[-1]


def category(*posts):
    return "".join(f'<a href="{p}">Weekend Reads</a>' for p in posts)


def test_normal_run_exits_0_and_saves(monkeypatch, tmp_path, capsys):
    code, _ = run_rt(monkeypatch, tmp_path, capsys, {rt.CATEGORY_URL: category(SAT_POST), SAT_POST: post_html()})
    assert code == 0 and (tmp_path / "data/ritholtz/articles.csv").exists()


def test_sunday_rerun_of_saturdays_post_exits_0(monkeypatch, tmp_path, capsys):
    """No new post on a Sunday (or before 06:30 ET): the newest is the one already
    served. Nothing to save, and that is not a failure."""
    pages = {rt.CATEGORY_URL: category(SAT_POST), SAT_POST: post_html()}
    assert run_rt(monkeypatch, tmp_path, capsys, pages)[0] == 0
    code, last = run_rt(monkeypatch, tmp_path, capsys, pages)
    assert code == 0 and "FAILED" not in last


def test_new_post_whose_links_all_ran_before_exits_0(monkeypatch, tmp_path, capsys):
    """Every link already shown by an earlier post: nothing new to show, not broken."""
    other = "https://ritholtz.com/2026/10/10-friday-am-reads-9/"
    run_rt(monkeypatch, tmp_path, capsys, {rt.CATEGORY_URL: category(other), other: post_html()})
    code, last = run_rt(monkeypatch, tmp_path, capsys, {rt.CATEGORY_URL: category(SAT_POST), SAT_POST: post_html()})
    assert code == 0 and "FAILED" not in last


@pytest.mark.parametrize("pages, why", [
    ({rt.CATEGORY_URL: Resp(CHALLENGE, 403)}, "Cloudflare challenge"),
    ({rt.CATEGORY_URL: Resp(CHALLENGE, 200)}, "Cloudflare challenge"),
    ({rt.CATEGORY_URL: Resp("nope", 403)}, "403"),
    ({rt.CATEGORY_URL: requests.ConnectionError("timed out")}, "timed out"),
    ({rt.CATEGORY_URL: '<a href="https://ritholtz.com/2026/10/some-chart/">Chart</a>'}, "no AM/Weekend Reads post"),
    ({rt.CATEGORY_URL: category(SAT_POST), SAT_POST: Resp(CHALLENGE, 403)}, "Cloudflare challenge"),
    ({rt.CATEGORY_URL: category(SAT_POST), SAT_POST: '<meta property="article:published_time" '
      'content="2026-10-24T10:30:00+00:00"><p>moved</p>'}, "no post content"),
    ({rt.CATEGORY_URL: category(SAT_POST), SAT_POST: post_html(0)}, "no articles"),
])
def test_real_failure_exits_1_with_one_fixed_line(monkeypatch, tmp_path, capsys, pages, why):
    code, last = run_rt(monkeypatch, tmp_path, capsys, pages)
    assert code == 1 and last.startswith("AM READS FAILED: ") and why in last, last
    assert not (tmp_path / "data/ritholtz/articles.csv").exists()


def test_post_without_publish_time_keeps_the_old_list(monkeypatch, tmp_path, capsys):
    """No article:published_time and no <time>: it used to stamp the scrape time, so
    Saturday's Weekend Reads re-scraped on Monday showed as Monday's list."""
    pages = {rt.CATEGORY_URL: category(SAT_POST), SAT_POST: post_html()}
    run_rt(monkeypatch, tmp_path, capsys, pages)
    csv = tmp_path / "data/ritholtz/articles.csv"
    before = csv.read_text()
    pages[SAT_POST] = post_html().split(">", 1)[1]       # the meta tag dropped
    code, last = run_rt(monkeypatch, tmp_path, capsys, pages)
    assert code == 1 and last.startswith("AM READS FAILED: ") and "no publish time" in last, last
    assert csv.read_text() == before


def test_ritholtz_script_exits_with_mains_code():
    src = (ROOT / "core/scrape_ritholtz.py").read_text()
    assert "sys.exit(main())" in src


# ---------- SatPost (core/scrape_trung.py) ----------
FEED = """<?xml version="1.0"?><rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item><title>Issue 1</title><link>https://www.readtrung.com/p/one</link>
<description>blurb</description><pubDate>Sun, 19 Oct 2026 01:24:53 GMT</pubDate></item>
</channel></rss>"""


def run_tr(monkeypatch, tmp_path, capsys, reply):
    monkeypatch.chdir(tmp_path)

    def get(url, headers=None, timeout=None):
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(tr.requests, "get", get)
    code = tr.scrape_satpost()
    return code, capsys.readouterr().out.strip().splitlines()[-1]


def test_satpost_ok_and_unchanged_exit_0(monkeypatch, tmp_path, capsys):
    assert run_tr(monkeypatch, tmp_path, capsys, Resp(FEED))[0] == 0
    code, last = run_tr(monkeypatch, tmp_path, capsys, Resp(FEED))
    assert code == 0 and last == "SatPost unchanged, file left alone"


@pytest.mark.parametrize("reply, why", [
    (requests.ConnectionError("timed out"), "timed out"),
    (Resp(CHALLENGE, 403), "403"),
    (Resp("<rss><channel></channel></rss>"), "no issues in the feed"),
])
def test_satpost_failure_exits_1_with_one_fixed_line(monkeypatch, tmp_path, capsys, reply, why):
    code, last = run_tr(monkeypatch, tmp_path, capsys, reply)
    assert code == 1 and last.startswith("SATPOST FAILED: ") and why in last, last


def test_trung_script_exits_with_its_code():
    assert "sys.exit(scrape_satpost())" in (ROOT / "core/scrape_trung.py").read_text()


# ---------- am_reads.yml: a failure still commits, then goes red ----------
def test_am_reads_workflow_commits_then_fails_on_a_scraper_error():
    wf = (ROOT / ".github/workflows/am_reads.yml").read_text()
    run = wf[wf.index("- name: Scrape AM Reads + SatPost"):wf.index("- name: Commit if the list changed")]
    assert "set +e" in run and "ritholtz=$R" in run and "trung=$T" in run and '"$GITHUB_OUTPUT"' in run
    assert wf.index("- name: Commit if the list changed") < wf.index("- name: Fail the run if a scraper failed")
    assert "steps.scrape.outputs.failed != ''" in wf
