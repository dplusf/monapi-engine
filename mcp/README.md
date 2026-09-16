# monapi MCP server

Gives an agent the decision a signup form gets: **allow**, **challenge**
or **block** for an email address, IP or domain, with the signals behind
it and what they mean.

Points at any monapi engine — your own instance via `MONAPI_URL`, or the
hosted API. Nothing is stored here; the server is a thin, read-only
client.

## Tools

| Tool | What it does |
|---|---|
| `monapi_check_email` | One address: blocklists, MX, mail server reputation, role account, typo |
| `monapi_check_emails` | A list of addresses, grouped by decision — signups, leads, a mailing list |
| `monapi_check_ip` | One IP against abuse, VPN/Tor and datacenter feeds, plus geo/ASN |
| `monapi_check_domain` | One domain: blocklists plus the reputation of where it resolves |
| `monapi_explain_decision` | What signal ids mean, what to do about them, and when they mislead |
| `monapi_list_profiles` | The policy profiles this instance offers and what each changes |

Every tool takes `response_format`: `markdown` (default, readable) or
`json` (the engine's full response).

## Install

```bash
uv pip install -e .
# or: pip install -e .
```

Requires Python 3.11+.

## Configure

| Variable | Default | Meaning |
|---|---|---|
| `MONAPI_URL` | `https://api.monapi.io` | Engine base URL — point at your own instance |
| `MONAPI_API_KEY` | — | **Required.** A key the instance knows (`BOOTSTRAP_API_KEYS`) |
| `MONAPI_PROFILE` | `default` | Policy profile used when a call does not name one |
| `MONAPI_TIMEOUT` | `10` | Per-request timeout in seconds |

### Claude Code

```bash
claude mcp add monapi \
  --env MONAPI_URL=http://localhost:18000 \
  --env MONAPI_API_KEY=dev-key-1 \
  -- uv run --directory /path/to/monapi-engine/mcp monapi-mcp
```

### Claude Desktop / any MCP client

```json
{
  "mcpServers": {
    "monapi": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/monapi-engine/mcp", "monapi-mcp"],
      "env": {
        "MONAPI_URL": "http://localhost:18000",
        "MONAPI_API_KEY": "dev-key-1",
        "MONAPI_PROFILE": "checkout"
      }
    }
  }
}
```

## Examples

> "Is `bitte@mailinator.com` a real address?"

```
# bitte@mailinator.com → block

Score 80/100 · confidence 0.9 · profile `default`

## Signals (1)
- `email_domain:disposable` (weight 40, disposable) — mailinator.com via disposable_ivolo
```

> "Check these 40 signups and tell me which ones to look at."

Calls `monapi_check_emails` once and returns blocks and challenges with
their signals, allows as a list, and anything it could not check with the
reason.

> "Why was that blocked?"

`monapi_explain_decision` reads the engine's own signal catalogue — the
meaning, what to do, and the cases where the signal fires on something
legitimate.

## Rate limits

The engine's email check defaults to **10 requests per minute per key**.
`monapi_check_emails` runs four at a time and backs off on HTTP 429, so a
long list takes minutes and may end with unchecked entries — these are
reported, never silently dropped. For recurring bulk work, raise
`RATE_LIMIT_EMAIL` on the engine.

## Requirements

The engine must expose `/v1/signals` and `/v1/profiles`
(`monapi_explain_decision` and `monapi_list_profiles` need them). Older
instances answer 404 there; the check tools still work.

## Development

```bash
uv pip install -e ".[dev]"
python -m pytest
npx @modelcontextprotocol/inspector uv run monapi-mcp   # interactive
```
