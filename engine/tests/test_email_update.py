from __future__ import annotations

import pytest

from app.services.email_checks import is_role_account, typo_suggestion, _one_edit_away


class TestOneEditAway:
    def test_substitution(self):
        assert _one_edit_away("gamil.com", "gmail.com")

    def test_insertion(self):
        assert _one_edit_away("gmail.com", "gmails.com")

    def test_deletion(self):
        assert _one_edit_away("gmails.com", "gmail.com")

    def test_transposition(self):
        assert _one_edit_away("gmial.com", "gmail.com")

    def test_two_edits_too_many(self):
        assert not _one_edit_away("gaml.com", "gmail.com")

    def test_length_diff_too_large(self):
        assert not _one_edit_away("abc", "abcdef")

    def test_different_both_ways(self):
        assert _one_edit_away("webb.de", "web.de")


class TestTypoSuggestion:
    def test_common_typo(self):
        assert typo_suggestion("gamil.com") == "gmail.com"

    def test_transposition_typo(self):
        assert typo_suggestion("gmial.com") == "gmail.com"

    def test_cut_typo(self):
        assert typo_suggestion("webb.de") == "web.de"

    def test_correct_domain_returns_none(self):
        assert typo_suggestion("gmail.com") is None

    def test_unknown_domain_returns_none(self):
        assert typo_suggestion("projektsued.de") is None

    def test_case_insensitive(self):
        assert typo_suggestion("GMAIL.COM") is None
        assert typo_suggestion("GAMIL.COM") == "gmail.com"

    def test_domain_in_popular_not_flagged(self):
        assert typo_suggestion("web.de") is None


class TestRoleAccount:
    def test_known_roles(self):
        for role in ("info", "admin", "support", "sales", "noreply", "no-reply", "hello", "contact"):
            assert is_role_account(role)

    def test_not_a_role(self):
        assert not is_role_account("dennis")
        assert not is_role_account("susi")

    def test_case_insensitive(self):
        assert is_role_account("Info")
        assert is_role_account("SUPPORT")
