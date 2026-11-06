# Kestrel Intelligence — AI Trading Research Platform

An AI-assisted market research, backtesting and **paper-trading** platform for crypto markets, with an architecture ready for stocks and forex.

> **Simulation & research only.** There is no real-money trading, no brokerage connectivity and no financial transactions anywhere in this codebase. AI outputs are estimates derived from historical data, not predictions or financial advice.

| Area | What you get |
|---|---|
| Dashboard | Virtual portfolio value, 24h P&L, equity curve, live market table, watchlist, AI insight, recent signals and orders, market sentiment |
| Markets | Live prices over WebSocket, catalog search to track new assets, candlestick charts (1m–1d), SMA 20/50/200, Bollinger Bands, volume, RSI, MACD |
| AI Analysis | Trend regression, support/resistance, pattern detection, a walk-forward ML model, an explainable composite signal with confidence, and a risk breakdown |
| Strategy Builder | Visual rule builder (13 indicators, 6 operators, ALL/ANY logic), risk exits, templates, immutable versioning |
| Backtesting | Next-bar execution, fees, slippage, gap-aware stops; return, max drawdown, Sharpe/Sortino, a buy-and-hold benchmark with the same costs (overlaid on the equity curve, with excess return and beta), win rate, profit factor, CAGR, exposure; side-by-side comparison |
| Paper Trading | $100k virtual balance, market and limit orders (open limit orders reserve cash or quantity; exposure limits are re-checked at fill time), positions, realized/unrealized P&L, risk limits, order and trade history, reset |
| Portfolio | Equity and drawdown history, allocation, trade statistics |
| Assistant | Chat grounded in platform data through tool calls; reports missing data as unavailable |
| Admin | Role management, account disabling, audit log viewer |

---

## Architecture

```
┌────────────────────────┐   /api/v1/* (same-origin proxy,     ┌───────────────────────────┐
│ Next.js 16 (React 19)  │──── httpOnly session cookie) ──────▶│ FastAPI (async)           │
│ Tailwind 4 · shadcn/ui │                                     │  ├─ market_data ─▶ Coinbase│
│ lightweight-charts     │◀──── ws /api/v1/ws/market ──────────│  ├─ indicators / ai        │
│ Recharts · React Query │        (live tickers)               │  ├─ strategies/backtesting │
└────────────────────────┘                                     │  ├─ paper_trading          │
                                                               │  └─ background jobs        │
                                                               └──────┬──────────────┬─────┘
                                                                PostgreSQL         Redis
                                                               (SQLAlchemy +   (cache, rate
                                                                 Alembic)        limiting)
```

### Repository layout

```
backend/
  app/
    api/            # FastAPI routers + dependencies (auth, RBAC, rate limits)
    core/           # config, logging, security, cache, exceptions
    database/       # engine/session, declarative base, portable column types
    models/         # SQLAlchemy models (21 tables)
    schemas/        # Pydantic request/response models
    market_data/    # provider interface, Coinbase + sample providers, caching service
    indicators/     # causal technical indicators
    ai/             # patterns, ML model, signal scoring, LLM narration, assistant
    strategies/     # rule DSL + evaluator + templates
    backtesting/    # engine + metrics
    paper_trading/  # order/fill/position ledger
    services/       # auth, audit, sentiment, background jobs
  alembic/          # migrations
  tests/            # pytest suite
frontend/
  src/
    app/            # routes (auth group, authenticated app group, API proxy)
    components/     # ui primitives (shadcn-style), layout, shared finance widgets
    features/       # dashboard, markets, charts, ai-analysis, strategies, backtesting,
                    # paper-trading, portfolio, assistant, settings, admin
    hooks/          # auth, theme, market WebSocket stream
    services/       # typed API client
    lib/ types/ styles/
docker-compose.yml
```

### Design decisions

