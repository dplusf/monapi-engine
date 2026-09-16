from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.api.v1.endpoints.meta import list_profiles, list_signals
from app.engine.profiles import PolicyProfile, default_profile
from app.engine.signals import empty_catalogue, load_catalogue

CATALOGUE_PATH = Path(__file__).resolve().parent.parent / "app" / "data" / "signals.yaml"


def _request(*, signals=None, profiles=None, query: dict | None = None):
    """Minimal stand-in for a FastAPI Request.

    The endpoints only touch app.state and query_params; auth is a
    dependency and is injected by FastAPI, not exercised here.
    """
    state = SimpleNamespace(signals=signals, profiles=profiles)
    return SimpleNamespace(app=SimpleNamespace(state=state), query_params=query or {})


def _run(coro):
    return asyncio.run(coro)


class TestListSignals:
    def test_full_catalogue(self):
        catalogue = load_catalogue(str(CATALOGUE_PATH))
        out = _run(list_signals(_request(signals=catalogue), _key="x"))
        assert out["version"] == catalogue.version
        assert len(out["signals"]) == len(catalogue.signals)
        assert "mx" in out["categories"]

    def test_single_signal_lookup(self):
        catalogue = load_catalogue(str(CATALOGUE_PATH))
        out = _run(list_signals(_request(signals=catalogue, query={"signal": "email:no_mx"}), _key="x"))
        assert out["found"] is True
        assert len(out["signals"]) == 1
        assert out["signals"][0]["id"] == "email:no_mx"
        # Only the category of the matched signal comes along
        assert list(out["categories"]) == ["mx"]

    def test_feed_signal_resolves_to_pattern(self):
        catalogue = load_catalogue(str(CATALOGUE_PATH))
        out = _run(list_signals(_request(signals=catalogue, query={"signal": "feed:ipsum:0"}), _key="x"))
        assert out["found"] is True
        assert out["signals"][0]["id_pattern"] == "feed:<feed_name>:<n>"

    def test_unknown_signal_is_not_an_error(self):
        catalogue = load_catalogue(str(CATALOGUE_PATH))
        out = _run(list_signals(_request(signals=catalogue, query={"signal": "made:up"}), _key="x"))
        assert out["found"] is False
        assert out["signals"] == []

    def test_empty_catalogue_still_answers(self):
        out = _run(list_signals(_request(signals=empty_catalogue()), _key="x"))
        assert out["signals"] == []


class TestListProfiles:
    def test_shapes_profiles(self):
        profiles = {
            "default": default_profile(),
            "checkout": PolicyProfile("checkout", challenge=20, block=60, weights={"anonymizer": 40}),
        }
        out = _run(list_profiles(_request(profiles=profiles), _key="x"))
        names = [p["name"] for p in out["profiles"]]
        assert names == ["checkout", "default"]
        checkout = out["profiles"][0]
        assert checkout["thresholds"] == {"challenge": 20, "block": 60}
        assert checkout["weights"] == {"anonymizer": 40}
        assert checkout["ignore"] == []

    def test_ignore_is_serialisable(self):
        """frozenset is not JSON — it must come back as a sorted list."""
        profiles = {"newsletter": PolicyProfile("newsletter", ignore=frozenset(["free_mail", "typo"]))}
        out = _run(list_profiles(_request(profiles=profiles), _key="x"))
        assert out["profiles"][0]["ignore"] == ["free_mail", "typo"]

    def test_no_profiles_loaded(self):
        out = _run(list_profiles(_request(profiles=None), _key="x"))
        assert out["profiles"] == []
