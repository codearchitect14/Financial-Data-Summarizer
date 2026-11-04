"""Quote fallbacks and calculations. No network."""

import time

import httpx
import pytest

import cache
import quotes
from quotes import QuoteUnavailableError, from_yahoo_chart, get_quote
from schemas import Quote


@pytest.fixture(autouse=True)
def temporary_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)


def fake_quote(source="yfinance", price=100.0):
    return Quote(ticker="ACME", price=price, as_of="2026-11-04T17:00:00+00:00", source=source)


def use_sources(monkeypatch, yfinance_source, chart_source):
    monkeypatch.setattr(quotes, "from_yfinance", yfinance_source)
    monkeypatch.setattr(quotes, "from_yahoo_chart", chart_source)


def fail(ticker):
    raise httpx.ConnectError("down")


def test_uses_yfinance_first(monkeypatch):
    use_sources(monkeypatch, lambda t: fake_quote(), fail)
    assert get_quote("acme").source == "yfinance"


@pytest.mark.parametrize("first", [fail, lambda t: None])
def test_moves_to_chart_when_yfinance_fails_or_is_empty(monkeypatch, first):
    use_sources(monkeypatch, first, lambda t: fake_quote("yahoo_chart"))
    assert get_quote("ACME").source == "yahoo_chart"


def test_slow_source_is_abandoned(monkeypatch):
    monkeypatch.setattr(quotes, "LIVE_SOURCE_TIMEOUT", 0.05)
    use_sources(monkeypatch, lambda t: time.sleep(0.5), lambda t: fake_quote("yahoo_chart"))
    assert get_quote("ACME").source == "yahoo_chart"


def test_saved_quote_is_labeled_when_live_sources_fail(monkeypatch):
    use_sources(monkeypatch, lambda t: fake_quote(price=42.0), fail)
    get_quote("ACME")
    use_sources(monkeypatch, fail, fail)
    saved = get_quote("ACME")
    assert (saved.price, saved.source, saved.is_saved) == (42.0, "saved", True)
    assert saved.as_of == "2026-11-04T17:00:00+00:00"  # The original time, not "now".


def test_no_quote_anywhere_is_a_clear_error(monkeypatch):
    use_sources(monkeypatch, fail, fail)
    with pytest.raises(QuoteUnavailableError, match="ACME"):
        get_quote("ACME")


def test_dotted_ticker_is_normalized_for_yahoo(monkeypatch):
    seen = []
    use_sources(monkeypatch, lambda t: seen.append(t) or fake_quote(), fail)
    get_quote("brk.b")
    assert seen == ["BRK-B"]


def test_change_is_computed_from_price_and_previous_close():
    quote = quotes._build_quote("ACME", "yfinance", price=110, previous_close=100)
    assert (quote.change, quote.change_percent) == (10, 10)


@pytest.mark.parametrize("price", [None, 0, -5, float("nan"), float("inf"), "n/a"])
def test_unusable_price_means_no_quote(price):
    assert quotes._build_quote("ACME", "yfinance", price=price) is None


def test_missing_previous_close_leaves_change_empty():
    quote = quotes._build_quote("ACME", "yfinance", price=110, previous_close=None)
    assert quote.change is None and quote.change_percent is None


def chart_client(payload, status=200):
    def respond(request):
        return httpx.Response(status, json=payload, request=request)

    return httpx.Client(transport=httpx.MockTransport(respond))


def test_chart_endpoint_is_parsed():
    payload = {"chart": {"result": [{"meta": {
        "regularMarketPrice": 353.9, "chartPreviousClose": 331.9,
        "regularMarketDayLow": 340.0, "regularMarketDayHigh": 354.0,
        "fiftyTwoWeekLow": 243.0, "fiftyTwoWeekHigh": 354.5,
        "currency": "USD", "fullExchangeName": "NasdaqGS", "regularMarketTime": 1793814585,
    }}]}}
    quote = from_yahoo_chart("AAPL", http=chart_client(payload))
    assert quote.price == 353.9
    assert quote.previous_close == 331.9
    assert quote.change == 22.0
    assert quote.exchange == "NasdaqGS"
    assert quote.as_of.endswith("+00:00")


def test_chart_with_no_results_means_no_quote():
    payload = {"chart": {"result": None, "error": {"code": "Not Found"}}}
    assert from_yahoo_chart("ZZZZ", http=chart_client(payload)) is None
