"""Strategy alerts: notify when a saved strategy's entry or exit rules fire on live data.

Rules are evaluated exactly as in backtests (same evaluator, closed candles only), so an
alert means "the backtester would have generated this signal at this bar's close".

* Edge-triggered: an alert fires when a rule set *becomes* true (false on the previous bar,
  true on this one). Level conditions like "close > SMA(200)" would otherwise fire on
  every bar for as long as they hold.
* A new or re-enabled alert starts from the newest closed bar; it never fires for history.
* After downtime, at most MAX_CATCH_UP_BARS missed bars are evaluated, so a restart can't
  produce a burst of stale notifications.
* Research notifications only: nothing here places orders, simulated or real.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.metrics import ALERT_EVENTS
from app.database.session import get_sessionmaker
from app.indicators.technical import candles_to_frame
from app.market_data.providers.base import Candle, timeframe_seconds
from app.market_data.service import MAX_CANDLES, MarketDataService
from app.models.alert import AlertEvent, StrategyAlert
from app.models.strategy import Strategy
from app.models.user import User, UserSettings
from app.services import webhooks
from app.services.email import OutgoingEmail, send_email
from app.strategies.definition import StrategyDefinition
from app.strategies.evaluator import evaluate_rules, max_warmup

logger = get_logger(__name__)

MAX_CATCH_UP_BARS = 3
DISCLAIMER = (
    "Simulated research signal. No real-money order is ever placed (forward tests place simulated paper orders only); "
    "this is not financial advice."
)


def _fmt_price(price: float) -> str:
    return f"{price:,.2f}" if price >= 1 else f"{price:.6g}"


async def check_alert(session: AsyncSession, market: MarketDataService, alert: StrategyAlert) -> list[AlertEvent]:
    """Evaluate one alert against the newest closed candles; returns the events it fired."""
    strategy = alert.strategy
    cfg = strategy.current_config
    if cfg is None:
        alert.last_error = "Strategy has no configuration"
        return []
    definition = StrategyDefinition.model_validate({"entry": cfg.entry_rules, "exit": cfg.exit_rules, "risk": cfg.risk})
    warmup = max_warmup([definition.entry, definition.exit])
    series = await market.get_candles(cfg.asset, cfg.timeframe, limit=min(MAX_CANDLES, warmup * 2 + 50))
    closed = series.closed()
    now = datetime.now(UTC)
    alert.last_checked_at = now
    if len(closed) < warmup + 2:
        alert.last_error = f"Not enough closed candles yet ({len(closed)} of {warmup + 2})"
        return []
    newest = closed[-1].ts
    if alert.last_bar_at is None:
        alert.last_bar_at, alert.last_error = newest, None  # start watching from now
        return []

    df = candles_to_frame(closed)
    cache: dict = {}
    signals = {"entry": evaluate_rules(df, definition.entry, cache).to_numpy(),
               "exit": evaluate_rules(df, definition.exit, cache).to_numpy()}  # fmt: skip
    wanted = {"entry": alert.on_entry, "exit": alert.on_exit}
    pending = [i for i, c in enumerate(closed) if c.ts > alert.last_bar_at][-MAX_CATCH_UP_BARS:]
    tf = timedelta(seconds=timeframe_seconds(cfg.timeframe))
    source = series.source + (":sample" if series.is_sample else "")
    events: list[AlertEvent] = []

    def make_event(kind: str, bar: Candle, matched: bool = False) -> AlertEvent:
        rules = definition.entry if kind == "entry" else definition.exit
        joined = f" {rules.logic.upper()} ".join(c.label() for c in rules.conditions)
        what = f"{kind} rules matched ({joined})" if matched else f"forward test {kind}"
        event = AlertEvent(
            user_id=alert.user_id,
            alert_id=alert.id,
            strategy_id=strategy.id,
            strategy_version=cfg.version,
            kind=kind,
            symbol=cfg.asset.symbol,
            timeframe=cfg.timeframe,
            bar_at=bar.ts,
            close_price=bar.close,
            data_source=source,
            message=(
                f"{strategy.name} v{cfg.version}: {what} on the {cfg.timeframe} "
                f"{cfg.asset.symbol} bar that closed {(bar.ts + tf):%Y-%m-%d %H:%M} UTC at {_fmt_price(bar.close)}."
            ),
        )
        session.add(event)
        events.append(event)
        ALERT_EVENTS.labels(kind).inc()
        return event

    for i in pending:
        for kind, sig in signals.items():
            if not (wanted[kind] and i > 0 and sig[i] and not sig[i - 1]):
                continue
            bar = closed[i]
            exists = await session.scalar(
                select(AlertEvent.id).where(AlertEvent.alert_id == alert.id, AlertEvent.kind == kind, AlertEvent.bar_at == bar.ts)
            )
            if exists:
                continue  # already recorded (e.g. by an overlapping check)
            make_event(kind, bar, matched=True)
    alert.last_bar_at, alert.last_error = newest, None
    if alert.auto_trade:
        from app.services.forward_test import act

        await session.flush()
        by_key = {(e.kind, e.bar_at): e for e in events}
        await act(session, market, alert, definition, cfg, closed, pending, signals, by_key, make_event)
    await session.flush()
    if events and alert.notify_email:
        await _email(session, alert, events)
    if events and alert.notify_webhook:
        await _webhook(session, alert, events)
    return events


async def _email(session: AsyncSession, alert: StrategyAlert, events: list[AlertEvent]) -> None:
    user = await session.get(User, alert.user_id)
    if user is None or not user.email_verified:
        return  # only verified addresses receive alert email
    kinds = " and ".join(sorted({e.kind for e in events}))
    body = "\n\n".join(e.message for e in events)
    msg = OutgoingEmail(
        to=user.email,
        subject=f"{kinds.capitalize()} signal: {alert.strategy.name} ({events[0].symbol} {events[0].timeframe})",
        text=f"Hi {user.full_name},\n\n{body}\n\n{DISCLAIMER}\n\nManage alerts on the strategy's page in Kestrel Intelligence.\n",
    )
    if await send_email(msg):
        sent = datetime.now(UTC)
        for e in events:
            e.emailed_at = sent


async def _webhook(session: AsyncSession, alert: StrategyAlert, events: list[AlertEvent]) -> None:
    """Best-effort: a failing endpoint is recorded on the user's settings, never fails the check."""
    settings = await session.scalar(select(UserSettings).where(UserSettings.user_id == alert.user_id))
    if settings is None or not settings.webhook_url or not settings.webhook_secret:
        return
    kinds = " and ".join(sorted({e.kind for e in events}))
    title = f"{kinds.capitalize()} signal: {alert.strategy.name} ({events[0].symbol} {events[0].timeframe})"
    fields = ("id", "kind", "symbol", "timeframe", "close_price", "message", "data_source", "order_id")
    details = [{**{f: getattr(e, f) for f in fields}, "bar_at": e.bar_at.isoformat()} for e in events]
    event = {"type": "strategy_alert", "strategy_id": alert.strategy_id, "strategy_name": alert.strategy.name,
             "events": details, "disclaimer": DISCLAIMER}  # fmt: skip
    fmt = webhooks.webhook_format(settings.webhook_url)
    payload = webhooks.build_payload(fmt, title, [e.message for e in events] + [DISCLAIMER], event)
    try:
        settings.webhook_last_status = await webhooks.deliver(settings.webhook_url, settings.webhook_secret, payload)
    except webhooks.WebhookError as exc:
        settings.webhook_last_status = f"Failed: {exc}"[:255]
        logger.warning("alert_webhook_failed", user_id=alert.user_id, error=str(exc))
    settings.webhook_last_at = datetime.now(UTC)


async def evaluate_alerts() -> int:
    """Background job: check every enabled alert. Returns the number of events fired."""
    fired = 0
    async with get_sessionmaker()() as session:
        market = MarketDataService(session)
        alerts = (
            await session.scalars(
                select(StrategyAlert)
                .join(Strategy, Strategy.id == StrategyAlert.strategy_id)
                .where(StrategyAlert.enabled.is_(True), Strategy.is_archived.is_(False))
                .order_by(StrategyAlert.id)
            )
        ).all()
        for alert in alerts:
            try:
                fired += len(await check_alert(session, market, alert))
                await session.commit()
            except Exception as exc:  # noqa: BLE001 - one failing alert must not stop the others
                alert_id = alert.id
                await session.rollback()
                logger.warning("alert_check_failed", alert_id=alert_id, error=str(exc))
                try:
                    await session.refresh(alert)  # rollback expired it
                    alert.last_error = f"Check failed: {type(exc).__name__}"[:255]
                    alert.last_checked_at = datetime.now(UTC)
                    await session.commit()
                except Exception:  # noqa: BLE001
                    await session.rollback()
    return fired
