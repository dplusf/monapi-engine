from __future__ import annotations

from app.engine.checks import dedupe_host_signals
from app.engine.models import Evidence, Signal


def _pair(feed: str, category: str, weight: int, ip: str):
    return (
        Signal(id=f"feed:{feed}:0", category=category, weight=weight, match=ip,
               source=feed, severity="medium"),
        Evidence(source=feed, category=category, match=ip, weight=weight),
    )


def _lists(*pairs):
    return [p[0] for p in pairs], [p[1] for p in pairs]


class TestDedupeHostSignals:
    def test_same_feed_across_hosts_counts_once(self):
        """The regression: gmail.com has five MX hosts in one listed
        datacenter range and scored 5 x 15 = 75 for a single fact."""
        signals, evidence = _lists(
            *[_pair("x4bnet_datacenter", "datacenter", 15, f"142.250.1.{i}") for i in range(5)]
        )
        s, e = dedupe_host_signals(signals, evidence)
        assert len(s) == 1
        assert len(e) == 1
        assert sum(x.weight for x in s) == 15

    def test_different_feeds_are_kept(self):
        signals, evidence = _lists(
            _pair("ipsum", "abuse", 30, "1.2.3.4"),
            _pair("spamhaus_drop", "abuse", 40, "1.2.3.5"),
        )
        s, _ = dedupe_host_signals(signals, evidence)
        assert len(s) == 2
        assert sum(x.weight for x in s) == 70

    def test_same_feed_different_categories_are_kept(self):
        signals, evidence = _lists(
            _pair("mixed_feed", "abuse", 30, "1.2.3.4"),
            _pair("mixed_feed", "anonymizer", 25, "1.2.3.5"),
        )
        s, _ = dedupe_host_signals(signals, evidence)
        assert len(s) == 2

    def test_dropped_categories_disappear(self):
        """datacenter on a mail server is the normal case and says
        nothing — the email check drops it."""
        signals, evidence = _lists(
            _pair("x4bnet_datacenter", "datacenter", 15, "142.250.1.1"),
            _pair("ipsum", "abuse", 30, "142.250.1.1"),
        )
        s, _ = dedupe_host_signals(signals, evidence, drop_categories=frozenset({"datacenter"}))
        assert len(s) == 1
        assert s[0].category == "abuse"

    def test_signals_and_evidence_stay_aligned(self):
        signals, evidence = _lists(
            _pair("feed_a", "abuse", 30, "1.1.1.1"),
            _pair("feed_a", "abuse", 30, "1.1.1.2"),
            _pair("feed_b", "anonymizer", 25, "1.1.1.3"),
        )
        s, e = dedupe_host_signals(signals, evidence)
        assert len(s) == len(e) == 2
        assert [x.source for x in s] == [x.source for x in e]

    def test_empty_input(self):
        assert dedupe_host_signals([], []) == ([], [])

    def test_first_occurrence_wins(self):
        """Keeps the host that was checked first, so the match field
        points at a real address rather than an arbitrary one."""
        signals, evidence = _lists(
            _pair("feed_a", "abuse", 30, "1.1.1.1"),
            _pair("feed_a", "abuse", 30, "2.2.2.2"),
        )
        s, _ = dedupe_host_signals(signals, evidence)
        assert s[0].match == "1.1.1.1"
