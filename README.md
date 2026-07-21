# monapi

Self-hosted request-time decision API for abuse prevention — and a live
demonstration of how we run and monitor API services.

Given an IP address, domain, or email, monapi returns a decision
(`allow` | `challenge` | `block`) with a score, the signals that produced
it, and the evidence behind each signal. It is built to be self-hosted:
no external calls at request time, no data leaving your infrastructure.

## Repository layout

| Directory | Component |
|---|---|
| `engine/` | FastAPI decision engine (checks → scoring → policy) + feed sync worker |
| `site/` | Next.js product site with an interactive console |
| `bot/` | Telegram bot for quick `/ip` and `/domain` lookups |

## Quick start (engine)

```bash
cd engine
docker compose up --build

curl http://localhost:18000/health
curl -H "X-API-Key: dev-key-1" http://localhost:18000/v1/check/ip/1.1.1.1
```

Feeds are synced from public blocklist sources every 15 minutes and held in
an in-memory trie index. API keys are bootstrapped via `BOOTSTRAP_API_KEYS`.

## Status

Maintained as time permits. This project runs in production on our own
infrastructure; issues and PRs are welcome but responses may take a while.

## License

MIT — see [LICENSE](LICENSE).
