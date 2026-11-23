"""One safe entry point for Claude API calls. Every failure returns None.

Callers always have a rule-based fallback (the text TAP shows today), so the
app keeps working when the feature is switched off, the key is missing, the
credit is used up, the card fails, the budget for the month is reached, or the
API is slow or down. Nothing here raises into a Streamlit screen.

Order of checks for one call:
1. stored result for the same input -> reuse it, no call
2. switched off / no key / SDK missing -> None
3. input over the feature's ceiling -> None
4. paused after a billing or key error -> None
5. reserve the worst-case cost in the ledger; over budget -> None
6. call; settle the actual cost (or keep the reservation when unknown)
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from typing import Any, Callable

from tap.ai_budget import (FEATURES, MONTHLY_APP_LIMIT_USD, estimate_input_tokens, max_call_micros,
                           to_micros, usage_cost_micros)

LOGGER = logging.getLogger(__name__)

# A billing or key problem will not fix itself in minutes; stop trying for a while.
BILLING_PAUSE_SECONDS = 6 * 3600
RATE_LIMIT_PAUSE_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 45.0


@dataclass(frozen=True)
class AIResult:
    text: str
    cached: bool
    cost_micros: int


def ai_enabled() -> bool:
    """Off unless TAP_AI_ENABLED=1 and an API key are both set on the service."""
    return os.environ.get("TAP_AI_ENABLED", "").strip() == "1" and bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def ai_ready(ledger: Any) -> bool:
    """Whether a call could start now: switched on, SDK installed and not paused. Budget is checked separately."""
    try:
        import importlib.util

        return ai_enabled() and importlib.util.find_spec("anthropic") is not None and ledger.ai_paused_until() <= ledger.now()
    except Exception:
        return False


def _default_client():
    try:
        import anthropic
    except ImportError:
        LOGGER.warning("anthropic package is not installed; AI features stay off")
        return None
    # No SDK retries: a slow answer is worse than the fallback text.
    return anthropic.Anthropic(timeout=REQUEST_TIMEOUT_SECONDS, max_retries=0)


def _error_kind(exc: Exception) -> str:
    """billing | auth | rate | rejected (not billed) | unknown (may have been billed)."""
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    error = body.get("error", {}) if isinstance(body, dict) else {}
    error_type = str(error.get("type", "")) if isinstance(error, dict) else ""
    message = f"{error.get('message', '') if isinstance(error, dict) else ''} {exc}".lower()
    if status == 402 or error_type == "billing_error" or "credit balance" in message or "billing" in message:
        return "billing"
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate"
    if isinstance(status, int):
        return "rejected"
    return "unknown"


def generate(ledger: Any, feature_key: str, *, system: str, prompt: str, project_id: str | None = None,
             cache_key: str | None = None, client_factory: Callable[[], Any] | None = None,
             output_schema: dict | None = None) -> AIResult | None:
    feature = FEATURES.get(feature_key)
    # Batch features are priced at the batch discount; a live call here would cost double.
    if feature is None or feature.monthly_usd <= 0 or feature.batch:
        return None
    try:
        if cache_key:
            stored = ledger.ai_cached(feature.key, cache_key)
            if stored is not None:
                return AIResult(stored, True, 0)
        if not ai_enabled():
            return None
        if estimate_input_tokens(system, prompt) > feature.max_input_tokens:
            LOGGER.info("AI %s skipped: input over ceiling", feature.key)
            return None
        if ledger.ai_paused_until() > ledger.now():
            return None
        client = (client_factory or _default_client)()
        if client is None:
            return None
        reservation = ledger.ai_reserve(feature.key, max_call_micros(feature), to_micros(feature.monthly_usd),
                                        to_micros(MONTHLY_APP_LIMIT_USD), project_id)
    except Exception:  # ledger or DB trouble must not reach the screen
        LOGGER.exception("AI %s skipped before the call", feature.key)
        return None
    if reservation is None:
        LOGGER.info("AI %s skipped: monthly budget reached", feature.key)
        return None

    try:
        response = client.messages.create(
            model=feature.model,
            max_tokens=feature.max_output_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": feature.effort,
                           **({"format": {"type": "json_schema", "schema": output_schema}} if output_schema else {})},
        )
    except Exception as exc:
        kind = _error_kind(exc)
        LOGGER.warning("AI %s failed (%s): %s", feature.key, kind, type(exc).__name__)
        try:
            if kind in ("billing", "auth"):
                ledger.ai_pause(ledger.now() + BILLING_PAUSE_SECONDS, kind)
            elif kind == "rate":
                ledger.ai_pause(ledger.now() + RATE_LIMIT_PAUSE_SECONDS, kind)
            if kind == "unknown":
                # Timeout or dropped connection: the request may have run and been billed.
                ledger.ai_settle(reservation, max_call_micros(feature), outcome="unknown")
            else:
                ledger.ai_settle(reservation, 0, outcome=kind)
        except Exception:
            LOGGER.exception("AI %s ledger update failed after error", feature.key)
        return None

    try:
        cost, input_tokens, output_tokens = usage_cost_micros(feature.model, response.usage, batch=feature.batch)
        stop = getattr(response, "stop_reason", None)
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text").strip()
        ok = stop == "end_turn" and bool(text)
        ledger.ai_settle(reservation, cost, input_tokens=input_tokens, output_tokens=output_tokens,
                         outcome="ok" if ok else str(stop or "empty"))
        if not ok:
            return None
        if cache_key:
            ledger.ai_store_result(feature.key, cache_key, text)
        return AIResult(text, False, cost)
    except Exception:
        LOGGER.exception("AI %s response handling failed", feature.key)
        return None
