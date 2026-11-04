"""Live Phase 4 checks. Starts the real server on a spare port and streams real briefings.

Run from backend/ with:  python check_api.py
Exits with 0 only if every check passes.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time

import httpx
import uvicorn

import main


def spare_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def stream(base: str, ticker: str, **params) -> tuple[list[tuple[float, str, dict]], float]:
    """Return each event with the time it arrived, proving they aren't sent all at once."""
    started = time.perf_counter()
    events, name = [], None
    with httpx.stream("GET", f"{base}/api/briefings/{ticker}/stream", params=params, timeout=150) as response:
        assert response.status_code == 200, f"status {response.status_code}"
        for line in response.iter_lines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                events.append((time.perf_counter() - started, name, json.loads(line[6:])))
    return events, time.perf_counter() - started


def check_briefing(base: str, ticker: str, expected_provider: str | None = None, **params) -> str:
    events, total = stream(base, ticker, **params)
    names = [name for _, name, _ in events]
    assert names[-1] == "result", f"ended with {names[-1]}: {events[-1][2]}"
    assert names.count("result") == 1 and names.count("progress") >= 5, f"events: {names}"
    result = events[-1][2]
    llm, counts = result["llm"], result["verification"]
    assert llm, f"no analysis: {result['warnings']}"
    assert result["quote"] and result["financials"]["years"], "missing quote or financials"
    if expected_provider:
        assert llm["provider"] == expected_provider, f"answered by {llm['provider']}"
    if llm["provider"] == "groq":
        assert any("Reduced briefing" in w for w in result["warnings"]), "no reduced label"
    saved = " saved" if llm["from_saved"] else ""
    if not llm["from_saved"] and llm["provider"] == "gemini":
        # On a real LLM call, the "analysis" step must arrive well before the result.
        analysis_at = next(at for at, name, data in events if data.get("step") == "analysis")
        assert total - analysis_at > 3, f"events arrived together: analysis at {analysis_at:.1f}s of {total:.1f}s"
    return (
        f"{llm['provider']}{saved}, {counts['verified_claims']}/{counts['total_claims']} verified, "
        f"{len(names)} events over {total:.1f}s, last progress at {events[-2][0]:.1f}s"
    )


def check_rejected(base: str, ticker: str, code: str) -> str:
    events, _ = stream(base, ticker)
    name, data = events[-1][1], events[-1][2]
    assert name == "failed" and data["code"] == code, f"got {name}: {data}"
    return data["message"][:70]


def check_health(base: str) -> str:
    response = httpx.get(f"{base}/api/health", timeout=10)
    body = response.json()
    assert response.status_code == 200 and body["status"] == "ok", f"health: {body}"
    settings = main.load_settings()
    for secret in (settings.gemini_api_key, settings.groq_api_key):
        assert secret not in response.text, "health exposes a key"
    return "ok, no keys exposed"


def check_no_keys_in_result(base: str) -> str:
    events, _ = stream(base, "AAPL")
    text = json.dumps([data for _, _, data in events])
    settings = main.load_settings()
    for secret in (settings.gemini_api_key, settings.groq_api_key):
        assert secret not in text, "stream exposes a key"
    return "no keys in stream"


def main_check() -> int:
    port = spare_port()
    server = uvicorn.Server(uvicorn.Config(main.app, port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    base = f"http://127.0.0.1:{port}"

    checks = [
        ("health", lambda: check_health(base)),
        ("AAPL", lambda: check_briefing(base, "AAPL")),
        ("NVDA first run", lambda: check_briefing(base, "NVDA")),
        ("XOM first run", lambda: check_briefing(base, "XOM")),
        ("JPM on Groq", lambda: check_briefing(base, "JPM", "groq", force_failover="true")),
        ("ZZZZZ", lambda: check_rejected(base, "ZZZZZ", "ticker_not_found")),
        ("SPY", lambda: check_rejected(base, "SPY", "unsupported_filer")),
        ("ASML", lambda: check_rejected(base, "ASML", "unsupported_filer")),
        ("no keys in stream", lambda: check_no_keys_in_result(base)),
    ]
    failures = 0
    for name, check in checks:
        try:
            print(f"PASS  {name:<18} {check()}")
        except Exception as exc:
            failures += 1
            print(f"FAIL  {name:<18} {type(exc).__name__}: {str(exc)[:400]}")
    server.should_exit = True
    print(f"\n{len(checks) - failures} of {len(checks)} checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main_check())
