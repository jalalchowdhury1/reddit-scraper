"""Unit tests for AM Reads dedup / cleanup (run: python3 -m pytest tests -q)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
from scrape_ritholtz import (clean_title_text, normalize_title, normalize_url, is_junk,
                             dedupe_articles, filter_already_shown, remember_shown)


def test_zero_width_bullet_is_stripped():
    assert clean_title_text("​• Tennis for Savages") == "Tennis for Savages"


def test_normalize_url_drops_tracking_and_www():
    a = normalize_url("https://www.wsj.com/finance/x-022abf17?reflink=share&st=abc")
    b = normalize_url("http://wsj.com/finance/x-022abf17/")
    assert a == b


def test_normalize_url_keeps_youtube_id():
    assert normalize_url("https://www.youtube.com/watch?v=abc123&t=5") != normalize_url("https://www.youtube.com/watch?v=zzz999")


def test_junk_lines():
    assert is_junk("Video of the day :", "https://youtu.be/x")
    assert is_junk("Be sure to check out our Masters in Business", "https://example.com")
    assert is_junk("Anything", "https://itunes.apple.com/us/podcast/x")
    assert is_junk("To learn how these reads are assembled each day, .", "https://x.com")
    assert is_junk("Previous Post", "https://x.com") and is_junk("Untitled", "https://x.com")
    assert is_junk("The weekend is here! Pour yourself a mug of coffee", "https://x.com")
    assert not is_junk("How China Thinks About AI", "https://www.derekthompson.org/p/x")


def test_dedupe_same_url_or_same_title():
    arts = [
        {"url": "https://a.com/x?utm=1", "title": "The Diesel Shock Is a Core Inflation Shock"},
        {"url": "https://a.com/x", "title": "Different wording"},
        {"url": "https://b.com/y", "title": "​• The diesel shock is a core inflation shock!"},
        {"url": "https://c.com/z", "title": "Unique"},
    ]
    assert [a["url"] for a in dedupe_articles(arts)] == ["https://a.com/x?utm=1", "https://c.com/z"]


def test_cross_day_repeat_dropped_but_same_post_rerun_kept():
    seen = remember_shown([{"url": "https://a.com/x", "title": "Old story"}], {}, "post-mon", "2026-09-21")
    tue = [{"url": "https://a.com/x?ref=2", "title": "Old story"}, {"url": "https://n.com", "title": "New"}]
    assert [a["title"] for a in filter_already_shown(tue, seen, "post-tue")] == ["New"]
    # re-running Monday's own post keeps its article
    assert len(filter_already_shown([{"url": "https://a.com/x", "title": "Old story"}], seen, "post-mon")) == 1
