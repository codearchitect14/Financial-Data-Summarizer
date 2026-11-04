"""Fallback rules, tested with the providers' real exception types. No keys or network."""

import httpx
import groq
import pytest
from google.genai import errors as genai_errors
from langchain_core.messages import AIMessage, HumanMessage
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
from pydantic import BaseModel

import llm
from llm import (
    InvalidStructuredOutputError,
    LLMConfigError,
    LLMUnavailableError,
    Settings,
    Usage,
    ask_structured,
    ask_text,
    call_with_fallback,
    invoke_structured,
    make_model,
    provider_status,
    should_fail_over,
)

SETTINGS = Settings(gemini_api_key="gem-secret", groq_api_key="grq-secret")
REQUEST = httpx.Request("POST", "https://example.test")


def groq_error(cls, status):
    return cls("failed", response=httpx.Response(status, request=REQUEST), body=None)


def wrapped_gemini_error(status):
    """Raise Gemini's error the way LangChain's client does, with the cause attached."""
    cls = genai_errors.ServerError if status >= 500 else genai_errors.ClientError
    original = cls(status, {"error": {"code": status, "message": "failed", "status": "X"}})
    try:
        try:
            raise original
        except genai_errors.APIError as cause:
            raise ChatGoogleGenerativeAIError("Error calling model") from cause
    except ChatGoogleGenerativeAIError as wrapped:
        return wrapped


class Script:
    """A `call` that plays a scripted outcome per provider and records its calls."""

    def __init__(self, gemini=None, groq_outcome=None):
        self.outcomes = {"gemini": gemini, "groq": groq_outcome}
        self.calls = []

    def __call__(self, provider, model):
        self.calls.append(provider)
        outcome = self.outcomes[provider]
        if isinstance(outcome, BaseException):
            raise outcome
        return f"{provider} answer", Usage(10, 5)


@pytest.fixture(autouse=True)
def no_real_models(monkeypatch):
    monkeypatch.setattr(llm, "make_model", lambda provider, settings: object())


@pytest.mark.parametrize(
    "error",
    [
        wrapped_gemini_error(429),
        wrapped_gemini_error(500),
        wrapped_gemini_error(503),
        groq_error(groq.RateLimitError, 429),
        groq_error(groq.InternalServerError, 500),
        groq.APITimeoutError(request=REQUEST),
        groq.APIConnectionError(request=REQUEST),
        httpx.ReadTimeout("slow"),
        httpx.ConnectError("no route"),
        TimeoutError(),
        ChatGoogleGenerativeAIError("Blocked or empty response"),
        InvalidStructuredOutputError("bad json"),
    ],
)
def test_availability_problems_fail_over(error):
    assert should_fail_over(error)


@pytest.mark.parametrize(
    "error",
    [
        wrapped_gemini_error(400),
        wrapped_gemini_error(401),
        wrapped_gemini_error(403),
        wrapped_gemini_error(404),
        groq_error(groq.AuthenticationError, 401),
        groq_error(groq.NotFoundError, 404),
        ValueError("a bug in our code"),
    ],
)
def test_setup_problems_and_bugs_do_not_fail_over(error):
    assert not should_fail_over(error)


class FlakyGemini(Script):
    """Gemini fails with the given errors in turn, then succeeds."""

    def __init__(self, *errors):
        super().__init__()
        self.errors = list(errors)

    def __call__(self, provider, model):
        self.calls.append(provider)
        if provider == "gemini" and self.errors:
            raise self.errors.pop(0)
        return f"{provider} answer", Usage(10, 5)


NO_WAIT = Settings(gemini_api_key="gem-secret", groq_api_key="grq-secret", retry_delay=0, groq_rate_limit_delay=0)


def test_gemini_503_is_retried_once_before_failing_over():
    script = FlakyGemini(wrapped_gemini_error(503))
    result = call_with_fallback(script, NO_WAIT)
    assert script.calls == ["gemini", "gemini"]
    assert result.provider == "gemini" and not result.fell_back


def test_repeated_gemini_503_moves_to_groq():
    script = FlakyGemini(wrapped_gemini_error(503), wrapped_gemini_error(503))
    assert call_with_fallback(script, NO_WAIT).provider == "groq"
    assert script.calls == ["gemini", "gemini", "groq"]


