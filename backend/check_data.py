"""Live Phase 2 checks against SEC EDGAR and Yahoo. Needs no LLM keys.

Run from backend/ with:  python check_data.py
Exits with 0 only if every check passes.
"""

from __future__ import annotations

import os
import sys

from edgar import (
    EdgarClient,
    TickerNotFoundError,
    UnsupportedFilerError,
)
from quotes import get_quote

# Figures known independently of this code: (period end, field, value).
KNOWN_FIGURES = {
    "AAPL": ("2025-09-27", "revenue", 416_161_000_000),
    "MSFT": ("2024-06-30", "revenue", 245_122_000_000),
    "JPM": ("2024-12-31", "net_income", 58_471_000_000),
    "XOM": ("2024-12-31", "net_income", 33_680_000_000),
    "NVDA": ("2025-01-26", "eps_diluted", 2.94),  # Adjusted for the 2024 stock split.
}
FULL_COMPANIES = ["AAPL", "MSFT", "JPM", "XOM", "NVDA", "BAC", "BRK.B"]
REJECTED = {
    "SPY": UnsupportedFilerError,
    "ASML": UnsupportedFilerError,
    "ZZZZZ": TickerNotFoundError,
    "not a ticker!": TickerNotFoundError,
}
MUST_FIND = ("business", "risk_factors", "mdna")
# The heading text each section's start should contain.
SECTION_MUST_START_NEAR = {
    "risk_factors": "risk factors",
    "mdna": "discussion and analysis",
    "business": "business",
}


def check_company(ticker: str) -> str:
    client = EdgarClient()
    company = client.resolve_company(ticker)
    filings = client.get_filings(company)
    assert filings.annual, "no 10-K found"
    if filings.quarterly:
        assert filings.quarterly.filing_date > filings.annual.filing_date, "10-Q is older than 10-K"

    sections = client.get_sections(filings)
    methods = []
    for key in MUST_FIND:
        section = sections[key]
        assert section.found, f"{key} not found"
        head = section.text[:200].lower()
        assert SECTION_MUST_START_NEAR[key] in head, f"{key} starts with {head[:70]!r}"
        methods.append(f"{key}:{section.method}")
    assert "<" not in sections["mdna"].text[:2000], "HTML left in the text"

    financials = client.get_financials(company)
    assert len(financials.years) >= 3, f"only {len(financials.years)} years"
    assert all(y.revenue for y in financials.years), "a year is missing revenue"
    if ticker in KNOWN_FIGURES:
        end, field, expected = KNOWN_FIGURES[ticker]
        year = next((y for y in financials.years if y.period_end == end), None)
        assert year, f"no year ending {end}"
        assert getattr(year, field) == expected, f"{field}: {getattr(year, field)} != {expected}"

    quote = get_quote(ticker)
    assert not quote.is_saved, "quote came from saved data"
    assert quote.price > 0 and quote.as_of, "quote has no price or as-of time"
    assert quote.change is not None, "quote has no change"
    assert not client.used_saved_data, "EDGAR data came from a saved copy"

    quarter = "10-Q used" if filings.quarterly else "10-K is newest"
    return f"{quote.source} {quote.price:.2f}, {len(financials.years)} years, {quarter}, " + ", ".join(
        m.split(":")[1] for m in methods
    )


def check_rejected(ticker: str, expected: type[Exception]) -> str:
    client = EdgarClient()
    try:
        client.get_filings(client.resolve_company(ticker))
    except expected as exc:
        return str(exc)[:80]
    raise AssertionError(f"expected {expected.__name__}")


def main() -> int:
    if "example.com" in os.getenv("SEC_USER_AGENT", "example.com"):
        print("Note: set a real name and email for SEC_USER_AGENT in backend/.env.\n")

    checks = [(t, lambda t=t: check_company(t)) for t in FULL_COMPANIES]
    checks += [(t, lambda t=t, e=e: check_rejected(t, e)) for t, e in REJECTED.items()]

    failures = 0
    for name, check in checks:
        try:
            print(f"PASS  {name:<14} {check()}")
        except Exception as exc:
            failures += 1
            print(f"FAIL  {name:<14} {type(exc).__name__}: {str(exc)[:300]}")

    print(f"\n{len(checks) - failures} of {len(checks)} checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
