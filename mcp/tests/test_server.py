from __future__ import annotations

import json

import httpx
import pytest

from monapi_mcp import server
from monapi_mcp.client import EngineConfig, MonapiClient, MonapiError
from monapi_mcp.format import ResponseFormat

DISPOSABLE = {
    "request_id": "r1",
    "ts": 1758000000,
    "profile": "default",
    "decision": "block",
    "action": None,
    "score": 80,
    "confidence": 0.9,
    "signals": [
        {
            "id": "email_domain:disposable",
            "category": "disposable",
            "weight": 40,
            "match": "mailinator.com",
            "source": "disposable_ivolo",
            "severity": "high",
        },
        {
            "id": "email:no_mx",
            "category": "mx",
            "weight": 40,
            "match": "mailinator.com",
            "source": "dns",
            "severity": "high",
        },
    ],
    "evidence": [],
    "enrichment": {
        "email": "a@mailinator.com",
        "domain": "mailinator.com",
        "deliverability": "undeliverable",
        "mx_hosts": [],
        "is_catchall": False,
        "is_role_account": False,
        "did_you_mean": None,
    },
    "timing_ms": {"total": 12},
}

CLEAN = {
    "profile": "default",
    "decision": "allow",
    "action": None,
    "score": 0,
    "confidence": 0.2,
    "signals": [],
    "evidence": [],
    "enrichment": {"domain": "example.com", "deliverability": "unknown", "mx_hosts": ["mx.example.com"]},
}

TYPO = {
    "profile": "default",
    "decision": "challenge",
    "action": {"type": "soft_block", "retry_after_seconds": 300, "reason": "score_in_challenge_band"},
    "score": 40,
    "confidence": 0.7,
    "signals": [
        {"id": "email:domain_typo", "category": "typo", "weight": 10, "match": "gamil.com~gmail.com", "source": "static_list", "severity": "low"},
        {"id": "email:no_mx", "category": "mx", "weight": 30, "match": "gamil.com", "source": "dns", "severity": "high"},
    ],
    "evidence": [],
    "enrichment": {"domain": "gamil.com", "did_you_mean": "gmail.com", "deliverability": "undeliverable"},
}

CATALOGUE = {
    "version": 1,
    "categories": {"mx": {"summary": "Mail routing", "default_weight": 30}},
    "signals": [
        {
            "id": "email:no_mx",
            "category": "mx",
            "weight": 30,
            "severity": "high",
            "source": "dns",
            "endpoints": ["/v1/check/email"],
            "meaning": "No MX and no A fallback.",
            "guidance": "Strongest cheap signal for a fake address.",
            "false_positives": "Transient DNS failures look identical.",
        },
        {
            "id_pattern": "feed:<feed_name>:<n>",
            "category": "abuse | anonymizer | datacenter",
            "weight": "feed weight",
            "severity": "varies",
            "source": "<feed_name>",
            "endpoints": ["/v1/check/ip"],
            "meaning": "The IP is listed by that feed.",
            "guidance": "Match on the feed name, not the index.",
        },
    ],
}

PROFILES = {
    "default": "default",
    "profiles": [
        {"name": "checkout", "thresholds": {"challenge": 20, "block": 60}, "weights": {"anonymizer": 40}, "ignore": []},
        {"name": "default", "thresholds": {"challenge": 30, "block": 80}, "weights": {}, "ignore": []},
    ],
}


def make_client(handler, **overrides) -> MonapiClient:
    """A client wired to a fake engine instead of the network."""
    config = EngineConfig(base_url="http://engine.test", api_key="k", **overrides)
    client = MonapiClient(config)
    client._client = httpx.AsyncClient(
        base_url=config.base_url,
        transport=httpx.MockTransport(handler),
        timeout=config.timeout,
    )
    return client


def route(responses: dict[str, object], calls: list[httpx.Request] | None = None):
    """Map path -> payload (or a callable returning a Response)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        payload = responses.get(request.url.path)
        if payload is None:
            return httpx.Response(404, json={"detail": "not found"})
        if callable(payload):
            return payload(request)
        return httpx.Response(200, json=payload)

    return handler


@pytest.fixture
def engine(monkeypatch):
    """Point the server's module-level client at a fake engine."""

    def _install(handler, **overrides):
        client = make_client(handler, **overrides)
        monkeypatch.setattr(server, "_client", client)
        monkeypatch.setattr(server, "_config", client.config)
        return client

    return _install


