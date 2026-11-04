"""Live Phase 3 checks: real briefings on both providers, using the keys in backend/.env.

Run from backend/ with:  python check_briefing.py [--fresh]
--fresh ignores saved analyses, so tokens and timing reflect real LLM calls.
Exits with 0 only if every check passes. Never prints API keys.
"""

from __future__ import annotations

import sys
from dataclasses import replace

import cache
from briefing import build_briefing
from llm import Settings, load_settings
from schemas import Briefing

MIN_VERIFIED_SHARE = 0.7


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def describe(briefing: Briefing) -> str:
    llm = briefing.llm
    counts = briefing.verification
    share = counts.verified_claims / counts.total_claims if counts.total_claims else 0
    saved = " [saved]" if llm.from_saved else ""
    for section in briefing.sections:
        for claim in section.claims:
            if not claim.verified:
                print(f"      {claim.status}: {claim.text[:120]}\n        Quote: {claim.supporting_quote[:200]}")
    return (
        f"{llm.provider}{saved}, {counts.verified_claims}/{counts.total_claims} verified ({share:.0%}), "
        f"{llm.input_tokens}+{llm.output_tokens} tokens, LLM {llm.elapsed_seconds}s, "
        f"total {briefing.elapsed_seconds}s"
    )


def check_common(briefing: Briefing) -> None:
    counts = briefing.verification
    require(briefing.llm is not None, f"no analysis: {briefing.warnings}")
    require(briefing.quote is not None, "no quote")
    require(len(briefing.financials.years) >= 3, "too few years of financials")
    require(counts.total_claims > 0, "no claims")
    share = counts.verified_claims / counts.total_claims
    require(share >= MIN_VERIFIED_SHARE, f"only {share:.0%} of quotes verified")
    empty = [s.key for s in briefing.sections if not s.claims and s.key != "quarterly_risk_factors" and not s.warning]
    require(not empty, f"sections with no claims: {empty}")
    require(briefing.client_questions, "no client questions")


def check_full(ticker: str, settings: Settings) -> str:
    briefing = build_briefing(ticker, settings=replace(settings, force_failover=False))
    check_common(briefing)
    require(briefing.llm.provider == "gemini", f"answered by {briefing.llm.provider}")
    require(not briefing.llm.reduced, "should be a full briefing")
    return describe(briefing)


def check_reduced(ticker: str, settings: Settings) -> str:
    briefing = build_briefing(ticker, settings=replace(settings, force_failover=True))
    check_common(briefing)
    require(briefing.llm.provider == "groq", f"answered by {briefing.llm.provider}")
    require(briefing.llm.reduced, "should be labeled reduced")
    require(any("Reduced briefing" in w for w in briefing.warnings), "no label")
    return describe(briefing)


def print_sample(ticker: str, settings: Settings) -> None:
    briefing = build_briefing(ticker, settings=replace(settings, force_failover=False))
    print(f"\n--- Sample: {briefing.company.name} ---")
    for section in briefing.sections:
        print(f"\n{section.title} ({section.filing_form})")
        for claim in section.claims:
            print(f"  [{claim.status}] {claim.text}\n      Quote: {claim.supporting_quote[:160]}")
    print("\nClient questions:")
    for question in briefing.client_questions:
        print(f"  - {question}")


def main() -> int:
    settings = load_settings()
    if not (settings.gemini_api_key and settings.groq_api_key):
        print("Add GEMINI_API_KEY and GROQ_API_KEY to backend/.env, then run this again.")
        return 2
    if "--fresh" in sys.argv:
        cache.clear("analysis")

    checks = [
        ("AAPL full", lambda: check_full("AAPL", settings)),
        ("JPM full", lambda: check_full("JPM", settings)),
        ("AAPL reduced", lambda: check_reduced("AAPL", settings)),
    ]
    failures = 0
    for name, check in checks:
        try:
            print(f"PASS  {name:<14} {check()}")
        except Exception as exc:
            failures += 1
            message = f"{type(exc).__name__}: {exc}"
            for secret in (settings.gemini_api_key, settings.groq_api_key):
                message = message.replace(secret, "[redacted]")
            print(f"FAIL  {name:<14} {message[:500]}")

    print(f"\n{len(checks) - failures} of {len(checks)} checks passed.")
    if not failures:
        print_sample("AAPL", settings)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