def test_gemini_rate_limit_is_not_retried():
    script = FlakyGemini(wrapped_gemini_error(429))
    call_with_fallback(script, NO_WAIT)
    assert script.calls == ["gemini", "groq"]


def failed_generation():
    message = "Error code: 400 - {'error': {'code': 'json_validate_failed', 'failed_generation': ''}}"
    return groq.BadRequestError(message, response=httpx.Response(400, request=REQUEST), body=None)


def test_groq_generation_failure_is_not_blamed_on_the_api_key():
    # Groq reports these as 400s, but the key and model are fine.
    script = Script(gemini=wrapped_gemini_error(429), groq_outcome=failed_generation())
    with pytest.raises(LLMUnavailableError):
        call_with_fallback(script, NO_WAIT)


class FlakyGroq(Script):
    """Groq fails with the given errors in turn, then succeeds."""

    def __init__(self, *errors):
        super().__init__(gemini=wrapped_gemini_error(429))
        self.errors = list(errors)

    def __call__(self, provider, model):
        self.calls.append(provider)
        if provider == "gemini":
            raise self.outcomes["gemini"]
        if self.errors:
            raise self.errors.pop(0)
        return "groq answer", Usage(10, 5)


def test_groq_generation_failure_is_retried_once():
    # Seen live on ORCL: Gemini overloaded, then Groq failing once, left no summary at all.
    script = FlakyGroq(failed_generation())
    result = call_with_fallback(script, NO_WAIT)
    assert script.calls == ["gemini", "groq", "groq"]
    assert result.provider == "groq" and result.fell_back


def test_repeated_groq_generation_failure_is_reported_as_unavailable():
    script = FlakyGroq(failed_generation(), failed_generation())
    with pytest.raises(LLMUnavailableError):
        call_with_fallback(script, NO_WAIT)
    assert script.calls == ["gemini", "groq", "groq"]


def test_groq_rate_limit_is_retried_once_after_a_wait():
    # Seen live on DIS: blocked by about a second, after an earlier chat in the same minute.
    script = FlakyGroq(groq_error(groq.RateLimitError, 429))
    result = call_with_fallback(script, NO_WAIT)
    assert script.calls == ["gemini", "groq", "groq"]
    assert result.provider == "groq"


def test_repeated_groq_rate_limit_is_reported_as_unavailable():
    script = FlakyGroq(groq_error(groq.RateLimitError, 429), groq_error(groq.RateLimitError, 429))
    with pytest.raises(LLMUnavailableError):
        call_with_fallback(script, NO_WAIT)
    assert script.calls == ["gemini", "groq", "groq"]


def test_real_groq_client_uses_low_reasoning_effort():
    assert llm.Settings().groq_reasoning_effort == "low"


def test_uses_gemini_when_healthy():
    script = Script()
    result = call_with_fallback(script, SETTINGS)
    assert script.calls == ["gemini"]
    assert (result.provider, result.fell_back, result.fallback_reason) == ("gemini", False, None)
    assert result.value == "gemini answer"
    assert result.usage.total_tokens == 15


def test_rate_limit_moves_to_groq_and_reports_why():
    script = Script(gemini=wrapped_gemini_error(429))
    result = call_with_fallback(script, SETTINGS)
    assert script.calls == ["gemini", "groq"]
    assert result.provider == "groq"
    assert result.model == SETTINGS.groq_model
    assert result.fell_back
    assert "Error calling model" in result.fallback_reason


def test_invalid_gemini_key_stops_instead_of_silently_using_groq():
    script = Script(gemini=wrapped_gemini_error(401))
    with pytest.raises(LLMConfigError, match="gemini rejected"):
        call_with_fallback(script, SETTINGS)
    assert script.calls == ["gemini"]


def test_force_failover_skips_gemini_and_needs_no_gemini_key():
    script = Script()
    settings = Settings(groq_api_key="k", force_failover=True)
    result = call_with_fallback(script, settings)
    assert script.calls == ["groq"]
    assert result.fell_back
    assert result.fallback_reason == "FORCE_LLM_FAILOVER is on"


