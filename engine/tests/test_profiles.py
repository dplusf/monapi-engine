from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from app.engine.models import Signal
from app.engine.policy import decision_from_score
from app.engine.profiles import PolicyProfile, load_profiles, default_profile
from app.engine.scoring import score_from_signals


class TestLoadProfiles:
    def test_default_included(self):
        profiles = load_profiles("/nonexistent.yaml")
        assert "default" in profiles

    def test_default_thresholds(self):
        p = load_profiles("/nonexistent.yaml")["default"]
        assert p.challenge == 30
        assert p.block == 80

    def test_load_custom_profiles(self):
        content = yaml.dump({
            "profiles": {
                "default": {"thresholds": {"challenge": 30, "block": 80}},
                "checkout": {"thresholds": {"challenge": 20, "block": 60}, "weights": {"anonymizer": 40}},
                "newsletter": {"thresholds": {"challenge": 50, "block": 90}, "ignore": ["free_mail"]},
            }
        })
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(content)
            path = f.name
        try:
            profiles = load_profiles(path)
            assert sorted(profiles) == ["checkout", "default", "newsletter"]
            assert profiles["checkout"].challenge == 20
            assert profiles["checkout"].block == 60
            assert profiles["checkout"].weights == {"anonymizer": 40}
            assert profiles["newsletter"].ignore == frozenset(["free_mail"])
            # Overrides do not leak between profiles
            assert profiles["default"].weights == {}
            assert profiles["default"].ignore == frozenset()
        finally:
            import os
            os.unlink(path)

    def test_invalid_profile_skipped(self):
        content = yaml.dump({
            "profiles": {
                "default": {"thresholds": {"challenge": 30, "block": 80}},
                "bad": {"thresholds": {"challenge": 90, "block": 80}},  # challenge >= block
            }
        })
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(content)
            path = f.name
        try:
            profiles = load_profiles(path)
            assert "default" in profiles
            assert "bad" not in profiles
        finally:
            import os
            os.unlink(path)

    def test_broken_yaml_falls_back(self):
        content = "not: [valid: yaml: {{{{{{"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(content)
            path = f.name
        try:
            profiles = load_profiles(path)
            assert profiles == {"default": profiles["default"]}
        finally:
            import os
            os.unlink(path)


class TestDefaultProfile:
    def test_is_default(self):
        p = default_profile()
        assert p.name == "default"
        assert p.challenge == 30
        assert p.block == 80


class TestShippedProfiles:
    """The profiles that ship with the engine, checked against the
    behaviour they promise — a threshold typo is silent otherwise."""

    def _shipped(self):
        return load_profiles(
            str(Path(__file__).resolve().parent.parent / "app" / "data" / "policies.yaml")
        )

    def test_all_present(self):
        assert sorted(self._shipped()) == ["checkout", "default", "lead", "newsletter"]

    def test_lead_challenges_a_free_mailbox_on_its_own(self):
        """The point of the profile: a gmail address is neither waved
        through nor blocked when something is given away."""
        p = self._shipped()["lead"]
        sig = [Signal(id="email_domain:free_mail", category="free_mail", weight=10,
                      match="gmail.com", source="freemail_willwhite", severity="low")]
        score = score_from_signals(sig, p)
        assert score == 30
        assert decision_from_score(score, p)[0] == "challenge"

    def test_lead_does_not_block_a_free_mailbox(self):
        p = self._shipped()["lead"]
        sig = [Signal(id="email_domain:free_mail", category="free_mail", weight=10,
                      match="gmail.com", source="freemail_willwhite", severity="low")]
        assert decision_from_score(score_from_signals(sig, p), p)[0] != "block"

    def test_newsletter_ignores_a_free_mailbox(self):
        p = self._shipped()["newsletter"]
        sig = [Signal(id="email_domain:free_mail", category="free_mail", weight=10,
                      match="gmail.com", source="freemail_willwhite", severity="low")]
        assert score_from_signals(sig, p) == 0

    def test_default_barely_notices_a_free_mailbox(self):
        p = self._shipped()["default"]
        sig = [Signal(id="email_domain:free_mail", category="free_mail", weight=10,
                      match="gmail.com", source="freemail_willwhite", severity="low")]
        assert decision_from_score(score_from_signals(sig, p), p)[0] == "allow"

    def test_lead_blocks_a_disposable_domain_on_its_own(self):
        """Giving goods away to a ten-minute address is the failure mode
        this profile exists for — it must not take a second signal."""
        p = self._shipped()["lead"]
        sig = [Signal(id="email_domain:disposable", category="disposable", weight=40,
                      match="mailinator.com", source="disposable_ivolo", severity="high")]
        assert decision_from_score(score_from_signals(sig, p), p)[0] == "block"

    def test_lead_does_not_block_a_free_mailbox_with_one_more_signal(self):
        """gmail plus a role account stays a challenge — a human decides."""
        p = self._shipped()["lead"]
        sig = [
            Signal(id="email_domain:free_mail", category="free_mail", weight=10,
                   match="gmail.com", source="freemail_willwhite", severity="low"),
            Signal(id="email:role_account", category="role_account", weight=5,
                   match="info", source="static_list", severity="low"),
        ]
        assert decision_from_score(score_from_signals(sig, p), p)[0] == "challenge"