class TestCheckEmail:
    async def test_markdown_verdict(self, engine):
        engine(route({"/v1/check/email/a@mailinator.com": DISPOSABLE}))
        out = await server.monapi_check_email("a@mailinator.com")
        assert "**block**" in out
        assert "Score 80/100" in out
        assert "`email_domain:disposable`" in out
        assert "disposable_ivolo" in out
        assert "undeliverable" in out

    async def test_json_is_the_raw_response(self, engine):
        engine(route({"/v1/check/email/a@mailinator.com": DISPOSABLE}))
        out = await server.monapi_check_email("a@mailinator.com", response_format=ResponseFormat.JSON)
        assert json.loads(out) == DISPOSABLE

    async def test_no_signals_is_not_reported_as_clean(self, engine):
        engine(route({"/v1/check/email/ok@example.com": CLEAN}))
        out = await server.monapi_check_email("ok@example.com")
        assert "absence of evidence" in out

    async def test_typo_suggestion_surfaces(self, engine):
        engine(route({"/v1/check/email/a@gamil.com": TYPO}))
        out = await server.monapi_check_email("a@gamil.com")
        assert "Did you mean" in out and "gmail.com" in out
        assert "soft_block" in out

    async def test_profile_is_passed_through(self, engine):
        calls: list[httpx.Request] = []
        engine(route({"/v1/check/email/a@example.com": CLEAN}, calls))
        await server.monapi_check_email("a@example.com", profile="checkout")
        assert calls[0].url.params["profile"] == "checkout"

    async def test_default_profile_from_config(self, engine):
        calls: list[httpx.Request] = []
        engine(route({"/v1/check/email/a@example.com": CLEAN}, calls), profile="newsletter")
        await server.monapi_check_email("a@example.com")
        assert calls[0].url.params["profile"] == "newsletter"

    async def test_address_is_url_encoded(self, engine):
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json=CLEAN)

        engine(handler)
        await server.monapi_check_email("a+tag@example.com")
        assert "a%2Btag%40example.com" in str(calls[0].url)


class TestCheckEmails:
    async def test_groups_by_decision(self, engine):
        engine(
            route(
                {
                    "/v1/check/email/bad@mailinator.com": DISPOSABLE,
                    "/v1/check/email/ok@example.com": CLEAN,
                    "/v1/check/email/typo@gamil.com": TYPO,
                }
            )
        )
        out = await server.monapi_check_emails(
            ["bad@mailinator.com", "ok@example.com", "typo@gamil.com"]
        )
        assert "## block (1)" in out
        assert "## challenge (1)" in out
        assert "## allow (1)" in out
        assert "did you mean gmail.com?" in out

    async def test_failures_are_reported_not_swallowed(self, engine):
        def handler(request: httpx.Request) -> httpx.Response:
            if "boom" in str(request.url):
                return httpx.Response(500)
            return httpx.Response(200, json=CLEAN)

        engine(handler)
        out = await server.monapi_check_emails(["ok@example.com", "boom@example.com"])
        assert "## Not checked (1)" in out
        assert "boom@example.com" in out
        assert "1 failed" in out

    async def test_duplicates_checked_once(self, engine):
        calls: list[httpx.Request] = []
        engine(route({"/v1/check/email/a@example.com": CLEAN}, calls))
        await server.monapi_check_emails(["a@example.com", "a@example.com"])
        assert len(calls) == 1

    async def test_json_shape(self, engine):
        engine(route({"/v1/check/email/ok@example.com": CLEAN}))
        out = json.loads(
            await server.monapi_check_emails(["ok@example.com"], response_format=ResponseFormat.JSON)
        )
        assert out["profile"] == "default"
        assert out["results"][0]["subject"] == "ok@example.com"
        assert out["failed"] == []


class TestCheckIpAndDomain:
    async def test_ip_shows_feeds_and_host(self, engine):
        payload = {
            "profile": "default",
            "decision": "challenge",
            "score": 50,
            "confidence": 0.7,
            "action": None,
            "signals": [
                {"id": "feed:tor_exits:0", "category": "anonymizer", "weight": 25, "match": "185.1.1.1", "source": "tor_exits", "severity": "medium"},
                {"id": "feed:ipsum:1", "category": "abuse", "weight": 25, "match": "185.1.1.1", "source": "ipsum", "severity": "medium"},
            ],
            "enrichment": {"ip": "185.1.1.1", "country": "Germany", "country_iso": "DE", "asn": 12345, "asn_organization": "Example AS", "hostname": "exit.example"},
        }
        engine(route({"/v1/check/ip/185.1.1.1": payload}))
        out = await server.monapi_check_ip("185.1.1.1")
        assert "`feed:tor_exits:0`" in out
        assert "AS12345 Example AS" in out
        assert "Germany (DE)" in out

    async def test_domain_shows_resolved_ips(self, engine):
        payload = {
            "profile": "default",
            "decision": "allow",
            "score": 0,
            "confidence": 0.2,
            "action": None,
            "signals": [],
            "enrichment": {"domain": "example.com", "resolved_ips": ["93.184.216.34"], "mx_hosts": []},
        }
        engine(route({"/v1/check/domain/example.com": payload}))
        out = await server.monapi_check_domain("example.com")
        assert "93.184.216.34" in out


