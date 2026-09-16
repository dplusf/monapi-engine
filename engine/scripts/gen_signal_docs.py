#!/usr/bin/env python3
"""Render docs/signals.md from app/data/signals.yaml.

The markdown is generated so the reference cannot drift from what the
engine serves at /v1/signals. Edit the YAML, run this, commit both.

    python scripts/gen_signal_docs.py           # write ../docs/signals.md
    python scripts/gen_signal_docs.py --check   # exit 1 if out of date
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine.signals import load_catalogue  # noqa: E402

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
CATALOGUE = ENGINE / "app" / "data" / "signals.yaml"
OUTPUT = ENGINE.parent / "docs" / "signals.md"

HEADER = """<!-- Generated from engine/app/data/signals.yaml by
     engine/scripts/gen_signal_docs.py — do not edit by hand. -->

# Signal reference

Every check returns a list of `signals`. Each signal is one fact the
engine found, with the weight it contributed to the score. This page is
what those ids mean.

The same data is served as JSON by `GET /v1/signals` on any instance —
use that if you are generating code or building an agent, since feeds and
weights are per-instance configuration.

## How a decision is built

```
signals → sum of weights (capped at 100) = score
score >= block threshold      → block
score >= challenge threshold  → challenge
otherwise                     → allow
```

Thresholds and weights come from the active policy profile
(`?profile=<name>`, see `GET /v1/profiles`). A profile can override the
weight of a whole category or ignore it entirely; the signals you get
back already reflect that, so the weights in a response are the weights
that actually scored.

Two rules for consuming signals in code:

- **Match on the id prefix and the category, not the full id.** Feed
  signal ids carry an index (`feed:ipsum:0`) that shifts when feeds change.
- **Treat an empty signal list as "nothing known", not as "clean".** A
  score of 0 with confidence 0.2 means no source had anything to say.

## Categories

"""

FOOTER = """
## Reading the rest of the response

| Field | Meaning |
|---|---|
| `score` | Sum of signal weights, capped at 100 |
| `confidence` | 0.2 with no signals, 0.5 / 0.7 / 0.9 as total weight passes 0 / 30 / 80 — how much evidence there is, not how likely abuse is |
| `evidence` | The same findings as `signals`, keyed by source, for showing a human why |
| `enrichment` | Facts gathered along the way: resolved IPs, MX hosts, `did_you_mean`, deliverability, geo/ASN |
| `action` | Present on `challenge` only: `retry_after_seconds` and a machine-readable `reason` |
| `profile` | The policy profile that produced this decision |
"""


def _fmt(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, list):
        return ", ".join(f"`{v}`" for v in value)
    return str(value).strip().replace("\n", " ")


def _cell(value: object) -> str:
    """Table-cell safe: placeholders like <category> must not render as HTML."""
    text = _fmt(value)
    if text.startswith("`") or text == "—":
        return text
    if "<" in text:
        return f"`{text}`"
    return text.replace("|", "\\|")


def render(catalogue) -> str:
    out = [HEADER.rstrip("\n")]
    out.append("")

    out.append("| Category | Default weight | What it means |")
    out.append("|---|---|---|")
    for name, spec in catalogue.categories.items():
        spec = spec or {}
        summary = _fmt(spec.get("summary"))
        if spec.get("emitted") is False:
            summary += " **(not emitted by any configured feed today)**"
        out.append(f"| `{name}` | {_cell(spec.get('default_weight'))} | {summary} |")

    out.append("")
    out.append("## Signals")
    out.append("")
    out.append("| Signal | Category | Weight | Severity | Source | Checks |")
    out.append("|---|---|---|---|---|---|")
    for sig in catalogue.signals:
        sid = sig.get("id") or sig.get("id_pattern", "")
        out.append(
            "| `{id}` | {cat} | {weight} | {sev} | {src} | {eps} |".format(
                id=sid,
                cat=_cell(sig.get("category")),
                weight=_cell(sig.get("weight")),
                sev=_cell(sig.get("severity")),
                src=_cell(sig.get("source")),
                eps=_cell(sig.get("endpoints")),
            )
        )

    out.append("")
    out.append("## What each signal means")
    out.append("")
    for sig in catalogue.signals:
        sid = sig.get("id") or sig.get("id_pattern", "")
        out.append(f"### `{sid}`")
        out.append("")
        if sig.get("examples"):
            out.append(f"Examples: {_fmt(sig['examples'])}")
            out.append("")
        out.append(_fmt(sig.get("meaning")))
        out.append("")
        out.append(f"**What to do with it.** {_fmt(sig.get('guidance'))}")
        out.append("")
        if sig.get("false_positives"):
            out.append(f"**When it is wrong.** {_fmt(sig['false_positives'])}")
            out.append("")

    out.append(FOOTER.strip())
    out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify docs are up to date")
    args = parser.parse_args()

    catalogue = load_catalogue(str(CATALOGUE))
    if not catalogue.signals:
        print(f"error: no signals loaded from {CATALOGUE}", file=sys.stderr)
        return 1

    rendered = render(catalogue)

    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != rendered:
            print(
                f"error: {OUTPUT} is out of date — run python scripts/gen_signal_docs.py",
                file=sys.stderr,
            )
            return 1
        print(f"{OUTPUT} is up to date")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(catalogue.signals)} signals)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
