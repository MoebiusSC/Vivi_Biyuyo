#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
test -s .env || { echo 'Missing .env'; exit 1; }
unconfigured=false
if [[ "${1:-}" = --allow-unconfigured ]]; then unconfigured=true; fi
if ! test -s secrets/fomo_api_key; then
  $unconfigured || { echo 'Missing FOMO secret'; exit 1; }
  install -d -m 0700 secrets
  touch secrets/fomo_api_key
fi
chmod 600 .env
chmod 700 secrets
chown 10001:10001 secrets/fomo_api_key
chmod 400 secrets/fomo_api_key
docker compose config --quiet
docker compose build --pull
docker compose up -d --wait --wait-timeout 120
curl -fsS http://127.0.0.1:8080/health
if $unconfigured; then
  test "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/ready)" = 503
  echo 'Unconfigured staging deployment only: FOMO readiness is pending.'
else
  curl -fsS http://127.0.0.1:8080/ready
fi
curl -fsS http://127.0.0.1:8080/ > /dev/null
echo 'Local liveness and dashboard verified. Enable HTTPS after DNS/auth configuration.'
