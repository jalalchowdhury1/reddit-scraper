"""Serve data/ from the newest commit on GitHub, not from the deployed copy (10 Oct 2026).

Why: Vercel's free plan allows 100 deploys a day for ALL of Jalal's projects together, and
this site's robots (GitHub Trending every 6 h, AM Reads, the Mac's Reddit saves, the RSS
backup) redeployed it ~25 times a day just to ship new CSVs. On 10 Oct the account hit the
cap and every project's deploys failed. Now vercel.json has git.deploymentEnabled false,
.github/workflows/deploy.yml deploys only code changes, and the running site downloads the
repo tarball (public repo, no token) at most once per TTL_S per warm instance and reads
data/ from that copy.

Fail-safe: any error (GitHub down, timeout, a bad tarball) keeps the last good copy, or
falls back to the data/ bundled with the deploy (never older than the last code deploy).
Off outside Vercel (tests and local runs read the checkout) and when LIVE_DATA=0.
/api/status shows the state under "data_source".

Disk: one ~1.5 MB folder in /tmp per data commit a warm instance sees. Old copies are not
deleted (house rule: no recursive deletes on computed paths); instances are short-lived
and /tmp holds 500 MB, so ~20 data commits a day never get near it.
"""
import hashlib
import io
import logging
import os
import tarfile
import threading
import time
import urllib.request
from pathlib import Path, PurePosixPath

TARBALL_URL = "https://codeload.github.com/jalalchowdhury1/reddit-scraper/tar.gz/refs/heads/main"
TTL_S = 300                    # re-check GitHub at most every 5 min per warm instance
TIMEOUT_S = 6
MAX_BYTES = 40 * 1024 * 1024   # the whole repo tarball is ~0.75 MB today
CACHE_DIR = Path("/tmp/reddit-scraper-live")

log = logging.getLogger("daily-reader")
_lock = threading.Lock()
_state = {"root": None, "version": "", "checked": 0.0, "fetched": 0.0, "error": ""}


def enabled() -> bool:
    on_vercel = bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"))
    return on_vercel and os.environ.get("LIVE_DATA", "1") != "0"


def data_members(tf):
    """(member, path relative to the repo root) for each regular file under <top>/data/.
    Anything else (other folders, links, absolute or '..' names) is skipped."""
    for m in tf:
        parts = PurePosixPath(m.name).parts
        if len(parts) < 3 or parts[1] != "data" or not m.isfile():
            continue
        rel = PurePosixPath(*parts[1:])
        if rel.is_absolute() or ".." in rel.parts:
            continue
        yield m, rel


def tarball_version(blob: bytes) -> str:
    """The commit id git archive writes into the pax global header, else a hash of the bytes."""
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        tf.next()
        sha = str(tf.pax_headers.get("comment", "")).strip()
    return sha or "blob-" + hashlib.sha1(blob).hexdigest()


def extract_data(blob: bytes, dest: Path) -> int:
    """Write the tarball's data/ files under dest/data/; returns how many."""
    n = 0
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for m, rel in data_members(tf):
            src = tf.extractfile(m)
            if src is None:
                continue
            out = dest.joinpath(*rel.parts)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(src.read())
            n += 1
    return n


def _fetch() -> bytes:
    req = urllib.request.Request(TARBALL_URL, headers={"User-Agent": "reddit-scraper-live-data"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        blob = r.read(MAX_BYTES + 1)
    if len(blob) > MAX_BYTES:
        raise ValueError(f"tarball over {MAX_BYTES} bytes")
    return blob


def _refresh():
    blob = _fetch()
    version = tarball_version(blob)
    _state["fetched"] = time.time()
    if version == _state["version"] and _state["root"] is not None:
        return
    dest = CACHE_DIR / version[:45]
    if not (dest / "data").is_dir():
        part = CACHE_DIR / f"{version[:45]}.part{time.time_ns()}"
        n = extract_data(blob, part)
        if n == 0 or not (part / "data").is_dir():
            raise ValueError("tarball has no data/ files")
        try:
            os.rename(part, dest)
        except OSError:
            if not (dest / "data").is_dir():
                raise
    _state["root"], _state["version"] = dest, version
    log.info("live data now at commit %s", version[:7])


def root(bundle: Path) -> Path:
    """The folder whose data/ the site should read right now: the newest GitHub copy when
    live, else `bundle` (the checkout, or the copy deployed with the code)."""
    if not enabled():
        return bundle
    if time.time() - _state["checked"] >= TTL_S:
        # Cold start: wait for the first copy. Warm: never block a page on a refresh that
        # another request is already doing; serve the current copy meanwhile.
        if _lock.acquire(blocking=_state["root"] is None):
            try:
                if time.time() - _state["checked"] >= TTL_S:
                    _state["checked"] = time.time()   # first, so an outage costs one try per TTL
                    try:
                        _refresh()
                        _state["error"] = ""
                    except Exception as e:
                        _state["error"] = f"{type(e).__name__}: {e}"[:200]
                        log.warning("live data refresh failed, serving %s: %s",
                                    "the last good copy" if _state["root"] else "the deployed bundle",
                                    _state["error"])
            finally:
                _lock.release()
    return _state["root"] or bundle


def status() -> dict:
    """For /api/status: is the site reading live data, from which commit, how fresh."""
    fetched = _state["fetched"]
    return {
        "live": enabled(),
        "serving": "github" if (enabled() and _state["root"]) else "bundle",
        "commit": _state["version"][:7] or None,
        "fetchedAgeS": round(time.time() - fetched) if fetched else None,
        "error": _state["error"] or None,
    }
