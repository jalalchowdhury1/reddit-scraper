"""core/live_data.py: the site reads data/ from GitHub's newest commit (10 Oct 2026)."""
import io
import tarfile
import time

import pytest

from core import live_data
import server

SHA = "0123456789abcdef0123456789abcdef01234567"


def make_tarball(files: dict, sha: str = SHA, extra=()) -> bytes:
    """A gzip tarball shaped like codeload's: pax comment = commit id, one top folder."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT,
                      pax_headers={"comment": sha} if sha else {}) as tf:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"reddit-scraper-main/{name}")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        for info in extra:
            tf.addfile(info)
    return buf.getvalue()


@pytest.fixture
def live(monkeypatch, tmp_path):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("LIVE_DATA", raising=False)
    monkeypatch.setattr(live_data, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(live_data, "_state", {"root": None, "version": "", "checked": 0.0,
                                               "fetched": 0.0, "error": ""})
    return tmp_path


def test_extract_keeps_only_regular_files_under_data(tmp_path):
    link = tarfile.TarInfo("reddit-scraper-main/data/link.csv")
    link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
    evil = tarfile.TarInfo("reddit-scraper-main/data/../../evil.txt")
    blob = make_tarball({"data/a/posts.csv": "id,title\n1,x\n", "server.py": "code",
                         "data/b.json": "{}"}, extra=(link, evil))
    n = live_data.extract_data(blob, tmp_path / "out")
    assert n == 2
    got = sorted(str(p.relative_to(tmp_path / "out")) for p in (tmp_path / "out").rglob("*") if p.is_file())
    assert got == ["data/a/posts.csv", "data/b.json"]
    assert not (tmp_path / "evil.txt").exists()


def test_version_is_the_commit_id_or_a_hash():
    assert live_data.tarball_version(make_tarball({"data/x": "1"})) == SHA
    assert live_data.tarball_version(make_tarball({"data/x": "1"}, sha="")).startswith("blob-")


def test_off_outside_vercel(monkeypatch, tmp_path):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.setattr(live_data, "_fetch", lambda: pytest.fail("must not fetch locally"))
    assert live_data.root(tmp_path) == tmp_path


def test_live_root_then_cached_within_ttl(live, monkeypatch):
    calls = []
    monkeypatch.setattr(live_data, "_fetch", lambda: calls.append(1) or make_tarball({"data/x.csv": "a\n1\n"}))
    r = live_data.root(live / "bundle")
    assert (r / "data/x.csv").read_text() == "a\n1\n"
    assert live_data.root(live / "bundle") == r and len(calls) == 1
    s = live_data.status()
    assert s["serving"] == "github" and s["commit"] == SHA[:7] and s["error"] is None


def test_new_commit_switches_copy(live, monkeypatch):
    monkeypatch.setattr(live_data, "_fetch", lambda: make_tarball({"data/x.csv": "old"}))
    first = live_data.root(live / "bundle")
    monkeypatch.setattr(live_data, "_fetch", lambda: make_tarball({"data/x.csv": "new"}, sha="f" * 40))
    live_data._state["checked"] = time.time() - live_data.TTL_S - 1
    second = live_data.root(live / "bundle")
    assert second != first and (second / "data/x.csv").read_text() == "new"
    assert (first / "data/x.csv").read_text() == "old"   # untouched, never deleted


def test_failure_keeps_last_good_copy_then_bundle(live, monkeypatch):
    def boom():
        raise OSError("github down")
    monkeypatch.setattr(live_data, "_fetch", boom)
    assert live_data.root(live / "bundle") == live / "bundle"          # no copy yet: bundle
    assert "github down" in live_data.status()["error"]
    monkeypatch.setattr(live_data, "_fetch", lambda: make_tarball({"data/x.csv": "ok"}))
    live_data._state["checked"] = 0.0
    good = live_data.root(live / "bundle")
    monkeypatch.setattr(live_data, "_fetch", boom)
    live_data._state["checked"] = 0.0
    assert live_data.root(live / "bundle") == good                      # outage: last good copy


def test_tarball_without_data_is_rejected(live, monkeypatch):
    monkeypatch.setattr(live_data, "_fetch", lambda: make_tarball({"server.py": "x"}))
    assert live_data.root(live / "bundle") == live / "bundle"
    assert "no data/" in live_data.status()["error"]


def test_live_data_off_switch(live, monkeypatch):
    monkeypatch.setenv("LIVE_DATA", "0")
    monkeypatch.setattr(live_data, "_fetch", lambda: pytest.fail("LIVE_DATA=0 must not fetch"))
    assert live_data.root(live / "bundle") == live / "bundle"


def test_server_reads_the_live_copy(live, monkeypatch):
    csv = "title,url,scraped_at\nRepo,https://github.com/a/b,2026-10-10T12:00:00\n"
    monkeypatch.setattr(live_data, "_fetch", lambda: make_tarball({"data/github_trending/repos.csv": csv}))
    assert server.data_dir() != server.BASE_DIR
    assert (server.data_dir() / "data/github_trending/repos.csv").read_text() == csv


def test_status_reports_the_data_source(live, monkeypatch):
    monkeypatch.setattr(live_data, "_fetch", lambda: make_tarball({"data/x.csv": "1"}))
    live_data.root(server.BASE_DIR)
    assert server.status()["data_source"]["commit"] == SHA[:7]
