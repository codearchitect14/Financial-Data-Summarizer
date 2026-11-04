"""The HTTP API. All keys stay here on the server, and the browser only sees results.

Run from backend/ with:  uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse

import agent as agent_module
import briefing as briefing_module
from edgar import (
    EdgarConfigError,
    EdgarUnavailableError,
    TickerNotFoundError,
    UnsupportedFilerError,
    normalize_ticker,
)
from llm import LLMConfigError, LLMUnavailableError, load_settings, provider_status
from quotes import QuoteUnavailableError, get_quote
from schemas import ChatRequest, ChatResponse, Quote

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
# httpx logs full request URLs at INFO, and we don't want those in demo output.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

KEEP_ALIVE_SECONDS = 10

app = FastAPI(title="Stock Briefing Assistant", version="0.1.0")

# (code, whether trying again could help), by error type. The UI can act on both.
_ERROR_CODES: dict[type[Exception], tuple[str, bool]] = {
    TickerNotFoundError: ("ticker_not_found", False),
    UnsupportedFilerError: ("unsupported_filer", False),
    EdgarUnavailableError: ("source_unavailable", True),
    LLMUnavailableError: ("llm_unavailable", True),
    EdgarConfigError: ("configuration_error", False),
    LLMConfigError: ("configuration_error", False),
}


def _event(name: str, data: Any) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def _failure(exc: Exception) -> dict[str, Any]:
    for error_type, (code, retryable) in _ERROR_CODES.items():
        if isinstance(exc, error_type):
            return {"code": code, "message": str(exc), "retryable": retryable}
    # An unexpected error could include internal details, so only the log gets those.
    logger.exception("Unexpected error while building a briefing", exc_info=exc)
    return {
        "code": "internal_error",
        "message": "Something went wrong while building this briefing. Please try again.",
        "retryable": True,
    }


def _briefing_events(ticker: str, force_failover: bool) -> Iterator[str]:
    """Run the pipeline in a thread, and yield its events as they happen.

    If the browser disconnects, the thread still finishes, so its analysis is saved
    and the tokens aren't wasted.
    """
    events: queue.Queue[str | None] = queue.Queue()

    def work() -> None:
        try:
            settings = load_settings()
            if force_failover:
                settings = replace(settings, force_failover=True)
            result = briefing_module.build_briefing(
                ticker,
                settings=settings,
                on_progress=lambda step, message: events.put(
                    _event("progress", {"step": step, "message": message})
                ),
            )
            events.put(_event("result", result.model_dump()))
        except Exception as exc:
            events.put(_event("failed", _failure(exc)))
        finally:
            events.put(None)

    threading.Thread(target=work, daemon=True, name=f"briefing-{ticker}").start()
    while True:
        try:
            event = events.get(timeout=KEEP_ALIVE_SECONDS)
        except queue.Empty:
            yield ": keep-alive\n\n"  # A comment line, which browsers ignore.
            continue
        if event is None:
            return
        yield event


@app.get("/api/briefings/{ticker}/stream")
def stream_briefing(ticker: str, force_failover: bool = False) -> StreamingResponse:
    """Stream `progress` events, then one `result` or `failed` event.

    The event is named `failed` because `error` is the browser's own connection event.
    The client must close its EventSource on either final event. Otherwise it will
    reconnect when the stream ends, and generate the briefing again.
    """
    return StreamingResponse(
        _briefing_events(ticker, force_failover),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# HTTP status for each failure code, when chat responds with plain JSON.
_HTTP_STATUS = {
    "ticker_not_found": 404,
    "unsupported_filer": 422,
    "source_unavailable": 503,
    "llm_unavailable": 503,
    "configuration_error": 500,
    "internal_error": 500,
}


@app.post("/api/chat", response_model=None)
def chat(request: ChatRequest) -> ChatResponse | JSONResponse:
    try:
        settings = load_settings()
        if request.force_failover:
            settings = replace(settings, force_failover=True)
        return agent_module.answer_question(
            request.ticker, request.question, request.history, settings=settings
        )
    except Exception as exc:
        failure = _failure(exc)
        if failure["code"] == "llm_unavailable":
            # Often Groq's per-minute limit just after a briefing, so a short wait helps.
            logger.warning("Chat failed: %s", exc)
            failure["message"] = "The LLMs are busy right now. Please try again in about a minute."
        return JSONResponse(status_code=_HTTP_STATUS[failure["code"]], content=failure)


@app.get("/api/quotes/{ticker}", response_model=None)
def live_quote(ticker: str) -> Quote | JSONResponse:
    """Return only the current quote, for refreshing the page. Uses no LLM quota."""
    wanted = normalize_ticker(ticker)
    if not re.fullmatch(r"[A-Z0-9-]{1,10}", wanted):
        return JSONResponse(
            status_code=404,
            content={"code": "ticker_not_found", "message": "That isn't a valid ticker.", "retryable": False},
        )
    try:
        return get_quote(wanted)
    except QuoteUnavailableError as exc:
        return JSONResponse(
            status_code=503,
            content={"code": "quote_unavailable", "message": str(exc), "retryable": True},
        )


@app.get("/api/health")
def health() -> dict[str, Any]:
    status = provider_status()
    ready = status["force_failover"] or status["providers"]["gemini"]["configured"]
    sec_configured = bool(os.getenv("SEC_USER_AGENT", "").strip())
    return {"status": "ok" if ready and sec_configured else "degraded", **status, "sec_configured": sec_configured}
