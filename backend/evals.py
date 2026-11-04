"""Measures the pipeline across companies, and saves the results for the slide.

Run from backend/ with:  python evals.py
Saved analyses are reused, so a run costs little. Their token counts and LLM times are
from when they were generated. Results go to eval_results.json and eval_results.md.
Exits with 0 only if every company behaves as expected. The verification rate is
reported rather than required, because a low rate means flagged claims, not a failure.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from briefing import build_briefing
from edgar import EdgarClient, EdgarError
from llm import Settings, load_settings
from schemas import Briefing

FULL_TICKERS = ["AAPL", "MSFT", "NVDA", "JPM", "XOM", "TSLA", "WMT", "PFE", "GOOGL", "ORCL"]
REDUCED_TICKERS = ["AAPL", "JPM", "WMT"]
REJECTED_TICKERS = {"ASML": "UnsupportedFilerError", "SPY": "UnsupportedFilerError", "ZZZZZ": "TickerNotFoundError"}
# Sections every 10-K briefing needs. A 10-Q's sections depend on the filing dates.
REQUIRED_SECTIONS = ("business", "risk_factors", "mdna")
RESULTS_DIR = Path(__file__).parent


def evaluate(ticker: str, settings: Settings) -> dict[str, Any]:
    edgar = EdgarClient()
    briefing: Briefing = build_briefing(ticker, settings=settings, client=edgar)
    sections = edgar.get_sections(edgar.get_filings(briefing.company))
    llm = briefing.llm
    counts = briefing.verification
    return {
        "ticker": briefing.company.ticker,
        "provider": llm.provider if llm else None,
        "reduced": llm.reduced if llm else None,
        "from_saved": llm.from_saved if llm else None,
        "verified": counts.verified_claims,
        "claims": counts.total_claims,
        "sections_found": sum(1 for key in REQUIRED_SECTIONS if sections[key].found),
        "sections_required": len(REQUIRED_SECTIONS),
        "found_by_name": [key for key, s in sections.items() if s.method == "section_name"],
        "financial_years": len(briefing.financials.years),
        "has_quote": briefing.quote is not None,
        "input_tokens": llm.input_tokens if llm else 0,
        "output_tokens": llm.output_tokens if llm else 0,
        "llm_seconds": llm.elapsed_seconds if llm else None,
    }


def problems(row: dict[str, Any], expected_provider: str) -> list[str]:
    found = []
    if row["provider"] != expected_provider:
        found.append(f"answered by {row['provider']}")
    if row["claims"] == 0:
        found.append("no claims")
    if row["sections_found"] < row["sections_required"]:
        found.append("missing a 10-K section")
    if row["financial_years"] < 3:
        found.append("too few years of financials")
    if not row["has_quote"]:
        found.append("no quote")
    return found


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    claims = sum(r["claims"] for r in rows)
    verified = sum(r["verified"] for r in rows)
    rates = [r["verified"] / r["claims"] for r in rows if r["claims"]]
    return {
        "tickers": len(rows),
        "verified": verified,
        "claims": claims,
        "verified_share": round(verified / claims, 3) if claims else 0,
        "lowest_share": round(min(rates), 3) if rates else 0,
        "highest_share": round(max(rates), 3) if rates else 0,
        "sections_found": sum(r["sections_found"] for r in rows),
        "sections_required": sum(r["sections_required"] for r in rows),
        "median_input_tokens": int(median(r["input_tokens"] for r in rows)),
        "median_output_tokens": int(median(r["output_tokens"] for r in rows)),
        "median_llm_seconds": round(median(r["llm_seconds"] for r in rows if r["llm_seconds"] is not None), 1),
    }


def check_rejected(ticker: str, expected: str) -> dict[str, Any]:
    client = EdgarClient()
    try:
        client.get_filings(client.resolve_company(ticker))
    except EdgarError as exc:
        return {"ticker": ticker, "passed": type(exc).__name__ == expected, "message": str(exc)}
    return {"ticker": ticker, "passed": False, "message": "No error was raised."}


def markdown(results: dict[str, Any]) -> str:
    lines = [
        "# Evaluation results",
        "",
        f"Generated {results['generated_at']}. One run per ticker and provider, so treat this as a small sample.",
        "",
        "| Provider | Tickers | Quotes verified | Range by ticker | Required sections found | Median tokens (in + out) | Median LLM time |",
        "|---|---|---|---|---|---|---|",
    ]
    for label, key in (("Gemini (full)", "full_summary"), ("Groq (reduced)", "reduced_summary")):
        s = results[key]
        if s:
            lines.append(
                f"| {label} | {s['tickers']} | {s['verified']} of {s['claims']} ({s['verified_share']:.0%}) | "
                f"{s['lowest_share']:.0%} to {s['highest_share']:.0%} | {s['sections_found']} of {s['sections_required']} | "
                f"{s['median_input_tokens']:,} + {s['median_output_tokens']:,} | {s['median_llm_seconds']} s |"
            )
    lines += ["", "| Ticker | Provider | Verified | Found by name, not heading | Years | LLM time |", "|---|---|---|---|---|---|"]
    for row in results["full"] + results["reduced"]:
        names = ", ".join(row["found_by_name"]) or "None"
        lines.append(
            f"| {row['ticker']} | {row['provider']} | {row['verified']} of {row['claims']} | {names} | "
            f"{row['financial_years']} | {row['llm_seconds']} s |"
        )
    lines += ["", "| Rejected ticker | Passed | Message |", "|---|---|---|"]
    for row in results["rejected"]:
        lines.append(f"| {row['ticker']} | {'Yes' if row['passed'] else 'No'} | {row['message']} |")
    lines += [
        "",
        "Measured: each quote is in the filings and contains the claim's amounts. "
        "Not measured: whether each claim is a fair reading of its quote.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    settings = load_settings()
    if not (settings.gemini_api_key and settings.groq_api_key):
        print("Add GEMINI_API_KEY and GROQ_API_KEY to backend/.env, then run this again.")
        return 2

    failures = 0
    runs: dict[str, list[dict[str, Any]]] = {"full": [], "reduced": []}
    plans = [
        ("full", FULL_TICKERS, replace(settings, force_failover=False), "gemini"),
        ("reduced", REDUCED_TICKERS, replace(settings, force_failover=True), "groq"),
    ]
    for mode, tickers, mode_settings, provider in plans:
        for ticker in tickers:
            try:
                row = evaluate(ticker, mode_settings)
            except Exception as exc:
                failures += 1
                print(f"FAIL  {ticker:<6} {mode:<8} {type(exc).__name__}: {str(exc)[:200]}")
                continue
            issues = problems(row, provider)
            failures += bool(issues)
            runs[mode].append(row)
            status = "FAIL" if issues else "PASS"
            saved = " saved" if row["from_saved"] else " fresh"
            print(f"{status}  {ticker:<6} {mode:<8} {row['provider']}{saved}, {row['verified']}/{row['claims']} verified {issues or ''}")

    rejected = [check_rejected(ticker, expected) for ticker, expected in REJECTED_TICKERS.items()]
    for row in rejected:
        failures += not row["passed"]
        print(f"{'PASS' if row['passed'] else 'FAIL'}  {row['ticker']:<6} rejected {row['message'][:70]}")

    results = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "gemini_model": settings.gemini_model,
        "groq_model": settings.groq_model,
        "full_summary": summarize(runs["full"]),
        "reduced_summary": summarize(runs["reduced"]),
        **runs,
        "rejected": rejected,
    }
    (RESULTS_DIR / "eval_results.json").write_text(json.dumps(results, indent=2))
    (RESULTS_DIR / "eval_results.md").write_text(markdown(results))
    print(f"\nFull: {results['full_summary']}\nReduced: {results['reduced_summary']}")
    print(f"\nWrote eval_results.json and eval_results.md. Problems: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
