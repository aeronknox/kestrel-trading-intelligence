# Technical Audit — Kestrel Intelligence

**Date:** 2026-11-05 · **Scope:** the whole repository as of commit `fb4d3f5`, plus the fixes made during this audit.

## Method

- Read the source of every module and checked suspected defects with targeted experiments, not assumptions:
  - RSI against the published StockCharts Wilder example
  - `X-Forwarded-For` spoofing against the running API
  - FastAPI yield-dependency commit semantics, checked in isolation
- Drove 23 real user flows in headless Chromium against the running stack. That suite is now committed as `npm run e2e`.
- Ran the full test suites after each fix.
- Verified that the Docker dependencies resolve for Linux: every backend wheel exists for CPython 3.14 / manylinux, and the npm lockfile contains the `linux-*-musl` native binaries.

### What could not be verified

| Item | Why | Mitigation |
|---|---|---|
| PostgreSQL behaviour (migration on PG, `FOR UPDATE`, JSONB, savepoints) | No PostgreSQL or Docker on the audit machine; running downloaded PG binaries was not permitted | Code review of PG-specific paths; SQLite exercises the same SQLAlchemy code. **Run `docker compose up` once before relying on it.** |
| `docker compose up` end to end | Docker not installed | Dependency resolution verified for Linux (see Method) |
| Live OpenAI responses | No API key | Integration exercised with a scripted fake client (prompts, tool loop, fallbacks) |

## Module classification

The status reflects the state **after** this audit's fixes. "Found" lists what was wrong before.

| # | Module | Status | Evidence | Found during audit |
|---|---|---|---|---|
| 1 | Frontend UI & interactions | **Fully implemented and tested** | 23 e2e flows pass with 0 console errors; 8 unit tests; typecheck and build clean | Expired session showed error cards instead of redirecting to login; form labels not associated with inputs (accessibility); `0` in optional risk fields caused a 422 |
| 2 | Backend REST API | **Fully implemented and tested** | 75 pytest tests | A failed DB commit still returned **200** (silent write loss); unique-constraint races returned 500 |
| 3 | Database models & migrations | **Fully implemented; tested on SQLite only** | `alembic upgrade/downgrade/check` clean on SQLite | Candle upsert could poison the PostgreSQL transaction (no savepoint) |
| 4 | Authentication & authorization | **Fully implemented and tested** | Session lifecycle, revocation, RBAC, lockout tests | No per-account brute-force protection; wrong current password returned 401, which looked like a logout; `ADMIN_EMAILS` grants admin to unverified emails |
| 5 | Crypto market data | **Fully implemented and tested** (real Coinbase data) | Live calls verified; parsing and pagination tested with a mocked transport; persistence and stale fallback tested | Provider routing ignored `Asset.provider`, so the documented stocks/forex extension didn't work; candle metadata reported the global provider |
| 6 | AI model & OpenAI | ML: **Fully implemented and tested**. OpenAI: **Implemented, tested with a fake client** | Leakage tests; tool-loop, retry and fallback tests | Deprecated `max_tokens` and fixed `temperature` would make newer models fail every call (silent fallback); the assistant's analysis tool made a nested paid LLM call |
| 7 | Technical indicators | **Fully implemented and tested** (previously **broken**) | Matches the Wilder reference (±0.1) and an independent oracle (1e-10) | EMA/RSI/ATR were seeded with the first value instead of the SMA: RSI off by up to **20 points** for about the first 60 bars, which affected early-window backtest signals |
| 8 | AI signal generation | **Fully implemented and tested** | Threshold and confidence-cap tests; end-to-end analysis | — |
| 9 | Strategy builder | **Fully implemented and tested** | API CRUD/versioning tests; UI create/edit/save flows | `0` stop-loss rejected by the server (now treated as "off") |
| 10 | Backtesting | **Fully implemented and tested** | Next-bar fills, gap stops, stop-before-target, cost and metric identities, no-look-ahead test | Indicator seeding (row 7) |
| 11 | Paper trading & accounting | **Fully implemented and tested** (previously **broken under concurrency**) | Accounting identity, limits, limit-order matching tests | `GET /paper/portfolio` and `GET /dashboard` matched orders **without the row lock**, so a concurrent request could double-fill an order or lose a cash update |
| 12 | WebSocket real-time updates | **Fully implemented and tested** (polling upstream) | Subscription, origin rejection, malformed input tests | Previously had no tests |
| 13 | Security & error handling | **Fully implemented and tested** | Rate-limit, spoofing, lockout, header and error-shape tests | **Rate limits bypassable** by rotating `X-Forwarded-For` (demonstrated: 20/20 attempts unthrottled); Dockerfile had `--forwarded-allow-ips *` |
| 14 | Automated tests | **Fully implemented** | Backend 48 → 75, frontend 7 → 8 unit tests plus 23 e2e flows | No coverage existed for WebSocket, provider parsing, OpenAI, rate limiting or persistence |
| 15 | Docker & deployment | **Implemented, not executed** | Linux dependency resolution verified | See "What could not be verified" |

**Mock or sample data:** only the opt-in `MARKET_DATA_PROVIDER=sample` development provider. It is labelled `is_sample` end to end, shows a banner, and is never persisted. Real data is the default.

