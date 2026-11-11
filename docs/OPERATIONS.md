# Operations runbook

How to run, watch, back up and upgrade a Kestrel Intelligence deployment made with Docker Compose. The platform is a research and **simulated** trading tool, so there are no real funds or broker connections to protect. User accounts, strategies, research runs and paper portfolios still live in PostgreSQL and are worth keeping.

Commands assume you are in the repository root. For the HTTPS deployment, set the file list once per shell so every command picks up the production override:

```bash
export COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml
```

## Services

| Service | Role | State |
|---|---|---|
| `postgres` | All persistent data | Volume `pgdata`. **Back this up.** |
| `redis` | Cache, rate limits, the background-job lease | None worth keeping. Persistence is off on purpose. |
| `backend` | FastAPI API. Runs migrations on start. Competes for the job lease unless `RUN_BACKGROUND_JOBS=false`. | None |
| `worker` (profile `worker`) | Background jobs only: order matching and margin calls, equity snapshots, strategy alerts and forward tests, history backfill, demo purge | None |
| `frontend` | Next.js pages and the same-origin `/api/v1` proxy | None |
| `caddy` (production) | HTTPS, certificates, routing | Volume `caddy_data` (certificates; re-issued automatically if lost) |
| `prometheus` (profile `monitoring`) | Metrics and alert rules | Volume `promdata` (15 days by default) |

## Health checks

| Check | Meaning |
|---|---|
| `GET /health` | The API process is up. Used by the container healthcheck. |
| `GET /health/ready` | Database reachable, cache backend, market-data provider, live-stream status and whether this instance holds the job lease. |
| `GET /metrics` | Prometheus metrics from the API (see below). |
| `worker:9100/metrics` | Prometheus metrics from the worker. |

With the production override the API isn't published, so check it from inside the network:

```bash
docker compose exec backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready').read().decode())"
```

## Metrics and alerts

Start Prometheus alongside the stack:

```bash
docker compose --profile monitoring up -d          # add --profile worker if you run the worker
```

The UI listens on <http://127.0.0.1:9090>, bound to localhost. On a server, reach it through an SSH tunnel (`ssh -L 9090:127.0.0.1:9090 you@server`). Configuration is in [`deploy/prometheus.yml`](../deploy/prometheus.yml) and the alert rules in [`deploy/prometheus-alerts.yml`](../deploy/prometheus-alerts.yml). Firing alerts show under **Alerts**. To get them by email or chat, add an Alertmanager.

`/metrics` is never routed publicly by Caddy. If the API port is exposed some other way, set `METRICS_TOKEN` and uncomment the `authorization` blocks in `deploy/prometheus.yml`, putting the same token in `deploy/metrics-token`. Git ignores that file.

| Metric | Type | What it tells you |
|---|---|---|
| `kestrel_http_requests_total{method,route,status}` | counter | Traffic and errors per route template (e.g. `/api/v1/strategies/{strategy_id}`) |
| `kestrel_http_request_duration_seconds{method,route}` | histogram | Latency per route |
| `kestrel_background_job_runs_total{job,outcome}` | counter | Job runs, `ok` or `error` |
| `kestrel_background_job_duration_seconds{job}` | histogram | Job run time |
| `kestrel_background_job_last_success_timestamp_seconds{job}` | gauge | When each job last completed |
| `kestrel_background_jobs_leader` / `_running` | gauge | Whether this process holds the job lease / runs the job loops |
| `kestrel_market_stream_connected`, `_healthy`, `_last_message_age_seconds` | gauge | Live Coinbase price feed. Unhealthy means REST polling is in use. |
| `kestrel_market_stream_messages_total`, `_reconnects_total` | counter | Feed throughput and stability |
| `kestrel_ws_clients` | gauge | Browsers connected to the live price socket |
| `kestrel_paper_orders_total{source,side,status}` | counter | Simulated orders by `user`, `strategy` (forward tests) or `margin_call` |
| `kestrel_paper_fills_total{side}`, `kestrel_paper_margin_calls_total` | counter | Simulated fills and forced short covers |
| `kestrel_alert_events_total{kind}` | counter | Strategy alert events (`entry`, `exit`) |
| `kestrel_emails_total{outcome}` | counter | Email `sent`, `failed` or `console` (logged only) |

Each process keeps its own counters. Prometheus scrapes every instance; use `sum()` across them.

### What to do when an alert fires