- **Real data only.** Market data comes from the [Coinbase Exchange public API](https://docs.cdp.coinbase.com/exchange/) (no key needed). Sentiment combines breadth and RSI computed from that data with the [alternative.me Crypto Fear & Greed Index](https://alternative.me/crypto/fear-and-greed-index/). Every data widget shows its source. A synthetic `sample` provider exists for offline development. It is flagged `is_sample` end to end, shows a persistent warning banner, and its data is never persisted.
- **The LLM never generates numbers.** Indicators, patterns, ML estimates, signals and risks are all computed in Python. When `OPENAI_API_KEY` is set, the model only *phrases* those computed facts, under explicit grounding rules. The assistant reaches data only through tools that read real application state. Without a key, both features fall back to deterministic text and say so in the UI.
- **No look-ahead bias.** Indicators are causal (tested). Rules are evaluated at bar *t*'s close and filled at bar *t+1*'s open. Stops are gap-aware and resolved conservatively (stop before target in the same bar). Analysis uses closed candles only. The ML model uses a forward-chaining `TimeSeriesSplit` with a gap equal to its label horizon, and is compared against a naive baseline. It gets zero weight in the signal when it shows no out-of-sample edge, which is common.
- **Explainable signals.** Each signal is a weighted average of components scored −1…+1, each with a reason: trend, MACD, RSI, Bollinger, patterns and ML. Confidence blends score magnitude with agreement between components and is capped at 85/100.
- **Reproducible strategies.** Editing a strategy creates a new immutable configuration version. Each backtest references the exact version it ran.
- **Paper-trading accounting.** Buy fees are capitalized into cost basis, so `equity − starting balance = realized + unrealized P&L` exactly (tested).
- **Sessions, not JWTs in JS.** Login issues an opaque random token in an `httpOnly`, `SameSite=Lax` cookie. Only an HMAC of the token is stored, so sessions are revocable on logout or password change. The Next.js server proxies `/api/v1/*`, which keeps the cookie first-party.
- **PyTorch is intentionally not included.** The ML component is a regularized logistic regression (scikit-learn), chosen for explainability (per-feature log-odds contributions) and because a deep model on a few hundred bars would mostly overfit. `ai/ml_model.py` keeps a small interface (`predict_direction(df) → dict`), so a PyTorch model can be added without touching callers.

### Security

- Argon2id password hashing with rehash-on-login and timing-equalized failed logins (no user enumeration)
- Server-side sessions with revocation, RBAC (`user` / `admin`) and an audit log for auth, admin, orders and strategy events
- Per-IP rate limiting, backed by Redis or an in-memory fallback, with stricter auth and compute buckets
- Pydantic validation on every input; strategy DSL parameters are range-checked
- Centralized error handling returns structured JSON errors with request IDs and never leaks stack traces
- Security headers on both tiers (CSP, `X-Frame-Options`, `nosniff`, Referrer-Policy, HSTS when `COOKIE_SECURE=true`) and a WebSocket origin check
- CORS allow-list, secrets read only from the environment, and `.env` git-ignored

---

## Running it

### Option A — Docker Compose (recommended)

Requirements: Docker with Compose v2.24+.

```bash
cp .env.example .env
# Set SECRET_KEY:  python -c "import secrets; print(secrets.token_urlsafe(48))"
# Optional: OPENAI_API_KEY, ADMIN_EMAILS=you@example.com
docker compose up --build
```

- App: <http://localhost:3000> (register an account; emails listed in `ADMIN_EMAILS` become admins)
- API docs: <http://localhost:8000/docs> · readiness: <http://localhost:8000/health/ready>

Migrations run automatically when the backend container starts.

### Option B — Local development (no Docker)

Requirements: Python 3.13+ (tested on 3.14) and Node.js 22+ (tested on 24). PostgreSQL and Redis are optional: the backend falls back to SQLite and an in-process cache.

**Backend**

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example .env
# For SQLite, edit .env:  DATABASE_URL=sqlite+aiosqlite:///./data/dev.db   REDIS_URL=
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

**Frontend**

```bash
cd frontend
npm install
cp .env.example .env.local      # BACKEND_INTERNAL_URL / NEXT_PUBLIC_WS_URL
npm run dev                     # http://localhost:3000
```

### Admin accounts

```bash
cd backend && python -m app.cli promote-admin you@example.com    # or demote-admin
# Docker: docker compose exec backend python -m app.cli promote-admin you@example.com
```

### Tests

```bash
cd backend  && pytest                  # 83 tests: indicators (incl. Wilder reference values),
                                       # backtester, ML leakage, signals, auth/RBAC, rate limiting,
                                       # paper-trading accounting, market data + Coinbase parsing,
                                       # OpenAI tool loop (fake client), WebSocket, API flows
cd frontend && npm test                # rule-builder logic + formatters (Vitest)
cd frontend && npm run typecheck && npm run build
cd frontend && npx playwright install chromium && npm run e2e
                                       # 23 browser flows against a running stack (:3000 + :8000)
```

Backend tests run against SQLite with the sample provider and need no network access. Set `TEST_DATABASE_URL=postgresql+psycopg://…` to run them against PostgreSQL.

### Continuous integration

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every push to `main` and on pull requests:

- **Backend:** Alembic upgrade/check/downgrade/upgrade on PostgreSQL 17, then the test suite on SQLite and again on PostgreSQL.
- **Frontend:** typecheck, unit tests, production build.
- **Docker:** `docker compose up --build --wait`, health checks, then the 23 browser flows against the containerized stack. See [docs/AUDIT.md](docs/AUDIT.md) for the latest technical audit.

---

## Configuration

All settings are environment variables; see [.env.example](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | dev value (rejected in production) | HMAC key for session-token hashing |
| `DATABASE_URL` | SQLite file | `postgresql+psycopg://…` or `sqlite+aiosqlite:///…` |
| `REDIS_URL` | empty | Cache and rate limits; empty uses in-process memory |
| `MARKET_DATA_PROVIDER` | `coinbase` | `coinbase` (real) or `sample` (synthetic, labelled) |
| `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_BASE_URL` | empty / `gpt-4.1-mini` | Optional LLM narration and assistant |
| `PAPER_STARTING_BALANCE`, `PAPER_FEE_BPS`, `PAPER_SLIPPAGE_BPS` | 100000 / 10 / 5 | Simulation parameters |
| `RATE_LIMIT_PER_MINUTE`, `AUTH_RATE_LIMIT_PER_MINUTE`, `COMPUTE_RATE_LIMIT_PER_MINUTE` | 240 / 15 / 30 | Per-IP limits |
| `CORS_ORIGINS` | `http://localhost:3000` | Also used for the WebSocket origin check |
| `ADMIN_EMAILS` | empty | Comma-separated emails granted the admin role at registration (unverified, so use only before exposing the app; prefer the CLI below) |
| `TRUST_PROXY_HEADERS` (frontend), `PROXY_SHARED_SECRET` (both) | `false` / empty | Set both only when a reverse proxy in front of Next.js sets `X-Forwarded-For`; the API then trusts the client IP for rate limiting and audit |
| `TRUSTED_PROXIES` | `127.0.0.1/32,::1/128` | Peers whose `X-Forwarded-For` is trusted without the secret |
| `LOGIN_MAX_FAILURES`, `LOGIN_LOCKOUT_MINUTES` | 10 / 15 | Per-account lockout after repeated failed sign-ins |
| `COOKIE_SECURE` | `false` | Set `true` behind HTTPS (also enables HSTS) |
| `LOG_JSON` | `false` | Structured JSON logs (on by default in Compose) |
| `BACKEND_INTERNAL_URL` | `http://localhost:8000` | Where the Next.js proxy sends API calls (read at runtime) |
| `NEXT_PUBLIC_WS_URL` | `ws://localhost:8000/api/v1/ws/market` | Browser WebSocket URL (baked in at build time) |

### Adding stocks or forex

1. Implement `MarketDataProvider` (`get_candles`, `get_ticker`, `list_products`) in `backend/app/market_data/providers/`.
2. Register it in `providers/registry.py`.
3. Create `Asset` rows with `asset_class="stock"` or `"forex"` and the provider's symbol mapping.

Indicators, analysis, backtesting and paper trading are asset-class agnostic. Annualization currently assumes 24/7 trading (`backtesting/metrics.py`), so equities would need a trading calendar.

---

## API overview

Interactive docs are at `/docs`. All routes are under `/api/v1`.

| Prefix | Endpoints |
|---|---|
| `/auth` | `register`, `login`, `logout`, `me`, `change-password` |
| `/users/me`, `/admin` | profile, settings; admin users, audit logs |
| `/market` | `overview`, `assets`, `catalog`, `assets/{symbol}/candles`, `assets/{symbol}/ticker`, `sentiment` |
| `/watchlists/default` | get, add, remove |
| `/analysis`, `/signals` | run analysis, history, signals |
| `/strategies` | CRUD, `templates`, `indicators` |
| `/backtests` | run, list, get, `compare`, delete |
| `/paper` | `portfolio`, `orders`, `orders/{id}/cancel`, `trades`, `history`, `analytics`, `portfolio/risk-limits`, `portfolio/reset` |
| `/dashboard` | aggregated dashboard payload |
| `/assistant` | `chat`, `conversations` |
| `/ws/market` | WebSocket ticker stream (`{"action":"subscribe","symbols":[…]}`) |

## Known limitations and next steps

- Background jobs (limit-order matching every 15s, equity snapshots every 5 min) and the WebSocket broadcaster run inside the API process, so run one backend replica or move them to a dedicated worker before scaling out.
- Live prices are polled from the provider every `MARKET_WS_POLL_SECONDS` (default 5s) and fanned out over WebSocket. An upstream exchange WebSocket feed would lower latency.
- Backtests are long-only, unleveraged, single-asset, and limited to 2,000 bars per run (Coinbase candle pagination).
- Paper trading is spot and long-only; short selling is rejected by design.