**UI-only features:** none found. Every button and form exercised in e2e calls a working API.

**Not implemented (out of scope so far):** email verification, password reset, explicit CSRF tokens (the app relies on `SameSite=Lax` cookies plus JSON-only APIs), multiple portfolios per user, short selling.

## Prioritized findings and resolution

| Priority | Finding | Resolution | Tests |
|---|---|---|---|
| P0 | Paper-order matching ran without the portfolio row lock (double fills, lost cash updates) | All mutating paths lock the portfolio; the dashboard commits early to release the lock | Existing paper suite plus e2e |
| P0 | Rate-limit bypass via a spoofed `X-Forwarded-For` | XFF trusted only from `TRUSTED_PROXIES` or a proxy presenting `PROXY_SHARED_SECRET`; Next.js forwards XFF only when `TRUST_PROXY_HEADERS=true`; uvicorn uses `--no-proxy-headers` | `test_security.py` |
| P0 | Failed commit returned success (data silently not saved) | `Depends(get_db, scope="function")` commits before the response is sent | `test_failed_commit_is_reported_not_silently_ok` |
| P0 | Candle upsert failure would abort the whole PostgreSQL transaction | Upsert wrapped in a SAVEPOINT (`begin_nested`) | `test_market_data.py` |
| P1 | No per-account brute-force protection | Lockout after `LOGIN_MAX_FAILURES` in `LOGIN_LOCKOUT_MINUTES`; reset on success | Lockout tests |
| P1 | Indicator seeding inaccuracy (RSI ±20 early) | SMA-seeded EMA and Wilder RMA (RSI, ATR, MACD signal) | Reference and oracle tests |
| P1 | OpenAI parameters incompatible with newer models; zero coverage | `max_completion_tokens`, temperature retry, nested-call removal | `test_llm.py` (6 tests) |
| P1 | Expired session did not redirect to login | Global React Query 401 handler; change-password uses 422 | e2e "expired session" |
| P2 | Form labels not linked to inputs (accessibility) | `Field` auto-assigns ids | e2e uses `getByLabel` |
| P2 | Stocks/forex provider routing not functional; wrong provenance on candles | `MarketDataService.provider_for(asset)`; per-series metadata | `test_non_crypto_assets_route_to_their_own_provider` |
| P2 | Unique-constraint races returned 500 | `IntegrityError` → 409 | `test_integrity_errors_map_to_409` |
| P2 | `0` in optional risk fields → 422 | `normalizeRisk` treats ≤0 as off | Vitest plus e2e |
| P2 | `ADMIN_EMAILS` trusts unverified emails | `python -m app.cli promote-admin`; *since 2026-11-06* the role is granted only after email verification | `test_cli_promotes_admin`, `test_role_based_access` |

## Remaining issues (not fixed, by priority)

1. **PostgreSQL and Docker unverified locally.** *Follow-up (2026-11-06):* the CI workflow now runs migrations and the full test suite on PostgreSQL 17 and brings up the Docker Compose stack for the browser flows. It is verified once the first GitHub Actions run is green.
2. **Single-replica constraint.** Background jobs and the WebSocket broadcaster run in-process, so a second replica would double-run jobs. Move them to a worker with a Redis lock before scaling out.
3. ~~**Open limit buys don't reserve cash.**~~ *Fixed 2026-11-06:* open limit buys reserve their worst-case cost and open limit sells reserve quantity; the API exposes `reserved_cash` and `available_cash`.
4. ~~**Risk limits are only partly re-checked at fill time.**~~ *Fixed 2026-11-06:* position-size, open-position and daily-loss limits are re-checked before a resting buy fills; a breach rejects the order with an "At fill time" reason.
5. ~~**No email verification or password reset.**~~ *Fixed 2026-11-06:* single-use, expiring emailed tokens (stored as keyed hashes) for verification and password reset; reset revokes all sessions; the forgot-password response does not reveal whether an account exists; per-address cooldown against inbox flooding; console or SMTP delivery.
6. **Upstream prices are polled** (every 5s by default) rather than streamed from an exchange WebSocket.
7. **Backtests** use 24/7 annualization (equities would need a trading calendar). *Update 2026-11-07:* short strategies and multi-asset tests are supported. *Update 2026-11-06:* the 2,000-bar cap is now 20,000 bars, backed by stored, backfilled history.
8. *Addressed 2026-11-06 by `docker-compose.prod.yml` (Caddy, automatic HTTPS), which gives each client its own rate limit; still applies to the plain development Compose file.* **The rate-limit bucket is shared without a reverse proxy.** When the browser reaches Next.js directly (default Compose), the API sees every user as the Next.js container, so the per-IP limits are shared. Per-account lockout still applies. Put a reverse proxy in front and set `TRUST_PROXY_HEADERS`/`PROXY_SHARED_SECRET` for per-client limits.
9. ~~**First portfolio creation can race.**~~ *Fixed 2026-11-06:* a partial unique index (migration `0002`) allows one active portfolio per user, and the losing request reuses the winner's portfolio.

## Test results at end of audit

```
backend   pytest              75 passed
frontend  vitest               8 passed
frontend  tsc --noEmit         clean
frontend  next build           20 routes, success
e2e       npm run e2e         23/23 flows PASS, 0 browser errors
```
