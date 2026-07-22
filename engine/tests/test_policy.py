from __future__ import annotations

import pytest

from app.engine.policy import decision_from_score
from app.engine.profiles import PolicyProfile


class TestDecisionFromScore:
    def test_below_challenge_is_allow(self):
        dec, action = decision_from_score(0)
        assert dec == "allow"
        assert action is None

    def test_challenge_band(self):
        dec, action = decision_from_score(30)
        assert dec == "challenge"
        assert action is not None
        assert action.type == "soft_block"
        assert action.retry_after_seconds == 300

    def test_block_threshold(self):
        dec, action = decision_from_score(80)
        assert dec == "block"
        assert action is None

    def test_custom_profile_challenge(self):
        profile = PolicyProfile("checkout", challenge=20, block=60)
        dec, _ = decision_from_score(25, profile)
        assert dec == "challenge"

    def test_custom_profile_block(self):
        profile = PolicyProfile("checkout", challenge=20, block=60)
        dec, _ = decision_from_score(60, profile)
        assert dec == "block"

    def test_newsletter_high_threshold(self):
        profile = PolicyProfile("newsletter", challenge=50, block=90)
        dec, _ = decision_from_score(40, profile)
        assert dec == "allow"

    def test_default_profile_fallback(self):
        dec, _ = decision_from_score(45)
        assert dec == "challenge"  # default challenge=30, block=80
