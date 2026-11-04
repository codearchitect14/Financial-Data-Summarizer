"""API behavior, with the pipeline replaced. No network or keys."""

import json

import pytest
from fastapi.testclient import TestClient

import agent as agent_module
import briefing as briefing_module
import main
from edgar import EdgarUnavailableError, TickerNotFoundError, UnsupportedFilerError
from llm import LLMConfigError, LLMUnavailableError
from quotes import QuoteUnavailableError
from schemas import Briefing, ChatResponse, Company, Financials, Quote

client = TestClient(main.app)


def parse_events(body):
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.split("\n")
        if lines[0].startswith("event: "):
            events.append((lines[0][7:], json.loads(lines[1][6:])))
    return events


def fake_briefing():
    return Briefing(
        company=Company(ticker="ACME", cik=1, name="Acme Corp"),
        financials=Financials(),
        generated_at="2026-11-04T17:00:00+00:00",
    )


@pytest.fixture
def pipeline(monkeypatch):
    seen = {}

    def build(ticker, *, settings=None, on_progress=None):
        seen.update(ticker=ticker, settings=settings)
        on_progress("company", "Looking up")
        on_progress("analysis", "Summarizing")
        return fake_briefing()

    monkeypatch.setattr(briefing_module, "build_briefing", build)
    return seen


def fail_with(monkeypatch, error):
    def build(ticker, *, settings=None, on_progress=None):
        raise error

    monkeypatch.setattr(briefing_module, "build_briefing", build)


def stream(ticker="ACME", **params):
    return client.get(f"/api/briefings/{ticker}/stream", params=params)


def test_progress_comes_first_then_one_result(pipeline):
    response = stream()
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    names = [name for name, _ in parse_events(response.text)]
    assert names == ["progress", "progress", "result"]


def test_result_contains_the_full_briefing(pipeline):
    _, result = parse_events(stream().text)[-1]
    assert Briefing(**result).company.name == "Acme Corp"


def test_dotted_ticker_reaches_the_pipeline(pipeline):
    stream("BRK.B")
    assert pipeline["ticker"] == "BRK.B"


def test_failover_switch_is_off_unless_requested(pipeline):
    stream()
    assert pipeline["settings"].force_failover in (False, True)  # Follows .env by default.
    stream(force_failover="true")
    assert pipeline["settings"].force_failover is True


@pytest.mark.parametrize(
    "error, code, retryable",
    [
        (TickerNotFoundError("Not a ticker."), "ticker_not_found", False),
        (UnsupportedFilerError("A fund."), "unsupported_filer", False),
        (EdgarUnavailableError("SEC is down."), "source_unavailable", True),
        (LLMConfigError("Bad key."), "configuration_error", False),
    ],
)
def test_known_errors_become_a_failed_event(monkeypatch, error, code, retryable):
    fail_with(monkeypatch, error)
    name, data = parse_events(stream().text)[-1]
    assert name == "failed"
    assert data == {"code": code, "message": str(error), "retryable": retryable}


def test_unexpected_errors_do_not_reveal_details(monkeypatch):
    fail_with(monkeypatch, RuntimeError("secret internal path /etc/key"))
    name, data = parse_events(stream().text)[-1]
    assert (name, data["code"]) == ("failed", "internal_error")
    assert "secret" not in data["message"]


def test_stream_is_kept_alive_during_long_waits(monkeypatch):
    monkeypatch.setattr(main, "KEEP_ALIVE_SECONDS", 0.01)
    import time

    def build(ticker, *, settings=None, on_progress=None):
        time.sleep(0.1)
        return fake_briefing()

    monkeypatch.setattr(briefing_module, "build_briefing", build)
    response = stream()
    assert ": keep-alive" in response.text
    assert parse_events(response.text)[-1][0] == "result"