| Alert | First steps |
|---|---|
| **ApiDown** | `docker compose ps` and `docker compose logs backend --tail 100`. A failed migration stops the container at start; see [Upgrades](#upgrades). |
| **NoBackgroundJobLeader** | No process runs jobs, so limit orders, margin calls, alerts and snapshots are paused. Check that Redis is up (`docker compose exec redis redis-cli ping`) and look for `background_jobs_lease_failed` in the logs. If every API instance has `RUN_BACKGROUND_JOBS=false`, start the worker. |
| **OrderMatchingStale** | As above. If a leader exists, look for `order_processing_failed` or `background_job_failed` with `job=process_all_open_orders`. |
| **BackgroundJobFailing** | Search the logs for `background_job_failed` with the job's name. Market-data outages show up here first; the jobs retry on their own. |
| **MarketStreamUnhealthy** | Prices still update by polling, only more slowly. Check outbound access to `wss://ws-feed.exchange.coinbase.com`. Set `MARKET_STREAM_ENABLED=false` to stop retrying. |
| **HighServerErrorRate** / **SlowApi** | Break `kestrel_http_requests_total` down by `route` to find the endpoint, then check the logs for its `request_id`. Long backtests and research runs are CPU-bound; see [Scaling](#scaling). |
| **EmailFailing** | `email_send_failed` in the logs has the SMTP error. Check the `SMTP_*` settings. Verification and reset links can be resent from the app. |

## Backups

Everything worth keeping is in PostgreSQL. Redis holds only rebuildable state.

### Take a backup

```bash
mkdir -p backups
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
  > "backups/kestrel-$(date -u +%Y%m%dT%H%MZ).dump"
```

This works while the app is running: `pg_dump` takes a consistent snapshot. To run it nightly, add a crontab entry that `cd`s to the repository first and keeps two weeks of dumps:

```cron
30 3 * * * cd /srv/kestrel && docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > backups/kestrel-$(date -u +\%Y\%m\%d).dump && find backups -name '*.dump' -mtime +14 -delete
```

Copy dumps off the server, because a backup on the same disk doesn't survive losing that disk.

Keep `.env` with the backups, stored separately and securely. Session and email-link tokens are stored as hashes keyed by `SECRET_KEY`. A database restored under a different key still works, but everyone has to sign in again and outstanding verification and reset links stop working.

### Restore

Restoring replaces the current database.

```bash
docker compose stop backend worker frontend
docker compose exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" --force "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' < backups/kestrel-YYYYMMDDTHHMMZ.dump
docker compose up -d
```

The backend applies any newer migrations as it starts, so a dump from an older release restores into a newer one. Restoring a newer dump into an older release is not supported.

Test a restore now and then. CI runs this exact backup-and-restore sequence on every push.

## Upgrades

```bash
# 1. Back up (see above).
git pull
docker compose up -d --build        # with the same --profile flags you normally use
docker compose logs backend --tail 50 | grep -i -E "migration|startup_complete|error"
```

Migrations run automatically when the backend container starts (`alembic upgrade head` in [`docker-entrypoint.sh`](../backend/docker-entrypoint.sh)). If one fails, the backend won't start and the error is in its log. To roll back, check out the previous release and restore the backup you took in step 1. Every migration also has a tested downgrade, `docker compose run --rm backend alembic downgrade -1`, but restoring the backup is the safer path.

The worker waits until the backend is healthy, so migrations have finished before it starts.

## Secrets

| Secret | How to rotate | Effect |
|---|---|---|
| `SECRET_KEY` | Put a new value (`openssl rand -hex 32`) in `.env`, then `docker compose up -d` | Everyone is signed out. Pending verification and reset links stop working. |
| `PROXY_SHARED_SECRET` | Change it in `.env` and recreate Caddy, frontend and backend together with `docker compose up -d` | None if all three restart together. Until then, rate limits fall back to the proxy's IP. |
| `POSTGRES_PASSWORD` | `docker compose exec postgres psql -U trading -c "ALTER USER trading PASSWORD '…'"`, then update `.env` and `docker compose up -d` | Brief reconnect. The variable only seeds a new volume, so changing `.env` alone does nothing. |
| `SMTP_PASSWORD`, `OPENAI_API_KEY`, `METRICS_TOKEN` | Update `.env` (and `deploy/metrics-token`), then `docker compose up -d` | None |

Never commit `.env`. Git ignores it.

## Scaling

- **Background jobs off the request path:** `docker compose --profile worker up -d` and set `RUN_BACKGROUND_JOBS=false` for the backend. Leaving it `true` is also safe, because a Redis lease elects a single runner. If the leader dies, another instance takes over within about 30 seconds.
- **More API instances** need `REDIS_URL`, which every Compose service already has. Rate limits and the job lease are then shared. Without Redis each process would run its own jobs.
- **Live prices** are per instance: each API instance holds its own Coinbase feed for its own browsers.
- **Heavy research:** backtests, sweeps and walk-forward tests run in the API process and are rate-limited by `COMPUTE_RATE_LIMIT_PER_MINUTE`. Watch `kestrel_http_request_duration_seconds` for `/api/v1/research/*` and `/api/v1/backtests`.

## Routine tasks

```bash
# Promote or demote an admin (e.g. before email delivery is configured)
docker compose exec backend python -m app.cli promote-admin you@example.com

# Follow the structured logs (JSON in Compose); every request has a request_id, also in the X-Request-ID header
docker compose logs -f backend worker

# Free disk space taken by old images after upgrades
docker image prune -f
```

In demo mode, sandboxes are purged `DEMO_TTL_HOURS` after creation, and at most `DEMO_MAX_ACCOUNTS` exist at once. Visitors who hit the cap see a "try again later" message.
