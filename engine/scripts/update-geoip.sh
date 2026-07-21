#!/bin/sh
# Download the GeoIP MMDB (default: ip66.dev, CC BY 4.0, no account/key).
# Used by the worker daily; safe to run manually or from cron.
set -eu

DEST_DIR="${GEOIP_DIR:-/data/geoip}"
URL="${GEOIP_URL:-https://downloads.ip66.dev/db/ip66.mmdb}"

mkdir -p "$DEST_DIR"
tmp="$DEST_DIR/.ip66.mmdb.tmp"
trap 'rm -f "$tmp"' EXIT

curl -fsSL "$URL" -o "$tmp"
mv "$tmp" "$DEST_DIR/ip66.mmdb"
trap - EXIT
echo "geoip updated: $DEST_DIR/ip66.mmdb"
