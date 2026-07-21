# CHECKLIST
# - Run dev: docker compose -f fastapi/docker-compose.yml up --build
# - Build:   docker compose -f fastapi/docker-compose.yml build
# - Lint:    (optional) ruff/pyright not wired in MVP

# monapi-engine (FastAPI)

Minimal self-hostable abuse decision engine API (allow|challenge|block).

What you get:
- FastAPI API service
- Worker that periodically downloads public threat/disposable feeds and builds a local index
- Caddy reverse proxy (TLS on `api.monapi.io` when DNS points to the host)

## Quickstart (local)

1) Copy env file:

```bash
cp fastapi/.env.example fastapi/.env
```

For production set in `fastapi/.env`:
- `PUBLIC_HOST=api.monapi.io`
- keep `ACME_EMAIL=monapi@projektsued.de`

2) Start:

```bash
docker compose -f fastapi/docker-compose.yml up --build
```

3) Smoke:

```bash
curl http://localhost:18000/health
curl -H "X-API-Key: dev-key-1" http://localhost:18000/v1/check/ip/1.1.1.1
```

## Notes

- Email checks try DNS (MX) + SMTP RCPT probing. Many clouds block outbound TCP/25; if blocked, the API returns `deliverability=unknown` (not a 500).
- Feeds are downloaded into `fastapi/data/feeds/` and indexed into `fastapi/data/index/`.