class TestExplainDecision:
    async def test_exact_and_pattern_ids(self, engine):
        engine(route({"/v1/signals": CATALOGUE}))
        out = await server.monapi_explain_decision(["email:no_mx", "feed:ipsum:0"])
        assert "No MX and no A fallback." in out
        assert "Transient DNS failures" in out
        assert "The IP is listed by that feed." in out

    async def test_unknown_id_is_explained_not_hidden(self, engine):
        engine(route({"/v1/signals": CATALOGUE}))
        out = await server.monapi_explain_decision(["made:up"])
        assert "Not in this engine's catalogue" in out

    async def test_catalogue_fetched_once(self, engine):
        calls: list[httpx.Request] = []
        engine(route({"/v1/signals": CATALOGUE}, calls))
        await server.monapi_explain_decision(["email:no_mx"])
        await server.monapi_explain_decision(["email:no_mx"])
        assert len([c for c in calls if c.url.path == "/v1/signals"]) == 1

    async def test_score_explains_the_threshold(self, engine):
        engine(route({"/v1/signals": CATALOGUE, "/v1/profiles": PROFILES}))
        out = await server.monapi_explain_decision(["email:no_mx"], score=65, profile="checkout")
        assert "blocked" in out and "60" in out

    async def test_score_below_challenge(self, engine):
        engine(route({"/v1/signals": CATALOGUE, "/v1/profiles": PROFILES}))
        out = await server.monapi_explain_decision(["email:no_mx"], score=10, profile="checkout")
        assert "allowed" in out

    async def test_old_engine_without_catalogue(self, engine):
        engine(route({}))
        out = await server.monapi_explain_decision(["email:no_mx"])
        assert "update the engine" in out


class TestListProfiles:
    async def test_table(self, engine):
        engine(route({"/v1/profiles": PROFILES}))
        out = await server.monapi_list_profiles()
        assert "`checkout`" in out
        assert "anonymizer=40" in out

    async def test_json(self, engine):
        engine(route({"/v1/profiles": PROFILES}))
        out = json.loads(await server.monapi_list_profiles(response_format=ResponseFormat.JSON))
        assert out == PROFILES


class TestErrors:
    """The error text is the interface — an agent acts on these sentences."""

    async def test_missing_api_key(self):
        client = MonapiClient(EngineConfig(base_url="http://engine.test", api_key=""))
        with pytest.raises(MonapiError, match="MONAPI_API_KEY"):
            await client.get("/v1/profiles")

    async def test_rejected_key(self, engine):
        engine(lambda request: httpx.Response(403))
        out = await server.monapi_check_email("a@example.com")
        assert "rejected the API key" in out

    async def test_unknown_profile_lists_the_real_ones(self, engine):
        engine(
            lambda request: httpx.Response(
                400, json={"detail": {"error": "unknown_profile", "available": ["checkout", "default"]}}
            )
        )
        out = await server.monapi_check_email("a@example.com", profile="nope")
        assert "checkout, default" in out

    async def test_timeout_names_the_knob(self, engine):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out", request=request)

        engine(handler)
        out = await server.monapi_check_email("a@example.com")
        assert "MONAPI_TIMEOUT" in out

    async def test_html_instead_of_json(self, engine):
        engine(lambda request: httpx.Response(200, text="<html>website</html>"))
        out = await server.monapi_check_email("a@example.com")
        assert "not at the website" in out

    async def test_rate_limit_retries_then_explains(self, engine, monkeypatch):
        import monapi_mcp.client as client_module

        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr(client_module.asyncio, "sleep", fake_sleep)
        attempts: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(request)
            return httpx.Response(429, headers={"Retry-After": "1"})

        engine(handler)
        out = await server.monapi_check_email("a@example.com")
        assert len(attempts) == client_module.MAX_RETRIES
        assert sleeps == [1.0, 1.0]
        assert "RATE_LIMIT_EMAIL" in out

    async def test_rate_limit_recovers(self, engine, monkeypatch):
        import monapi_mcp.client as client_module

        async def fake_sleep(seconds: float) -> None:
            return None

        monkeypatch.setattr(client_module.asyncio, "sleep", fake_sleep)
        state = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            state["n"] += 1
            if state["n"] == 1:
                return httpx.Response(429)
            return httpx.Response(200, json=CLEAN)

        engine(handler)
        out = await server.monapi_check_email("a@example.com")
        assert "**allow**" in out


class TestToolRegistration:
    async def test_all_tools_exposed(self):
        names = {t.name for t in await server.mcp.list_tools()}
        assert names == {
            "monapi_check_email",
            "monapi_check_emails",
            "monapi_check_ip",
            "monapi_check_domain",
            "monapi_explain_decision",
            "monapi_list_profiles",
        }

    async def test_every_tool_is_read_only(self):
        for tool in await server.mcp.list_tools():
            assert tool.annotations.read_only_hint is True
            assert tool.annotations.destructive_hint is False
            assert tool.annotations.title

    async def test_schemas_are_flat_and_described(self):
        for tool in await server.mcp.list_tools():
            for name, spec in tool.input_schema["properties"].items():
                assert spec.get("description"), f"{tool.name}.{name} has no description"
