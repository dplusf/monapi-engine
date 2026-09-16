"""Turning engine responses into something a model can read cheaply.

Raw check responses are verbose — evidence duplicates signals, enrichment
carries fields that rarely matter. The markdown here keeps what changes a
decision and drops the rest; `json` returns the response untouched for
callers that want everything.
"""
from __future__ import annotations

import json
from enum import Enum
from typing import Any

DECISION_ORDER = ["block", "challenge", "allow"]


class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


def as_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


def signal_line(signal: dict[str, Any]) -> str:
    """`email_domain:disposable` (weight 40, disposable) — mailinator.com via disposable_ivolo"""
    parts = [f"`{signal.get('id', '?')}` (weight {signal.get('weight', '?')}"]
    if signal.get("category"):
        parts.append(f", {signal['category']}")
    parts.append(")")
    line = "".join(parts)
    match = signal.get("match")
    source = signal.get("source")
    if match:
        line += f" — {match}"
    if source:
        line += f" via {source}"
    return line


def _enrichment_lines(enrichment: dict[str, Any]) -> list[str]:
    """The enrichment fields that actually inform a follow-up action."""
    out: list[str] = []

    if enrichment.get("did_you_mean"):
        out.append(f"- **Did you mean**: {enrichment['did_you_mean']} — offer this correction in the form")
    if enrichment.get("deliverability") and enrichment["deliverability"] != "unknown":
        out.append(f"- **Deliverability**: {enrichment['deliverability']}")
    if enrichment.get("is_catchall"):
        out.append("- **Catch-all domain**: the address cannot be verified individually")
    if enrichment.get("is_role_account"):
        out.append("- **Role account**: shared mailbox, not a person")

    mx = enrichment.get("mx_hosts") or []
    if mx:
        shown = ", ".join(mx[:3]) + (f" (+{len(mx) - 3} more)" if len(mx) > 3 else "")
        out.append(f"- **MX**: {shown}")

    geo_bits = []
    if enrichment.get("country"):
        geo_bits.append(f"{enrichment['country']} ({enrichment.get('country_iso', '')})".strip())
    if enrichment.get("asn"):
        geo_bits.append(f"AS{enrichment['asn']} {enrichment.get('asn_organization', '')}".strip())
    if enrichment.get("hostname"):
        geo_bits.append(enrichment["hostname"])
    if geo_bits:
        out.append(f"- **Host**: {' · '.join(geo_bits)}")

    ips = enrichment.get("resolved_ips") or []
    if ips:
        shown = ", ".join(ips[:3]) + (f" (+{len(ips) - 3} more)" if len(ips) > 3 else "")
        out.append(f"- **Resolves to**: {shown}")

    return out


