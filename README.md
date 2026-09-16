# monapi

[![CI](https://github.com/dplusf/monapi-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/dplusf/monapi-engine/actions/workflows/ci.yml)

Self-hosted request-time decision API for abuse prevention.

Given an IP address, domain, or email, monapi returns a decision
(`allow` | `challenge` | `block`) with a score, the signals that produced
it, and the evidence behind each signal. It is built to be self-hosted:
no external calls at request time, no data leaving your infrastructure.

## Repository layout

| Directory | Component |
|---|---|
| `engine/` | FastAPI decision engine (checks → scoring → policy) + feed sync worker |
| `mcp/` | MCP server — the same decisions as a tool for agents |
| `clients/node/` | `@monapi/client` — TypeScript client, fail-open |
| `docs/` | [Signal reference](docs/signals.md): what every signal id means |

The product website, interactive console and telegram bot are maintained
separately.

## Quick start (engine)

```bash
cd engine
cp .env.example .env
docker compose up --build

curl http://localhost:18000/health
curl -H "X-API-Key: dev-key-1" http://localhost:18000/v1/check/ip/1.1.1.1
curl -H "X-API-Key: dev-key-1" "http://localhost:18000/v1/check/ip/1.1.1.1?profile=checkout"
```

Feeds are synced from public blocklist sources every 15 minutes and held in
an in-memory trie index (IPv4 + IPv6). API keys are bootstrapped via
`BOOTSTRAP_API_KEYS`. Policy profiles (thresholds, weights, ignored
categories) are defined in `engine/app/data/policies.yaml` and selected per
request with `?profile=<name>`. Optional Geo/ASN/rDNS enrichment via
`ENRICHER=geoip` (local MMDB, no account required).

## Endpoints

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` | no | Liveness |
| `GET /ready` | no | Readiness: database, index size, feed age |
| `GET /v1/check/ip/{ip}` | yes | IP reputation |
| `GET /v1/check/domain/{domain}` | yes | Domain reputation |
| `GET /v1/check/email/{email}` | yes | Email validation + reputation |
| `GET /v1/signals` | yes | Signal catalogue — every id this instance can emit |
| `GET /v1/profiles` | yes | Policy profiles and what each one changes |

Checks take `?profile=<name>`. Every response carries `decision`, `score`,
`confidence`, `signals`, `evidence` and `enrichment`; the
[signal reference](docs/signals.md) explains what the ids mean and when
they mislead.

## Using it

```ts
// TypeScript / Next.js — npm install @monapi/client
import { checkEmail } from "@monapi/client";
const { decision, score, signals } = await checkEmail("kontakt@gamil.com");
```

```bash
# From an agent — see mcp/README.md
claude mcp add monapi --env MONAPI_API_KEY=dev-key-1 \
  -- uv run --directory ./mcp monapi-mcp
```

## Status

Maintained as time permits. This project runs in production on our own
infrastructure; issues and PRs are welcome but responses may take a while.

## License

MIT — see [LICENSE](LICENSE).

