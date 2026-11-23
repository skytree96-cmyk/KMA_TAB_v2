"""Claude API monthly budget: fixed per-call ceilings and per-feature allocations.

Pure functions and constants only. The budget is enforced before every call by
the ledger in AccountStore (reserve the worst case, settle the actual cost), so
the bill cannot exceed the plan even when every call hits its ceiling.

Plan (2026-11-23): total bill <= USD 100 including 10% VAT, so features may use
at most USD 90. Of that, the allocations below are spent by the running app;
USD 15 goes to a separate development key and the rest stays as reserve.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

# USD per million tokens (input, output). Anthropic list prices, 2026-11.
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
BATCH_DISCOUNT = 0.5

# Hard ceiling for everything the running app may spend in one month (USD).
MONTHLY_APP_LIMIT_USD = 50.0


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    model: str
    max_input_tokens: int
    max_output_tokens: int
    monthly_usd: float
    batch: bool = False
    effort: str = "medium"


FEATURES: dict[str, Feature] = {
    feature.key: feature
    for feature in (
        Feature("report_commentary", "조직 리포트 해설", "claude-sonnet-5-5", 20_000, 4_000, 40.0),
        Feature("course_tagging", "과정 역량 태깅", "claude-sonnet-5-5", 7_000, 4_000, 3.3, batch=True),
        Feature("question_review", "문항 검수", "claude-sonnet-5-5", 13_000, 2_000, 4.6),
        # Participants' own writing leaves the country if sent; kept at zero until
        # the consent and privacy policy decide on overseas transfer.
        Feature("open_answer_summary", "자유응답 요약", "claude-haiku-5-5", 50_000, 4_000, 0.0),
    )
}

assert sum(feature.monthly_usd for feature in FEATURES.values()) <= MONTHLY_APP_LIMIT_USD


def to_micros(usd: float) -> int:
    """Ledger amounts are integer micro-dollars so sums never drift."""
    return int(round(usd * 1_000_000))


def call_cost_micros(model: str, input_tokens: int, output_tokens: int, *, batch: bool = False) -> int:
    input_price, output_price = PRICES[model]
    usd = input_tokens / 1e6 * input_price + output_tokens / 1e6 * output_price
    if batch:
        usd *= BATCH_DISCOUNT
    # Round up: the ledger may overstate a call by a micro-dollar, never understate it.
    return -(-int(usd * 1e12) // 1_000_000)


def usage_cost_micros(model: str, usage, *, batch: bool = False) -> tuple[int, int, int]:
    """Actual cost of a response from its usage block: (micros, input_tokens, output_tokens).

    Cache writes are priced at 2x input (the 1-hour rate, the dearer of the two)
    and cache reads at 0.1x, so the ledger never understates.
    """
    plain = int(getattr(usage, "input_tokens", 0) or 0)
    written = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    output = int(getattr(usage, "output_tokens", 0) or 0)
    weighted_input = plain + written * 2 + -(-read // 10)
    return call_cost_micros(model, weighted_input, output, batch=batch), plain + written + read, output


def max_call_micros(feature: Feature) -> int:
    """Worst case for one call: full input ceiling and full max_tokens (thinking included)."""
    return call_cost_micros(feature.model, feature.max_input_tokens, feature.max_output_tokens, batch=feature.batch)


def estimate_input_tokens(*texts: str) -> int:
    """Conservative count without a network call: one token per character plus overhead.

    Korean text tokenizes below one token per character, so this overestimates.
    """
    return sum(len(text or "") for text in texts) + 64


def month_key(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, KST).strftime("%Y-%m")