def format_check(subject: str, result: dict[str, Any]) -> str:
    """One check as markdown."""
    decision = result.get("decision", "?")
    score = result.get("score", "?")
    confidence = result.get("confidence", "?")
    profile = result.get("profile", "default")

    lines = [
        f"# {subject} → **{decision}**",
        "",
        f"Score {score}/100 · confidence {confidence} · profile `{profile}`",
        "",
    ]

    signals = result.get("signals") or []
    if signals:
        lines.append(f"## Signals ({len(signals)})")
        lines.extend(f"- {signal_line(s)}" for s in signals)
        lines.append("")
        lines.append(
            "Use `monapi_explain_decision` with these ids for what they mean and when they are wrong."
        )
    else:
        lines.append("## Signals")
        lines.append(
            "None. No source had anything on this — that is an absence of evidence, "
            "not a clean bill of health."
        )
    lines.append("")

    enrichment = _enrichment_lines(result.get("enrichment") or {})
    if enrichment:
        lines.append("## Context")
        lines.extend(enrichment)
        lines.append("")

    action = result.get("action")
    if action:
        lines.append(
            f"## Action\n`{action.get('type')}` — retry after "
            f"{action.get('retry_after_seconds')}s ({action.get('reason')})"
        )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def format_batch(results: list[dict[str, Any]], profile: str, failed: list[dict[str, str]]) -> str:
    """A batch of email checks, grouped by decision.

    Blocks and challenges come first with their signals; allows are a
    plain list, because the whole point of a batch is finding the few
    addresses that need attention.
    """
    by_decision: dict[str, list[dict[str, Any]]] = {d: [] for d in DECISION_ORDER}
    for entry in results:
        by_decision.setdefault(entry["result"].get("decision", "allow"), []).append(entry)

    counts = " · ".join(f"{len(by_decision[d])} {d}" for d in DECISION_ORDER)
    lines = [
        f"# Checked {len(results)} of {len(results) + len(failed)} with profile `{profile}`",
        "",
        counts + (f" · {len(failed)} failed" if failed else ""),
        "",
    ]

    for decision in ("block", "challenge"):
        entries = by_decision.get(decision) or []
        if not entries:
            continue
        lines.append(f"## {decision} ({len(entries)})")
        for entry in entries:
            result = entry["result"]
            ids = ", ".join(f"`{s.get('id')}`" for s in (result.get("signals") or [])) or "no signals"
            detail = f"- **{entry['subject']}** — score {result.get('score')} — {ids}"
            hint = (result.get("enrichment") or {}).get("did_you_mean")
            if hint:
                detail += f" — did you mean {hint}?"
            lines.append(detail)
        lines.append("")

    allowed = by_decision.get("allow") or []
    if allowed:
        lines.append(f"## allow ({len(allowed)})")
        lines.append(", ".join(e["subject"] for e in allowed))
        lines.append("")

    if failed:
        lines.append(f"## Not checked ({len(failed)})")
        lines.extend(f"- **{f['subject']}** — {f['error']}" for f in failed)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def format_explanation(signal_id: str, entry: dict[str, Any] | None) -> list[str]:
    """One signal explained, as markdown lines."""
    if entry is None:
        return [
            f"### `{signal_id}`",
            "",
            "Not in this engine's catalogue. Either the id is mistyped, or the "
            "engine emitting it is newer than the one being asked.",
            "",
        ]

    lines = [f"### `{signal_id}`", ""]
    meta = [
        f"category `{entry.get('category')}`",
        f"weight {entry.get('weight')}",
        f"severity {entry.get('severity')}",
        f"source {entry.get('source')}",
    ]
    lines.append(" · ".join(meta))
    lines.append("")
    lines.append(str(entry.get("meaning", "")).strip())
    lines.append("")
    if entry.get("guidance"):
        lines.append(f"**What to do.** {str(entry['guidance']).strip()}")
        lines.append("")
    if entry.get("false_positives"):
        lines.append(f"**When it is wrong.** {str(entry['false_positives']).strip()}")
        lines.append("")
    return lines


def format_profiles(payload: dict[str, Any]) -> str:
    profiles = payload.get("profiles") or []
    lines = [
        "# Policy profiles on this engine",
        "",
        "Pass one as `profile` to any check. Thresholds decide the verdict: "
        "score at or above `block` blocks, at or above `challenge` challenges.",
        "",
        "| Profile | challenge | block | Weight overrides | Ignored categories |",
        "|---|---|---|---|---|",
    ]
    for p in profiles:
        thresholds = p.get("thresholds", {})
        weights = p.get("weights") or {}
        ignore = p.get("ignore") or []
        lines.append(
            "| `{name}` | {challenge} | {block} | {weights} | {ignore} |".format(
                name=p.get("name"),
                challenge=thresholds.get("challenge"),
                block=thresholds.get("block"),
                weights=", ".join(f"{k}={v}" for k, v in sorted(weights.items())) or "—",
                ignore=", ".join(f"`{c}`" for c in ignore) or "—",
            )
        )
    lines.append("")
    return "\n".join(lines)