def test_both_providers_failing_reports_both():
    script = Script(
        gemini=wrapped_gemini_error(503),
        groq_outcome=groq_error(groq.RateLimitError, 429),
    )
    with pytest.raises(LLMUnavailableError) as caught:
        call_with_fallback(script, SETTINGS)
    assert "Gemini:" in str(caught.value) and "Groq:" in str(caught.value)


def test_missing_gemini_key_is_a_clear_error():
    with pytest.raises(LLMConfigError, match="GEMINI_API_KEY"):
        call_with_fallback(Script(), Settings(groq_api_key="k"))


def test_missing_groq_key_during_outage_is_a_clear_error():
    script = Script(gemini=wrapped_gemini_error(503))
    with pytest.raises(LLMUnavailableError, match="GROQ_API_KEY"):
        call_with_fallback(script, Settings(gemini_api_key="k"))


def test_force_failover_without_groq_key_is_a_clear_error():
    with pytest.raises(LLMConfigError, match="GROQ_API_KEY"):
        call_with_fallback(Script(), Settings(gemini_api_key="k", force_failover=True))


def test_bugs_in_our_code_surface_unchanged():
    with pytest.raises(ValueError, match="our code"):
        call_with_fallback(Script(gemini=ValueError("our code")), SETTINGS)


def test_keys_are_removed_from_reported_errors():
    script = Script(gemini=TimeoutError("timed out using gem-secret and key=abc123"))
    result = call_with_fallback(script, SETTINGS)
    assert "gem-secret" not in result.fallback_reason
    assert "abc123" not in result.fallback_reason


def test_each_provider_can_receive_different_input(monkeypatch):
    seen = {}

    class Model:
        def __init__(self, provider):
            self.provider = provider

        def invoke(self, messages):
            seen[self.provider] = messages[0].content
            if self.provider == "gemini":
                raise TimeoutError()
            return AIMessage(content="ok")

    monkeypatch.setattr(llm, "make_model", lambda provider, settings: Model(provider))
    size = {"gemini": "full", "groq": "reduced"}
    ask_text(lambda provider: [HumanMessage(content=size[provider])], SETTINGS)
    assert seen == {"gemini": "full", "groq": "reduced"}


class Answer(BaseModel):
    text: str


class StructuredModel:
    """Stands in for a chat model, returning a preset `include_raw` result."""

    def __init__(self, reply):
        self.reply = reply
        self.options = None

    def with_structured_output(self, schema, **options):
        self.options = options
        return self

    def invoke(self, messages):
        return self.reply


def test_unparsable_structured_output_moves_to_groq(monkeypatch):
    models = {
        "gemini": StructuredModel({"raw": AIMessage(content="x"), "parsed": None, "parsing_error": "bad"}),
        "groq": StructuredModel({"raw": AIMessage(content="y"), "parsed": Answer(text="ok"), "parsing_error": None}),
    }
    monkeypatch.setattr(llm, "make_model", lambda provider, settings: models[provider])
    result = ask_structured(Answer, [HumanMessage(content="q")], SETTINGS)
    assert result.provider == "groq"
    assert result.value.text == "ok"


def test_groq_structured_output_is_strict():
    model = StructuredModel({"raw": AIMessage(content="y"), "parsed": Answer(text="ok")})
    invoke_structured("groq", model, Answer, [HumanMessage(content="q")])
    assert model.options == {"method": "json_schema", "include_raw": True, "strict": True}


def test_usage_is_read_from_the_raw_reply():
    raw = AIMessage(
        content="y",
        usage_metadata={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
    )
    model = StructuredModel({"raw": raw, "parsed": Answer(text="ok")})
    _, usage = invoke_structured("gemini", model, Answer, [HumanMessage(content="q")])
    assert usage == Usage(7, 3)


def test_status_never_includes_keys():
    status = provider_status(SETTINGS)
    assert status["providers"]["gemini"]["configured"] is True
    assert "gem-secret" not in str(status) and "grq-secret" not in str(status)


def test_real_clients_are_built_with_failover_settings(monkeypatch):
    monkeypatch.undo()  # Use the real make_model, without making any network call.
    gemini = make_model("gemini", SETTINGS)
    assert gemini.max_retries == 0
    assert gemini.timeout == 30
    grq = make_model("groq", SETTINGS)
    assert grq.max_retries == 1
    assert grq.request_timeout == 30
