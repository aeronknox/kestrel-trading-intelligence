"""OpenAI integration (optional).

The LLM is used only to *phrase* facts the platform has already computed. It is
instructed never to introduce numbers that are not present in the supplied data.
When no API key is configured, or the call fails, callers fall back to
deterministic, data-driven text.
"""

import json
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

GROUNDING_RULES = (
    "Rules: Use ONLY the numbers and facts in the provided JSON data. Never invent or estimate "
    "prices, dates, statistics, or performance figures that are not present in the data. "
    "If something is not in the data, say it is unavailable. Describe model outputs as "
    "estimates, not predictions or guarantees. Do not give personalized financial advice. "
    "This platform is for research and simulated (paper) trading only."
)

_client: Any = None


def get_client() -> Any | None:
    global _client
    settings = get_settings()
    if not settings.ai_enabled:
        return None
    if _client is None:
        from openai import AsyncOpenAI

        _client = AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url, timeout=30.0)
    return _client


async def narrate_analysis(facts: dict) -> tuple[str, str]:
    """Return (narrative, source) where source is 'openai:<model>' or 'rule_based'."""
    client = get_client()
    if client is None:
        return rule_based_narrative(facts), "rule_based"
    model = get_settings().openai_model
    try:
        resp = await client.chat.completions.create(
            model=model,
            temperature=0.2,
            max_tokens=450,
            messages=[
                {
                    "role": "system",
                    "content": "You are a market analyst writing a concise technical-analysis brief "
                    "(3 short paragraphs: market structure, signal rationale, key risks). " + GROUNDING_RULES,
                },
                {"role": "user", "content": "Analysis data:\n" + json.dumps(facts, default=str)},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        if not text:
            raise ValueError("empty completion")
        return text, f"openai:{model}"
    except Exception as exc:  # noqa: BLE001 - LLM is optional; degrade gracefully
        logger.warning("llm_narrative_failed", error=str(exc))
        return rule_based_narrative(facts), "rule_based"


def _fmt_price(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v:,.2f}" if v >= 1 else f"{v:,.6g}"


def rule_based_narrative(facts: dict) -> str:
    t = facts["trend"]
    sig = facts["signal"]
    ind = facts["indicators"]
    sym, tf = facts["symbol"], facts["timeframe"]
    rsi_text = f"{ind['rsi_14']:.1f}" if ind.get("rsi_14") is not None else "n/a"
    lines = [
        f"{sym} on the {tf} timeframe is in a {t['direction']} over the last {t['lookback_bars']} closed bars "
        f"(regression move {t['regression_move_pct']:+.1f}%, R² {t['r_squared']:.2f}). "
        f"Last close {_fmt_price(ind.get('close'))}; RSI(14) {rsi_text}."
    ]
    drivers = sorted(sig["components"], key=lambda c: -abs(c["score"] * c["weight"]))[:3]
    if drivers:
        lines.append(
            f"The composite score is {sig['score']:+.2f} → {sig['action'].upper()} "
            f"(confidence {sig['confidence']:.0f}/100). Main drivers: "
            + " ".join(f"{d['name']}: {d['reason']}" for d in drivers)
        )
    key_risks = [r["title"] for r in facts.get("risks", []) if r["level"] in ("high", "medium")]
    if key_risks:
        lines.append("Key risks: " + ", ".join(key_risks) + ".")
    lines.append("This is an automated, rule-based summary of computed indicators — an estimate, not a forecast.")
    return "\n\n".join(lines)
