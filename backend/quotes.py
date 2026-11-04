"""Current quotes: yfinance, then Yahoo's chart endpoint, then the last saved quote.

Both live sources depend on Yahoo, so only the saved quote helps if Yahoo is down.
Saved quotes are always labeled. A licensed vendor would replace this in production.
"""

from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, datetime
from typing import Any

import httpx
import yfinance

import cache
from edgar import normalize_ticker
from schemas import Quote

logger = logging.getLogger(__name__)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # We report failures ourselves.

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
LIVE_SOURCE_TIMEOUT = 10  # Seconds. A slow source shouldn't stall the briefing.
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="quotes")


class QuoteUnavailableError(Exception):
    """No live or saved quote exists. The message can be shown to the user."""


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _timestamp(value: Any) -> str | None:
    number = _number(value)
    if number is None or number <= 0:
        return None
    return datetime.fromtimestamp(number, UTC).isoformat()


def _build_quote(ticker: str, source: str, **fields: Any) -> Quote | None:
    """Build a quote, computing the change here rather than trusting a source's figure."""
    price = _number(fields.pop("price", None))
    if price is None or price <= 0:
        return None
    previous = _number(fields.get("previous_close"))
    change = price - previous if previous else None
    return Quote(
        ticker=ticker,
        source=source,
        price=price,
        previous_close=previous,
        change=round(change, 4) if change is not None else None,
        change_percent=round(change / previous * 100, 4) if change is not None else None,
        currency=fields.get("currency"),
        exchange=fields.get("exchange"),
        as_of=fields.get("as_of"),
        **{
            name: _number(fields.get(name))
            for name in ("day_low", "day_high", "year_low", "year_high", "market_cap")
        },
    )


def from_yfinance(ticker: str) -> Quote | None:
    # Use `info`, not `fast_info`: in testing, fast_info's previous close disagreed with
    # Yahoo's own figure (330.28 versus 331.90 for AAPL), and it has no as-of time.
    info = yfinance.Ticker(ticker).info
    return _build_quote(
        ticker, "yfinance",
        price=info.get("regularMarketPrice") or info.get("currentPrice"),
        previous_close=info.get("regularMarketPreviousClose") or info.get("previousClose"),
        day_low=info.get("regularMarketDayLow"),
        day_high=info.get("regularMarketDayHigh"),
        year_low=info.get("fiftyTwoWeekLow"),
        year_high=info.get("fiftyTwoWeekHigh"),
        market_cap=info.get("marketCap"),
        currency=info.get("currency"),
        exchange=info.get("fullExchangeName") or info.get("exchange"),
        as_of=_timestamp(info.get("regularMarketTime")),
    )


def from_yahoo_chart(ticker: str, http: httpx.Client | None = None) -> Quote | None:
    client = http or httpx.Client(
        headers={"User-Agent": "Mozilla/5.0 (stock-briefing-prototype)"},
        timeout=LIVE_SOURCE_TIMEOUT,
        follow_redirects=True,
    )
    # With a 1-day range, chartPreviousClose is the previous trading day's close.
    response = client.get(CHART_URL.format(ticker=ticker), params={"range": "1d", "interval": "1d"})
    response.raise_for_status()
    results = (response.json().get("chart") or {}).get("result") or []
    if not results:
        return None
    meta = results[0].get("meta", {})
    return _build_quote(
        ticker, "yahoo_chart",
        price=meta.get("regularMarketPrice"),
        previous_close=meta.get("chartPreviousClose"),
        day_low=meta.get("regularMarketDayLow"),
        day_high=meta.get("regularMarketDayHigh"),
        year_low=meta.get("fiftyTwoWeekLow"),
        year_high=meta.get("fiftyTwoWeekHigh"),
        currency=meta.get("currency"),
        exchange=meta.get("fullExchangeName") or meta.get("exchangeName"),
        as_of=_timestamp(meta.get("regularMarketTime")),
    )


def get_quote(ticker: str) -> Quote:
    wanted = normalize_ticker(ticker)
    for name, source in (("yfinance", from_yfinance), ("yahoo_chart", from_yahoo_chart)):
        future = _pool.submit(source, wanted)
        try:
            quote = future.result(timeout=LIVE_SOURCE_TIMEOUT)
        except FutureTimeoutError:
            logger.warning("Quote source %s timed out for %s", name, wanted)
            continue
        except Exception as exc:
            logger.warning("Quote source %s failed for %s: %s", name, wanted, type(exc).__name__)
            continue
        if quote is not None:
            cache.write("quotes", wanted, quote.model_dump())
            return quote
        logger.warning("Quote source %s had no data for %s", name, wanted)

    saved = cache.read("quotes", wanted)
    if saved is not None:
        return Quote(**{**saved, "source": "saved", "is_saved": True})
    raise QuoteUnavailableError(f"No quote is available for {wanted} right now.")
