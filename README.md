# monapi

Self-hosted request-time decision API for abuse prevention.

Given an IP address, domain, or email, monapi returns a decision
(`allow` | `challenge` | `block`) with a score, the signals that produced
it, and the evidence behind each signal. It is built to be self-hosted:
no external calls at request time, no data leaving your infrastructure.

## Repository layout

| Directory | Component |
|---|---|
| `engine/` | FastAPI decision engine (checks → scoring → policy) + feed sync worker |
| `bot/` | Telegram bot for quick `/ip` and `/domain` lookups |

The product website and interactive console are maintained separately.

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

## Status

Maintained as time permits. This project runs in production on our own
infrastructure; issues and PRs are welcome but responses may take a while.

## License

MIT — see [LICENSE](LICENSE).

