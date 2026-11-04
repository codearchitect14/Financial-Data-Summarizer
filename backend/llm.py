"""LLM access: Gemini first, Groq when Gemini is unavailable.

This wraps the calls itself rather than using LangChain's `with_fallbacks`,
because that sends the same input to both models and doesn't report which one
answered. Groq's lower rate limits need a smaller input, and the UI must show
which provider produced each result.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from pydantic import BaseModel, SecretStr

logger = logging.getLogger(__name__)

Provider = Literal["gemini", "groq"]
Messages = Sequence[BaseMessage] | Callable[[Provider], Sequence[BaseMessage]]
T = TypeVar("T")
SchemaT = TypeVar("SchemaT", bound=BaseModel)

load_dotenv(Path(__file__).with_name(".env"))


class LLMError(Exception):
    """Base class for LLM failures. Messages are safe to show to users."""


class LLMConfigError(LLMError):
    """A setup or request problem that retrying elsewhere shouldn't hide."""


class LLMUnavailableError(LLMError):
    """No provider could answer."""


class InvalidStructuredOutputError(LLMError):
    """The model's reply didn't match the requested schema."""


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = ""
    groq_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    groq_model: str = "openai/gpt-oss-120b"
    force_failover: bool = False
    # Seconds. No Gemini retries, so a failure switches to Groq straight away.
    gemini_timeout: float = 30
    groq_timeout: float = 30
    # Limits output, as Groq's listed per-minute token limit also covers output.
    groq_max_output_tokens: int = 2000
    # gpt-oss spends output tokens on reasoning. At the default effort, a briefing ran
    # out of room before finishing its JSON.
    groq_reasoning_effort: str = "low"
    # Gemini's 503 says demand spikes are usually temporary, so wait once before failing
    # over. 504s were also seen in testing, and a full briefing is worth a short wait.
    retry_delay: float = 2
    groq_rate_limit_delay: float = 8

    def model_name(self, provider: Provider) -> str:
        return self.gemini_model if provider == "gemini" else self.groq_model

    def api_key(self, provider: Provider) -> str:
        return self.gemini_api_key if provider == "gemini" else self.groq_api_key


def load_settings() -> Settings:
    defaults = Settings()
    return Settings(
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "").strip() or defaults.gemini_model,
        groq_model=os.getenv("GROQ_MODEL", "").strip() or defaults.groq_model,
        force_failover=os.getenv("FORCE_LLM_FAILOVER", "").strip().lower()
        in {"1", "true", "yes"},
    )


def provider_status(settings: Settings | None = None) -> dict[str, Any]:
    """Describe the LLM setup for the health endpoint. Never includes keys."""
    s = settings or load_settings()
    return {
        "force_failover": s.force_failover,
        "providers": {
            p: {"configured": bool(s.api_key(p)), "model": s.model_name(p)}
            for p in ("gemini", "groq")
        },
    }


def make_model(provider: Provider, settings: Settings) -> BaseChatModel:
    if provider == "gemini":
        return ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=SecretStr(settings.gemini_api_key),
            # No temperature: gemini-3.5-flash-lite ignores it and warns.
            timeout=settings.gemini_timeout,
            max_retries=0,  # The client's default is 6, which would stall failover.
        )
    return ChatGroq(
        model=settings.groq_model,
        api_key=SecretStr(settings.groq_api_key),
        temperature=0,
        timeout=settings.groq_timeout,
        max_tokens=settings.groq_max_output_tokens,
        reasoning_effort=settings.groq_reasoning_effort,
        max_retries=1,  # Groq is the last resort, so one retry is worthwhile.
    )


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
        )


def usage_from(message: AIMessage | None) -> Usage:
    meta = getattr(message, "usage_metadata", None) or {}
    return Usage(meta.get("input_tokens", 0), meta.get("output_tokens", 0))


@dataclass(frozen=True)
class LLMResult(Generic[T]):
    value: T
    provider: Provider
    model: str
    fell_back: bool
    fallback_reason: str | None
    usage: Usage
    elapsed_seconds: float


# --- Error classification ---


def _exception_chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _status_code(exc: BaseException) -> int | None:
    # Clients wrap the original error, so look through the whole chain.
    for error in _exception_chain(exc):
        for attr in ("status_code", "code"):
            value = getattr(error, attr, None)
            if isinstance(value, int) and 100 <= value <= 599:
                return value
    return None


def _has_class_name(exc: BaseException, *fragments: str) -> bool:
    return any(
        fragment in cls.__name__
        for error in _exception_chain(exc)
        for cls in type(error).__mro__
        for fragment in fragments
    )


def _is_failed_generation(exc: BaseException) -> bool:
    # Groq reports output it couldn't complete as a 400, but the key and request are fine.
    return any(
        "json_validate_failed" in str(error) or "failed_generation" in str(error)
        for error in _exception_chain(exc)
    )


def should_fail_over(exc: BaseException) -> bool:
    """True if the provider is unavailable, rather than the request being wrong."""
    if isinstance(exc, InvalidStructuredOutputError) or _is_failed_generation(exc):
        return True
    status = _status_code(exc)
    if status is not None:
        return status in {408, 429} or status >= 500
    # No status means the request never completed, or Gemini returned an unusable
    # reply such as a blocked or empty response.
    return _has_class_name(
        exc, "Timeout", "ConnectError", "ConnectionError", "TransportError",
        "GoogleGenerativeAIError",
    )


def _is_provider_error(exc: BaseException) -> bool:
    # Separates real API rejections from bugs in our own code, which should surface.
    return _status_code(exc) is not None or _has_class_name(
        exc, "APIError", "GroqError", "GoogleGenerativeAIError", "ClientError"
    )


