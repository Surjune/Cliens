"""Tests for the Gemini client and the version-controlled prompt.

The prompt is the safety mechanism here: the model must not be able to introduce a
figure the engine did not compute. Those constraints are asserted directly, because
a prompt edit that dropped them would otherwise pass silently.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.core import constants
from app.core.config import Settings
from app.core.exceptions import ExternalServiceError, ExternalServiceUnconfiguredError
from app.external.gemini import API_BASE_URL, GeminiClient
from app.external.prompts import PROMPT_VERSION, build_report_prompt

MODEL = "gemini-2.0-flash"
ENDPOINT = f"{API_BASE_URL}/models/{MODEL}:generateContent"


@pytest.fixture
def configured(settings: Settings) -> Settings:
    """Settings with a Gemini key present."""
    return settings.model_copy(update={"gemini_api_key": "test-key", "gemini_model": MODEL})


@pytest.fixture(autouse=True)
def _no_backoff_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove retry backoff so failure-path tests do not sleep."""
    monkeypatch.setattr(constants, "EXTERNAL_RETRY_INITIAL_BACKOFF_SECONDS", 0.0)
    monkeypatch.setattr(constants, "EXTERNAL_RETRY_MAX_BACKOFF_SECONDS", 0.0)


def reply(text: str) -> httpx.Response:
    """A well-formed Gemini response."""
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


class TestCredentialGuard:
    """No key means an explicit error, never a fabricated report."""

    async def test_unconfigured_raises(self, settings: Settings) -> None:
        with pytest.raises(ExternalServiceUnconfiguredError) as caught:
            await GeminiClient(settings).generate("anything")

        assert caught.value.http_status == 503
        assert caught.value.details["missing"] == ["GEMINI_API_KEY"]

    def test_reports_configured_when_a_key_is_present(self, configured: Settings) -> None:
        assert GeminiClient(configured).is_configured is True


class TestGeneration:
    """The happy path and how the request is formed."""

    @respx.mock
    async def test_returns_the_generated_text(self, configured: Settings) -> None:
        respx.post(ENDPOINT).mock(return_value=reply("## What we found\nA report."))

        result = await GeminiClient(configured).generate("prompt")

        assert result.startswith("## What we found")

    @respx.mock
    async def test_sends_the_key_as_a_header_not_a_query_parameter(
        self, configured: Settings
    ) -> None:
        """Query strings land in access logs and proxy caches; headers do not."""
        route = respx.post(ENDPOINT).mock(return_value=reply("text"))

        await GeminiClient(configured).generate("prompt")

        request = route.calls.last.request
        assert request.headers["x-goog-api-key"] == "test-key"
        assert "test-key" not in str(request.url)

    @respx.mock
    async def test_requests_deterministic_output(self, configured: Settings) -> None:
        """A report that reworded itself on refresh would undermine the numbers."""
        route = respx.post(ENDPOINT).mock(return_value=reply("text"))

        await GeminiClient(configured).generate("prompt")

        import json

        body = json.loads(route.calls.last.request.content)
        assert body["generationConfig"]["temperature"] == 0.0

    @respx.mock
    async def test_joins_multi_part_responses(self, configured: Settings) -> None:
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": "A"}, {"text": "B"}]}}]},
            )
        )

        assert await GeminiClient(configured).generate("prompt") == "AB"


class TestFailureModes:
    """An empty or blocked response must not become an empty report."""

    @respx.mock
    async def test_no_candidates_raises(self, configured: Settings) -> None:
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})
        )

        with pytest.raises(ExternalServiceError) as caught:
            await GeminiClient(configured).generate("prompt")

        assert caught.value.details["block_reason"] == "SAFETY"

    @respx.mock
    async def test_empty_text_raises(self, configured: Settings) -> None:
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200, json={"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]}
            )
        )

        with pytest.raises(ExternalServiceError, match="empty report"):
            await GeminiClient(configured).generate("prompt")

    @respx.mock
    async def test_upstream_error_maps_to_a_typed_error(self, configured: Settings) -> None:
        respx.post(ENDPOINT).mock(return_value=httpx.Response(429))

        with pytest.raises(ExternalServiceError) as caught:
            await GeminiClient(configured).generate("prompt")

        assert caught.value.service == "gemini"


class TestPromptSafety:
    """The prompt is the guard against invented figures."""

    def test_version_is_recorded(self) -> None:
        assert PROMPT_VERSION == "v1"

    def test_forbids_introducing_numbers(self) -> None:
        prompt = build_report_prompt({"crossing_year": 2041})
        assert "Never introduce a number" in prompt

    def test_forbids_estimating_missing_values(self) -> None:
        prompt = build_report_prompt({"crossing_year": None})
        assert "Never estimate it" in prompt

    def test_requires_stating_uncertainty(self) -> None:
        prompt = build_report_prompt({})
        assert "uncertainty" in prompt.lower()

    def test_forbids_financial_and_insurance_advice(self) -> None:
        prompt = build_report_prompt({})
        assert "Do not give legal, financial or insurance advice" in prompt

    def test_embeds_the_supplied_data(self) -> None:
        """The model must see the real figures, not a paraphrase of them."""
        prompt = build_report_prompt({"crossing_year": 2041, "confidence": "moderate"})
        assert "2041" in prompt
        assert "moderate" in prompt

    def test_requires_the_limitations_section(self) -> None:
        """A report without stated limits would overstate what this product knows."""
        assert "What this does not tell you" in build_report_prompt({})