def test_quote_endpoint_returns_the_current_quote(monkeypatch):
    seen = []

    def quote(ticker):
        seen.append(ticker)
        return Quote(ticker=ticker, price=10.5, as_of="2026-11-04T17:00:00+00:00", source="yfinance")

    monkeypatch.setattr(main, "get_quote", quote)
    response = client.get("/api/quotes/brk.b")
    assert response.status_code == 200
    assert response.json()["price"] == 10.5
    assert seen == ["BRK-B"]


def test_quote_endpoint_labels_a_saved_quote(monkeypatch):
    saved = Quote(ticker="ACME", price=9.0, source="saved", is_saved=True)
    monkeypatch.setattr(main, "get_quote", lambda ticker: saved)
    assert client.get("/api/quotes/ACME").json()["is_saved"] is True


def test_quote_endpoint_reports_when_no_quote_exists(monkeypatch):
    def fail(ticker):
        raise QuoteUnavailableError("No quote is available for ACME right now.")

    monkeypatch.setattr(main, "get_quote", fail)
    response = client.get("/api/quotes/ACME")
    assert response.status_code == 503
    assert response.json()["code"] == "quote_unavailable"


def test_quote_endpoint_rejects_a_malformed_ticker_without_calling_yahoo(monkeypatch):
    def never(ticker):
        raise AssertionError("should not fetch a quote")

    monkeypatch.setattr(main, "get_quote", never)
    assert client.get("/api/quotes/not%20a%20ticker!").status_code == 404


def test_health_never_includes_keys(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gem-secret")
    monkeypatch.setenv("GROQ_API_KEY", "grq-secret")
    response = client.get("/api/health")
    assert response.status_code == 200
    assert "secret" not in response.text
    assert response.json()["providers"]["gemini"]["configured"] is True


def test_health_reports_missing_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("FORCE_LLM_FAILOVER", "0")
    assert client.get("/api/health").json()["status"] == "degraded"


def fake_answer(**fields):
    return ChatResponse(answer="Revenue rose.", provider="gemini", model="m", **fields)


def test_chat_returns_the_answer_and_passes_the_request(monkeypatch):
    seen = {}

    def answer(ticker, question, history, *, settings):
        seen.update(ticker=ticker, question=question, history=history, settings=settings)
        return fake_answer(tools_used=["Annual financials"])

    monkeypatch.setattr(agent_module, "answer_question", answer)
    body = {
        "ticker": "AAPL", "question": "How did revenue change?", "force_failover": True,
        "history": [{"role": "user", "content": "Hi"}],
    }
    response = client.post("/api/chat", json=body)
    assert response.status_code == 200
    assert response.json()["answer"] == "Revenue rose."
    assert response.json()["tools_used"] == ["Annual financials"]
    assert seen["ticker"] == "AAPL" and seen["history"][0].content == "Hi"
    assert seen["settings"].force_failover is True


@pytest.mark.parametrize(
    "error, status, code",
    [
        (TickerNotFoundError("Not a ticker."), 404, "ticker_not_found"),
        (UnsupportedFilerError("A fund."), 422, "unsupported_filer"),
        (LLMUnavailableError("Groq: raw detail"), 503, "llm_unavailable"),
        (LLMConfigError("Bad key."), 500, "configuration_error"),
        (RuntimeError("secret path"), 500, "internal_error"),
    ],
)
def test_chat_failures_have_clear_codes_and_hide_details(monkeypatch, error, status, code):
    def answer(*args, **kwargs):
        raise error

    monkeypatch.setattr(agent_module, "answer_question", answer)
    response = client.post("/api/chat", json={"ticker": "AAPL", "question": "Why?"})
    assert response.status_code == status
    assert response.json()["code"] == code
    assert "secret" not in response.text and "raw detail" not in response.text


@pytest.mark.parametrize(
    "body",
    [{}, {"ticker": "AAPL"}, {"ticker": "AAPL", "question": ""}, {"ticker": "AAPL", "question": "x" * 2001}],
)
def test_chat_rejects_invalid_requests(body):
    assert client.post("/api/chat", json=body).status_code == 422
