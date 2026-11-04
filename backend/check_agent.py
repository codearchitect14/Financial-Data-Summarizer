"""Live Phase 6 checks: real questions on both providers, using the keys in backend/.env.

Run from backend/ with:  python check_agent.py
Exits with 0 only if every check passes.
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import replace

from agent import answer_question
from edgar import EdgarClient
from llm import load_settings

QUESTION = "How did revenue change, and what risks does management flag?"


# Figures attached to the wrong year, as Groq once produced. AAPL's real revenue is
# $391.0B for 2024, $416.2B for 2025 and $478.8B for 2026.
WRONG_YEAR = re.compile(
    r"416\.2 billion[^.;$]{0,30}(?:fiscal |FY ?)?2024|(?:fiscal |FY ?)2024[^.;$]{0,30}416\.2"
    r"|478\.8 billion[^.;$]{0,30}(?:fiscal |FY ?)?2025|(?:fiscal |FY ?)2025[^.;$]{0,30}478\.8",
    re.IGNORECASE,
)


def check(ticker, question, settings, provider=None, min_tools=0, expect=(), reject=()):
    response = answer_question(ticker, question, settings=settings)
    print(f"      A: {response.answer}\n      Tools: {response.tools_used}")
    assert not provider or response.provider == provider, f"answered by {response.provider}"
    assert len(response.tools_used) >= min_tools, f"tools used: {response.tools_used}"
    print(f"      Unsupported figures: {response.unsupported_figures}")
    assert not WRONG_YEAR.search(response.answer), "a figure is attached to the wrong year"
    text = response.answer.lower()
    for phrase in expect:
        assert phrase.lower() in text, f"answer doesn't mention {phrase!r}"
    for phrase in reject:
        assert phrase.lower() not in text, f"answer mentions {phrase!r}"
    return (
        f"{response.provider}, {len(response.tools_used)} tool types, "
        f"{response.input_tokens}+{response.output_tokens} tokens, {response.elapsed_seconds}s"
    )


def main() -> int:
    settings = load_settings()
    if not (settings.gemini_api_key and settings.groq_api_key):
        print("Add GEMINI_API_KEY and GROQ_API_KEY to backend/.env, then run this again.")
        return 2
    print(f"Actual AAPL figures: {[(y.period_end, y.revenue) for y in EdgarClient().get_financials(EdgarClient().resolve_company('AAPL')).years[:2]]}\n")

    gemini, groq = replace(settings, force_failover=False), replace(settings, force_failover=True)
    checks = [
        ("Gemini two parts", lambda: check("AAPL", QUESTION, gemini, "gemini", 2, expect=["478.8"])),
        ("Groq two parts", lambda: check("AAPL", QUESTION, groq, "groq", 2, expect=["478.8"])),
        ("Advice declined", lambda: check("AAPL", "Should my client buy this stock now? Give a price target.", gemini, reject=["should buy", "you should sell"])),
    ]
    failures = 0
    for name, run in checks:
        print(f"{name}:")
        try:
            print(f"PASS  {run()}\n")
        except Exception as exc:
            failures += 1
            print(f"FAIL  {type(exc).__name__}: {str(exc)[:500]}\n")
        time.sleep(1)
    print(f"{len(checks) - failures} of {len(checks)} checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
