# Vivi Biyuyo

Vivi Biyuyo is a shadow-first memecoin research/trading engine built around the FOMO API.

The first objective is to create proprietary evidence quickly: which FOMO traders generate useful early signals, which flow/safety filters improve outcomes, and how signal quality decays with latency. Live execution is deliberately disabled in v0.1.

## v0.1

- FOMO app-feed WebSocket by default, with optional Growth on-chain mode.
- 7d + 30d leaderboard wallet-quality model keyed by stable userId.
- Smart-money cluster detection by token.
- Token flow, holder-concentration and developer-exit guards.
- Four simultaneous experimental lanes: A Single Copy, B Cluster, C Cluster+Flow, D Cluster+Flow+Safety.
- Atomic persistent state and append-only events/signals, adapted from Hermes reliability patterns.
- Web dashboard and health endpoint.
- Shadow decisions only; no live order adapter exists yet.

## FOMO endpoints

REST base: https://api.fomoapi.io
App feed: wss://api.fomoapi.io/ws/alerts
Growth on-chain feed: wss://api.fomoapi.io/ws/trades
Leaderboards: /v2/leaderboard/{window}
Token stats: /v2/token/{address}/stats
Token devs: /v2/token/{address}/devs

FOMO recommends userId as the stable trader key and eventId as the alert dedupe key.

## Run

    python -m pip install -e ".[dev]"
    export FOMO_API_KEY_FILE=/ruta/privada/fomo_api_key
    python -m vivi_biyuyo.main

The Python entrypoint reads process environment variables. `.env` is loaded by
Docker Compose, not automatically by Python. Without a FOMO key the dashboard
starts, but `/ready` returns 503.

Dashboard: http://localhost:8080

Default persistent directory: state/vivi_biyuyo

## OCI shadow/paper deployment

See [the OCI runbook](docs/OCI.md) for the modular collector/intelligence/strategies,
SQLite inbox and transactional paper portfolios, latency research, Compose volume,
Docker secrets, health/readiness, backups and optional authenticated HTTPS with Caddy.

`VIVI_MODE=shadow` is the default; `paper` simulates independent A/B/C/D portfolios
using observed prices. Live trading remains unavailable and startup rejects live mode.
No signing credentials are needed. Run `pytest -q` before deployment.
