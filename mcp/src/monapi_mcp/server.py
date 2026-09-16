#!/usr/bin/env python3
"""MCP server for a monapi engine.

Gives an agent the same decision the engine gives a signup form: allow,
challenge or block, with the signals behind it. Points at any instance —
a self-hosted engine via MONAPI_URL, or the hosted API by default.

Environment:
    MONAPI_URL          engine base URL (default https://api.monapi.io)
    MONAPI_API_KEY      required; a key the instance knows
    MONAPI_PROFILE      default policy profile (default "default")
    MONAPI_TIMEOUT      per-request timeout in seconds (default 10)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from monapi_mcp.client import EngineConfig, MonapiClient, MonapiError
from monapi_mcp.format import (
    ResponseFormat,
    as_json,
    format_batch,
    format_check,
    format_explanation,
    format_profiles,
)

# httpx logs every request at INFO. On a stdio server that is noise in
# the client's log for no benefit.
logging.getLogger("httpx").setLevel(logging.WARNING)

mcp = MCPServer("monapi_mcp")

_config = EngineConfig.from_env()
_client = MonapiClient(_config)

# The engine's email check is rate limited (10/minute by default), so a
# batch stays deliberately narrow and lets the client's backoff absorb
# the rest rather than hammering and failing.
BATCH_CONCURRENCY = 4


def _annotations(title: str, *, open_world: bool = True) -> ToolAnnotations:
    """Every tool here reads; none of them change anything on the engine."""
    return ToolAnnotations(
        title=title,
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=open_world,
    )


async def _run_check(kind: str, value: str, profile: str | None, fmt: ResponseFormat) -> str:
    """Shared body of the three single-subject check tools."""
    try:
        result = await _client.check(kind, value, profile)
    except MonapiError as exc:
        return f"Error: {exc}"
    if fmt == ResponseFormat.JSON:
        return as_json(result)
    return format_check(value, result)


@mcp.tool(
    name="monapi_check_email",
    annotations=_annotations("Check an email address"),
)
async def monapi_check_email(
    email: Annotated[str, Field(description="Address to check, e.g. 'user@mailinator.com'", min_length=3, max_length=320)],
    profile: Annotated[str | None, Field(description="Policy profile, e.g. 'checkout' or 'newsletter'. Omit for the configured default; monapi_list_profiles shows what each does.")] = None,
    response_format: Annotated[ResponseFormat, Field(description="'markdown' for a readable verdict, 'json' for the full engine response")] = ResponseFormat.MARKDOWN,
) -> str:
    """Judge one email address: allow, challenge or block, with the reasons.

    Checks domain blocklists (disposable, phishing, malware), mail
    routing (MX records), the reputation of the mail servers' IPs, role
    accounts and likely typos. No mailbox probing — the address is not
    contacted.

    Returns markdown: the decision, score out of 100, each signal with
    its weight, and the context that informs a follow-up (deliverability,
    a `did_you_mean` correction, MX hosts). With response_format='json',
    the engine's full response including evidence and timing.

    Use when: judging a signup, a lead, a contact form submission, or an
    address pasted from a list.
    Don't use when: you need many addresses — monapi_check_emails is one
    call and reports which ones need attention.
    """
    return await _run_check("email", email, profile, response_format)


@mcp.tool(
    name="monapi_check_emails",
    annotations=_annotations("Check many email addresses"),
)
async def monapi_check_emails(
    emails: Annotated[list[str], Field(description="Addresses to check, e.g. ['a@example.com', 'b@mailinator.com']", min_length=1, max_length=100)],
    profile: Annotated[str | None, Field(description="Policy profile applied to every address")] = None,
    response_format: Annotated[ResponseFormat, Field(description="'markdown' groups by decision; 'json' returns every full response")] = ResponseFormat.MARKDOWN,
) -> str:
    """Check a list of email addresses and report which ones need attention.

    Runs the same check as monapi_check_email over the whole list, a few
    at a time, and backs off when the engine rate-limits. Addresses that
    could not be checked are listed separately with the reason — a
    partial answer, never a silent gap.

    Returns markdown grouped by decision: blocks and challenges with
    their signals first, allows as a plain list, failures last. With
    response_format='json', an object with `profile`, `results` and
    `failed`.

    Note on volume: the engine's email check defaults to 10 requests per
    minute per key, so a list of 100 takes several minutes and may end
    with unchecked entries. For recurring bulk work, raise
    RATE_LIMIT_EMAIL on the engine.

    Use when: vetting a signup export, a mailing list, a batch of leads.
    Don't use when: one address — monapi_check_email returns more detail.
    """
    semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)
    results: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []

    async def one(address: str) -> None:
        async with semaphore:
            try:
                result = await _client.check("email", address, profile)
            except MonapiError as exc:
                failed.append({"subject": address, "error": str(exc)})
                return
            results.append({"subject": address, "result": result})

    # Deduplicate but keep the caller's order — lists of signups repeat.
    seen: set[str] = set()
    ordered = [e for e in emails if not (e in seen or seen.add(e))]

    await asyncio.gather(*(one(address) for address in ordered))

    order = {address: i for i, address in enumerate(ordered)}
    results.sort(key=lambda r: order[r["subject"]])
    failed.sort(key=lambda f: order[f["subject"]])

    used_profile = profile or _config.profile
    if response_format == ResponseFormat.JSON:
        return as_json({"profile": used_profile, "results": results, "failed": failed})
    return format_batch(results, used_profile, failed)


@mcp.tool(
    name="monapi_check_ip",
    annotations=_annotations("Check an IP address"),
)
async def monapi_check_ip(
    ip: Annotated[str, Field(description="IPv4 or IPv6 address, e.g. '185.220.101.1'", min_length=3, max_length=45)],
    profile: Annotated[str | None, Field(description="Policy profile to apply")] = None,
    response_format: Annotated[ResponseFormat, Field(description="'markdown' or 'json'")] = ResponseFormat.MARKDOWN,
) -> str:
    """Judge one IP address against public abuse, VPN/Tor and datacenter feeds.

    Every feed listing the address contributes a signal; weights stack,
    so an address on several lists reaches block range without any single
    feed being decisive. When the engine has GeoIP enabled, the response
    also carries country, ASN and reverse DNS.

    Returns markdown: decision, score, each feed that listed the address,
    and host context. With response_format='json', the full response.

    Use when: judging a request's origin, a login, a server in a log.
    Don't use when: the question is about a domain or an address — those
    have their own tools and check more than the IP.
    """
    return await _run_check("ip", ip, profile, response_format)


@mcp.tool(
    name="monapi_check_domain",
    annotations=_annotations("Check a domain"),
)
async def monapi_check_domain(
    domain: Annotated[str, Field(description="Hostname without scheme, e.g. 'example.com'", min_length=3, max_length=253)],
    profile: Annotated[str | None, Field(description="Policy profile to apply")] = None,
    response_format: Annotated[ResponseFormat, Field(description="'markdown' or 'json'")] = ResponseFormat.MARKDOWN,
) -> str:
    """Judge one domain: blocklist hits plus the reputation of where it resolves.

    Checks phishing, malware and disposable-mail lists, then resolves the
    domain and runs each A record through the IP feeds — a clean domain
    on a listed host still surfaces.

    Returns markdown: decision, score, signals, resolved IPs with geo/ASN
    where available, and MX hosts. With response_format='json', the full
    response.

    Use when: judging a link, a referrer, a website, a sender domain.
    Don't use when: you have a full email address — monapi_check_email
    adds mailbox-level checks on top of this.
    """
    return await _run_check("domain", domain, profile, response_format)


@mcp.tool(
    name="monapi_explain_decision",
    annotations=_annotations("Explain signal ids", open_world=False),
)
async def monapi_explain_decision(
    signal_ids: Annotated[list[str], Field(description="Signal ids from a check, e.g. ['email:no_mx', 'feed:tor_exits:0']", min_length=1, max_length=25)],
    score: Annotated[int | None, Field(description="The score from that check, to explain how the thresholds applied", ge=0, le=100)] = None,
    profile: Annotated[str | None, Field(description="The profile used for that check")] = None,
    response_format: Annotated[ResponseFormat, Field(description="'markdown' or 'json'")] = ResponseFormat.MARKDOWN,
) -> str:
    """Explain what signal ids from a check actually mean, and when they mislead.

    Reads the engine's own signal catalogue, so the answer matches the
    instance that produced the decision rather than general knowledge.
    For each id: what is true when it fires, what to do about it, and the
    cases where it fires on something legitimate. Given `score` and
    `profile`, also shows which threshold the score crossed.

    Returns markdown, one section per id. With response_format='json',
    the catalogue entries verbatim.

    Use when: justifying a decision to a user, deciding whether a signal
    warrants acting, or writing rules against signal ids.
    Don't use when: you have not run a check yet — the ids come from one.
    """
    try:
        entries = {sid: await _client.explain(sid) for sid in signal_ids}
    except MonapiError as exc:
        return f"Error: {exc}"

    if response_format == ResponseFormat.JSON:
        return as_json({"signals": entries})

    lines = ["# What these signals mean", ""]
    for sid, entry in entries.items():
        lines.extend(format_explanation(sid, entry))

    if score is not None:
        try:
            payload = await _client.profiles()
        except MonapiError:
            payload = {"profiles": []}
        name = profile or _config.profile
        match = next((p for p in payload.get("profiles", []) if p.get("name") == name), None)
        if match:
            thresholds = match.get("thresholds", {})
            challenge, block = thresholds.get("challenge"), thresholds.get("block")
            if score >= block:
                verdict = f"blocked: {score} is at or above the block threshold of {block}"
            elif score >= challenge:
                verdict = (
                    f"challenged: {score} is at or above the challenge threshold of "
                    f"{challenge} but below block at {block}"
                )
            else:
                verdict = f"allowed: {score} is below the challenge threshold of {challenge}"
            lines.append(f"## Why the verdict\n\nWith profile `{name}` the request was {verdict}.")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


@mcp.tool(
    name="monapi_list_profiles",
    annotations=_annotations("List policy profiles", open_world=False),
)
async def monapi_list_profiles(
    response_format: Annotated[ResponseFormat, Field(description="'markdown' or 'json'")] = ResponseFormat.MARKDOWN,
) -> str:
    """List the policy profiles this engine offers and what each one changes.

    Profiles are per-instance configuration: thresholds for challenge and
    block, per-category weight overrides, and categories ignored
    entirely. A stricter profile fits checkout; a looser one fits a
    newsletter signup where a false block costs a subscriber.

    Returns a markdown table of every profile with its thresholds,
    overrides and ignores. With response_format='json', the raw payload.

    Use when: choosing a profile, or explaining why the same address got
    different verdicts in two places.
    """
    try:
        payload = await _client.profiles()
    except MonapiError as exc:
        return f"Error: {exc}"
    if response_format == ResponseFormat.JSON:
        return as_json(payload)
    return format_profiles(payload)


def main() -> None:
    """Run the server over stdio."""
    try:
        mcp.run()
    finally:
        try:
            asyncio.run(_client.aclose())
        except RuntimeError:
            pass


if __name__ == "__main__":
    main()
