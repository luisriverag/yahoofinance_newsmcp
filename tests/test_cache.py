import os
import time

from yahoofinance_newsmcp.cache import JsonCache, article_fingerprint, build_cache
from yahoofinance_newsmcp.config import Settings
from yahoofinance_newsmcp.yahoo import NewsArticle


def test_json_cache_round_trips_within_ttl(tmp_path):
    path = str(tmp_path / "x.json")
    cache = JsonCache(path, ttl_seconds=3600)
    cache.set("k", {"value": "v"})

    assert cache.get("k")["value"] == "v"


def test_json_cache_persists_across_instances(tmp_path):
    path = str(tmp_path / "x.json")
    first = JsonCache(path, ttl_seconds=3600)
    first.set("k", {"value": "v"})
    first.save()

    second = JsonCache(path, ttl_seconds=3600)
    assert second.get("k")["value"] == "v"


def test_json_cache_expires_after_ttl(tmp_path):
    path = str(tmp_path / "x.json")
    cache = JsonCache(path, ttl_seconds=0.01)
    cache.set("k", {"value": "v"})
    time.sleep(0.02)

    assert cache.get("k") is None


def test_json_cache_miss_returns_none(tmp_path):
    cache = JsonCache(str(tmp_path / "x.json"), ttl_seconds=3600)
    assert cache.get("missing") is None


def test_json_cache_with_no_path_is_always_a_miss_and_never_writes(tmp_path):
    cache = JsonCache(None, ttl_seconds=3600)
    cache.set("k", {"value": "v"})

    assert cache.get("k") is None
    cache.save()  # must not raise with no path


def test_json_cache_tolerates_a_corrupt_file(tmp_path):
    path = tmp_path / "x.json"
    path.write_text("not json{{{", encoding="utf-8")

    cache = JsonCache(str(path), ttl_seconds=3600)

    assert cache.get("anything") is None


def test_json_cache_save_prunes_expired_entries(tmp_path):
    path = str(tmp_path / "x.json")
    cache = JsonCache(path, ttl_seconds=0.01)
    cache.set("stale", {"value": "v"})
    time.sleep(0.02)
    cache.set("fresh", {"value": "v2"})
    cache.save()

    reloaded = JsonCache(path, ttl_seconds=3600)
    assert reloaded.get("stale") is None
    assert reloaded.get("fresh")["value"] == "v2"


def test_json_cache_save_is_a_noop_when_nothing_changed(tmp_path):
    path = str(tmp_path / "x.json")
    cache = JsonCache(path, ttl_seconds=3600)
    cache.save()

    assert not os.path.exists(path)


def test_build_cache_is_inert_without_cache_dir():
    settings = Settings(cache_dir="")
    cache = build_cache(settings, "summaries")
    cache.set("k", {"value": "v"})

    assert cache.get("k") is None


def test_build_cache_uses_cache_subdir_under_cache_dir(tmp_path):
    settings = Settings(cache_dir=str(tmp_path), cache_ttl_hours=1)
    cache = build_cache(settings, "summaries")
    cache.set("k", {"value": "v"})
    cache.save()

    assert os.path.exists(tmp_path / "cache" / "summaries.json")


def test_article_fingerprint_changes_when_body_changes():
    base = NewsArticle(ticker="AAPL", title="t", link="https://a/1", body="body one")
    changed = NewsArticle(ticker="AAPL", title="t", link="https://a/1", body="body two")

    assert article_fingerprint(base) != article_fingerprint(changed)


def test_article_fingerprint_stable_for_identical_article():
    a = NewsArticle(ticker="AAPL", title="t", link="https://a/1", body="body")
    b = NewsArticle(ticker="AAPL", title="t", link="https://a/1", body="body")

    assert article_fingerprint(a) == article_fingerprint(b)