def _describe(exc: BaseException, settings: Settings) -> str:
    """Short error text for logs and users, with any API keys removed."""
    text = f"{type(exc).__name__}: {exc}"
    for secret in (settings.gemini_api_key, settings.groq_api_key):
        if secret:
            text = text.replace(secret, "[redacted]")
    text = re.sub(r"(?i)(key=)[^\s&'\"]+", r"\1[redacted]", text)
    return text[:300]


# --- The fallback itself ---


def call_with_fallback(
    call: Callable[[Provider, BaseChatModel], tuple[T, Usage]],
    settings: Settings | None = None,
) -> LLMResult[T]:
    """Run `call` on Gemini, then on Groq if Gemini is unavailable.

    `call` receives the provider so it can adapt its request, for example by
    sending less text to Groq. It returns its value and the tokens it used.
    """
    s = settings or load_settings()
    reason = "FORCE_LLM_FAILOVER is on" if s.force_failover else None

    if not s.force_failover:
        if not s.gemini_api_key:
            raise LLMConfigError("GEMINI_API_KEY is not set in backend/.env.")
        try:
            try:
                return _run("gemini", call, s, None)
            except Exception as exc:
                if _status_code(exc) not in {503, 504}:
                    raise
                logger.warning("Gemini was temporarily unavailable, retrying once.")
                time.sleep(s.retry_delay)
                return _run("gemini", call, s, None)
        except LLMConfigError:
            raise
        except Exception as exc:
            if not should_fail_over(exc):
                raise
            reason = _describe(exc, s)
            logger.warning("Gemini unavailable, switching to Groq: %s", reason)

    if not s.groq_api_key:
        if s.force_failover:
            raise LLMConfigError("GROQ_API_KEY is not set in backend/.env.")
        raise LLMUnavailableError(
            f"Gemini failed and GROQ_API_KEY is not set. Gemini: {reason}"
        )
    try:
        try:
            return _run("groq", call, s, reason)
        except Exception as exc:
            # A failed generation is intermittent: the same request then passed 3 times
            # out of 3. A per-minute rate limit clears within seconds, so it's worth a wait.
            rate_limited = _status_code(exc) == 429
            if not (rate_limited or _is_failed_generation(exc)):
                raise
            logger.warning("Groq was temporarily unavailable, retrying once.")
            time.sleep(s.groq_rate_limit_delay if rate_limited else s.retry_delay)
            return _run("groq", call, s, reason)
    except LLMConfigError:
        raise
    except Exception as exc:
        if not should_fail_over(exc):
            raise
        raise LLMUnavailableError(
            f"All LLM providers failed. Gemini: {reason}. Groq: {_describe(exc, s)}"
        ) from exc


def _run(
    provider: Provider,
    call: Callable[[Provider, BaseChatModel], tuple[T, Usage]],
    settings: Settings,
    fallback_reason: str | None,
) -> LLMResult[T]:
    started = time.perf_counter()
    try:
        value, usage = call(provider, make_model(provider, settings))
    except Exception as exc:
        if not should_fail_over(exc) and _is_provider_error(exc):
            raise LLMConfigError(
                f"{provider} rejected the request. Check its API key and model "
                f"name ({settings.model_name(provider)}). {_describe(exc, settings)}"
            ) from exc
        raise
    return LLMResult(
        value=value,
        provider=provider,
        model=settings.model_name(provider),
        fell_back=fallback_reason is not None,
        fallback_reason=fallback_reason,
        usage=usage,
        elapsed_seconds=round(time.perf_counter() - started, 2),
    )


# --- Single-provider calls ---


def invoke_text(
    model: BaseChatModel, messages: Sequence[BaseMessage]
) -> tuple[str, Usage]:
    reply = model.invoke(list(messages))
    return reply.text, usage_from(reply)


def invoke_structured(
    provider: Provider,
    model: BaseChatModel,
    schema: type[SchemaT],
    messages: Sequence[BaseMessage],
) -> tuple[SchemaT, Usage]:
    options: dict[str, Any] = {"method": "json_schema", "include_raw": True}
    if provider == "groq":
        options["strict"] = True
    reply = model.with_structured_output(schema, **options).invoke(list(messages))
    parsed = reply.get("parsed")
    if parsed is None:
        raise InvalidStructuredOutputError(
            f"{provider} did not return valid {schema.__name__}: "
            f"{reply.get('parsing_error')}"
        )
    return parsed, usage_from(reply.get("raw"))


def invoke_with_tools(
    provider: Provider,
    model: BaseChatModel,
    tools: Sequence[Any],
    messages: Sequence[BaseMessage],
) -> tuple[AIMessage, Usage]:
    # Groq's docs say openai/gpt-oss-120b doesn't support parallel tool use.
    options: dict[str, Any] = {"parallel_tool_calls": False} if provider == "groq" else {}
    reply = model.bind_tools(list(tools), **options).invoke(list(messages))
    return reply, usage_from(reply)


# --- Calls with fallback ---


def _resolve(messages: Messages, provider: Provider) -> Sequence[BaseMessage]:
    return messages(provider) if callable(messages) else messages


def ask_text(messages: Messages, settings: Settings | None = None) -> LLMResult[str]:
    return call_with_fallback(
        lambda provider, model: invoke_text(model, _resolve(messages, provider)),
        settings,
    )


def ask_structured(
    schema: type[SchemaT], messages: Messages, settings: Settings | None = None
) -> LLMResult[SchemaT]:
    return call_with_fallback(
        lambda provider, model: invoke_structured(
            provider, model, schema, _resolve(messages, provider)
        ),
        settings,
    )
