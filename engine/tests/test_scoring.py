from __future__ import annotations

import pytest

from app.engine.models import Signal
from app.engine.scoring import score_from_signals, confidence_from_signals, effective_signals
from app.engine.profiles import PolicyProfile


def _sigs(*pairs: tuple[str, int]) -> list[Signal]:
    return [
        Signal(id=f"test:{cat}", category=cat, weight=w, match="1.2.3.4", source="test", severity="high")
        for cat, w in pairs
    ]


class TestScoreFromSignals:
    def test_empty_returns_zero(self):
        assert score_from_signals([]) == 0

    def test_sum_simple(self):
        assert score_from_signals(_sigs(("abuse", 20), ("abuse", 15))) == 35

    def test_capped_at_100(self):
        assert score_from_signals(_sigs(("abuse", 60), ("malware", 50))) == 100

    def test_weight_override(self):
        profile = PolicyProfile("test", weights={"abuse": 50})
        sigs = _sigs(("abuse", 10))  # 10 -> 50
        assert score_from_signals(sigs, profile) == 50

    def test_category_ignored(self):
        profile = PolicyProfile("test", ignore=frozenset(["free_mail"]))
        sigs = _sigs(("abuse", 30), ("free_mail", 10))
        assert score_from_signals(sigs, profile) == 30

    def test_both_override_and_ignore(self):
        profile = PolicyProfile("test", weights={"anonymizer": 40}, ignore=frozenset(["free_mail"]))
        sigs = _sigs(("anonymizer", 25), ("free_mail", 10), ("abuse", 20))
        # anonymizer 25->40, free_mail ignored, abuse 20 = 60
        assert score_from_signals(sigs, profile) == 60


class TestConfidenceFromSignals:
    def test_empty(self):
        assert confidence_from_signals([]) == 0.2

    def test_low(self):
        assert confidence_from_signals(_sigs(("abuse", 10))) == 0.5

    def test_medium(self):
        assert confidence_from_signals(_sigs(("abuse", 30), ("abuse", 15))) == 0.7

    def test_high(self):
        assert confidence_from_signals(_sigs(("abuse", 80))) == 0.9

    def test_confidence_applies_ignored_categories(self):
        profile = PolicyProfile("test", ignore=frozenset(["free_mail"]))
        sigs = _sigs(("abuse", 10), ("free_mail", 80))
        # free_mail ignored -> only abuse 10 -> low
        assert confidence_from_signals(sigs, profile) == 0.5


class TestEffectiveSignals:
    def test_no_profile_returns_original(self):
        sigs = _sigs(("abuse", 20))
        eff = effective_signals(sigs)
        assert len(eff) == 1
        assert eff[0].weight == 20

    def test_weight_override_changes_signal(self):
        profile = PolicyProfile("test", weights={"abuse": 99})
        sigs = _sigs(("abuse", 20))
        eff = effective_signals(sigs, profile)
        assert eff[0].weight == 99
        assert eff[0].severity == "high"

    def test_override_sets_severity(self):
        profile = PolicyProfile("test", weights={"free_mail": 5})
        sigs = _sigs(("free_mail", 40))
        eff = effective_signals(sigs, profile)
        assert eff[0].weight == 5
        assert eff[0].severity == "low"

    def test_ignored_category_removed(self):
        profile = PolicyProfile("test", ignore=frozenset(["datacenter"]))
        sigs = _sigs(("abuse", 20), ("datacenter", 15))
        eff = effective_signals(sigs, profile)
        assert len(eff) == 1
        assert eff[0].category == "abuse"
