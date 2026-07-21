# monapi-engine (FastAPI)

Self-hostable abuse decision engine API (allow|challenge|block).

What you get:
- FastAPI API service with policy profiles (`?profile=`)
- Worker that periodically downloads public threat/disposable feeds, builds
  a local IPv4+IPv6 index and keeps the GeoIP database fresh
- Optional enrichment: Geo/ASN/rDNS via a local MMDB (ip66.dev, no account)
- Optional email verification via Reoon (off by default, no SMTP probing)

## Quickstart (local)

```bash
cp .env.example .env
docker compose up --build

curl http://localhost:18000/health
curl -H "X-API-Key: dev-key-1" http://localhost:18000/v1/check/ip/1.1.1.1
curl -H "X-API-Key: dev-key-1" "http://localhost:18000/v1/check/ip/1.1.1.1?profile=checkout"
```

## Policy profiles

Named variants of thresholds / weight overrides / ignored categories, defined
in `app/data/policies.yaml`, selected per request via `?profile=<name>`.
Unknown profiles return 400 with the list of available profiles.

## Enrichment

Set `ENRICHER=geoip` to add ASN, organization, country and rDNS hostname to
IP responses. The MMDB is downloaded daily by the worker (or manually via
`scripts/update-geoip.sh`). ip66 provides no city level; a MaxMind key can
be added later without code changes.

## Email checks

No SMTP RCPT probing (protects the sending IP's reputation). Signals come
from syntax validation, MX existence, disposable/free-mail lists, role
accounts, typo detection and MX-IP reputation. Set `EMAIL_VERIFIER=reoon`
plus `REOON_API_KEY` for external verification.

## Notes

- Feeds land in `/data/feeds/`, the index in `/data/index/`, GeoIP in `/data/geoip/`.
- Caddy reverse proxy is included for standalone TLS; behind an existing
  reverse proxy (e.g. Traefik) run the API container without it.
