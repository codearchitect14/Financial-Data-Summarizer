"""Live Phase 1 checks against both providers, using the keys in backend/.env.

Run from backend/ with:  python check_llm.py
Exits with 0 only if every check passes. Never prints API keys.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import replace

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from llm import (
    Provider,
    Settings,
    Usage,
    ask_text,
    invoke_structured,
    invoke_text,
    invoke_with_tools,
    load_settings,
    make_model,
)

SHARE_PRICE = "123.45"


class Extraction(BaseModel):
    company: str = Field(description="Company name")
    revenue_billions: float = Field(description="Revenue in billions of dollars")
    supporting_quote: str = Field(description="Exact sentence from the text")


@tool
def get_share_price(ticker: str) -> str:
    """Get the current share price for a stock ticker."""
    return SHARE_PRICE


def check_plain(provider: Provider, settings: Settings) -> tuple[str, Usage]:
    text, usage = invoke_text(
        make_model(provider, settings),
        [HumanMessage(content="Reply with exactly the word: READY")],
    )
    assert "READY" in text.upper(), f"unexpected reply: {text[:100]!r}"
    return "replied", usage


def check_structured(provider: Provider, settings: Settings) -> tuple[str, Usage]:
    source = "Acme Corp reported revenue of 12.5 billion dollars for the year."
    result, usage = invoke_structured(
        provider,
        make_model(provider, settings),
        Extraction,
        [
            SystemMessage(content="Extract the requested fields from the text."),
            HumanMessage(content=source),
        ],
    )
    assert "acme" in result.company.lower(), f"company: {result.company!r}"
    assert result.revenue_billions == 12.5, f"revenue: {result.revenue_billions}"
    return "matched schema", usage


def check_tools(provider: Provider, settings: Settings) -> tuple[str, Usage]:
    # A full round trip, because the agent must also send tool results back.
    model = make_model(provider, settings)
    messages = [
        HumanMessage(content="What is ACME's share price? Use the tool to find out.")
    ]
    first, usage = invoke_with_tools(provider, model, [get_share_price], messages)
    assert first.tool_calls, f"no tool call; replied: {first.text[:100]!r}"
    call = first.tool_calls[0]
    assert call["name"] == "get_share_price", f"called {call['name']}"
    messages += [
        first,
        ToolMessage(content=get_share_price.invoke(call["args"]), tool_call_id=call["id"]),
    ]
    final, more = invoke_with_tools(provider, model, [get_share_price], messages)
    assert SHARE_PRICE in final.text, f"final answer: {final.text[:100]!r}"
    return "tool round trip", usage + more


def check_forced_failover(settings: Settings) -> tuple[str, Usage]:
    result = ask_text(
        [HumanMessage(content="Reply with exactly the word: READY")],
        replace(settings, force_failover=True),
    )
    assert result.provider == "groq" and result.fell_back, f"answered by {result.provider}"
    return "labeled groq", result.usage


def check_real_failover(settings: Settings) -> tuple[str, Usage]:
    # A 1 ms Gemini timeout causes a genuine failure, so this tests the real path.
    result = ask_text(
        [HumanMessage(content="Reply with exactly the word: READY")],
        replace(settings, force_failover=False, gemini_timeout=0.001),
    )
    assert result.provider == "groq" and result.fell_back, f"answered by {result.provider}"
    return "timeout moved to groq", result.usage


def main() -> int:
    settings = load_settings()
    missing = [
        name
        for name, value in (
            ("GEMINI_API_KEY", settings.gemini_api_key),
            ("GROQ_API_KEY", settings.groq_api_key),
        )
        if not value
    ]
    if missing:
        print(f"Add {' and '.join(missing)} to backend/.env, then run this again.")
        return 2

    print(f"Gemini model: {settings.gemini_model}\nGroq model:   {settings.groq_model}\n")

    checks: list[tuple[str, Callable[[], tuple[str, Usage]]]] = []
    for provider in ("gemini", "groq"):
        checks += [
            (f"{provider} plain reply", lambda p=provider: check_plain(p, settings)),
            (f"{provider} structured output", lambda p=provider: check_structured(p, settings)),
            (f"{provider} tool call", lambda p=provider: check_tools(p, settings)),
        ]
    checks += [
        ("forced failover", lambda: check_forced_failover(settings)),
        ("real failover", lambda: check_real_failover(settings)),
    ]

    failures = 0
    for name, check in checks:
        try:
            try:
                detail, usage = check()
            except Exception as exc:
                # A temporary overload says nothing about whether the feature works.
                if not ("503" in str(exc) or "504" in str(exc)):
                    raise
                print(f"      {name}: provider was temporarily unavailable, retrying in 10 seconds")
                time.sleep(10)
                detail, usage = check()
            print(f"PASS  {name:<28} {detail} ({usage.total_tokens} tokens)")
        except Exception as exc:
            failures += 1
            message = f"{type(exc).__name__}: {exc}"
            for secret in (settings.gemini_api_key, settings.groq_api_key):
                message = message.replace(secret, "[redacted]")
            print(f"FAIL  {name:<28} {message[:400]}")

    print(f"\n{len(checks) - failures} of {len(checks)} checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
