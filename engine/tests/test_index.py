from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.adapters.feeds import FeedDef
from app.adapters.index import build_index, load_index
from app.engine.checks import check_ip


def _build(wo: Path, feeds: list[FeedDef]) -> None:
    idx = str(wo / "index")
    raw = str(wo / "raw")
    Path(raw).mkdir(parents=True, exist_ok=True)
    # Write dummy feed files matching the feed names
    for feed in feeds:
        path = Path(raw) / f"{feed.name}{'.json' if feed.format == 'json' else '.txt'}"
        path.touch()
    build_index(index_dir=idx, raw_dir=raw, feeds=feeds, feed_meta={})


class TestIndexIPv6:
    @pytest.fixture
    def store(self, tmp_path):
        feeds = [
            FeedDef(name="v4feed", url="x", type="cidr", category="abuse", weight=35, format="text"),
            FeedDef(name="v6feed", url="x", type="cidr", category="abuse", weight=40, format="text"),
        ]
        (tmp_path / "raw").mkdir()
        (tmp_path / "raw" / "v4feed.txt").write_text("203.0.113.0/24\n198.51.100.7\n")
        (tmp_path / "raw" / "v6feed.txt").write_text("2001:db8:bad::/48\n2001:db8:dead::beef\n")
        _build(tmp_path, feeds)
        return load_index(str(tmp_path / "index"))

    def test_v4_cidr_match(self, store):
        r = check_ip(store, "203.0.113.55")
        assert r.score == 35
        assert r.decision == "challenge"

    def test_v4_bare_ip_match(self, store):
        r = check_ip(store, "198.51.100.7")
        assert r.score == 35

    def test_v6_cidr_match(self, store):
        r = check_ip(store, "2001:db8:bad::1")
        assert r.score == 40
        assert r.decision == "challenge"

    def test_v6_bare_ip_match(self, store):
        r = check_ip(store, "2001:db8:dead::beef")
        assert r.score == 40

    def test_v6_not_in_index_is_allow(self, store):
        r = check_ip(store, "2001:db8:9999::1")
        assert r.score == 0
        assert r.decision == "allow"

    def test_non_ip_is_allow(self, store):
        r = check_ip(store, "not-an-ip")
        assert r.score == 0

    def test_trie_for_v4(self, store):
        assert store.trie_for("1.1.1.1") is store.ip_trie

    def test_trie_for_v6(self, store):
        assert store.trie_for("::1") is store.ip6_trie

    def test_trie_for_bad_input(self, store):
        assert store.trie_for("not-an-ip") is None


class TestDomainParsing:
    def _ds(self, tmp_path, name, category, fmt, content):
        feeds = [FeedDef(name=name, url="x", type="domain", category=category, weight=40, format=fmt)]
        raw = tmp_path / "raw"
        raw.mkdir()
        suffix = ".json" if fmt == "json" else (".hosts" if fmt == "hostfile" else ".txt")
        (raw / f"{name}{suffix}").write_text(content, encoding="utf-8")
        idx = str(tmp_path / "index")
        build_index(index_dir=idx, raw_dir=str(raw), feeds=feeds, feed_meta={})
        return load_index(idx)

    def test_text_format(self, tmp_path):
        store = self._ds(tmp_path, "d", "disposable", "text", "mailinator.com\nspam.net\n")
        assert "mailinator.com" in store.domains
        assert store.domains["mailinator.com"]["disposable"]["weight"] == 40

    def test_json_format(self, tmp_path):
        store = self._ds(tmp_path, "j", "disposable", "json", '["a.com","b.com"]')
        assert "a.com" in store.domains

    def test_hostfile_format(self, tmp_path):
        store = self._ds(tmp_path, "h", "malware", "hostfile", "# comment\n127.0.0.1 evil.com\n127.0.0.1 evil2.com\n")
        assert "evil.com" in store.domains
        assert "evil2.com" in store.domains
        assert "localhost" not in store.domains
        assert "127.0.0.1" not in store.domains

    def test_categories_do_not_collapse(self, tmp_path):
        feeds = [
            FeedDef(name="d", url="x", type="domain", category="disposable", weight=40, format="text"),
            FeedDef(name="p", url="x", type="domain", category="phishing", weight=35, format="text"),
        ]
        raw = tmp_path / "raw"
        raw.mkdir()
        (raw / "d.txt").write_text("evil.com\n")
        (raw / "p.txt").write_text("evil.com\n")
        idx = str(tmp_path / "index")
        build_index(index_dir=idx, raw_dir=str(raw), feeds=feeds, feed_meta={})
        store = load_index(idx)
        assert store.domains["evil.com"]["disposable"]["weight"] == 40
        assert store.domains["evil.com"]["phishing"]["weight"] == 35

    def test_highest_weight_taken_across_feeds(self, tmp_path):
        feeds = [
            FeedDef(name="a", url="x", type="domain", category="abuse", weight=20, format="text"),
            FeedDef(name="b", url="x", type="domain", category="abuse", weight=50, format="text"),
        ]
        raw = tmp_path / "raw"
        raw.mkdir()
        (raw / "a.txt").write_text("bad.com\n")
        (raw / "b.txt").write_text("bad.com\n")
        idx = str(tmp_path / "index")
        build_index(index_dir=idx, raw_dir=str(raw), feeds=feeds, feed_meta={})
        store = load_index(idx)
        assert store.domains["bad.com"]["abuse"]["weight"] == 50
