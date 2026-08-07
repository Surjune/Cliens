"""Google Gemini client for report generation.

Calls the REST API directly through the shared transport in ``http.py`` rather than
pulling in an SDK: the surface used here is one endpoint, and going through the
shared policy means this call gets the same timeouts, retries and correlation-ID
propagation as every other outbound request.

Generation is configured at temperature 0. The rest of the product is
deterministic, and a report that reworded itself on every refresh would undermine
confidence in the numbers it describes.
"""

from __future__ import annotations

from typing import Any

from app.core import constants
from app.core.config import Settings
from app.core.exceptions import ExternalServiceError, ExternalServiceUnconfiguredError
from app.core.logging import get_logger
from app.external.http import request_json

logger = get_logger(__name__)

SERVICE_NAME = "gemini"
API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiClient:
    """Generates plain-English text from a prompt."""

    def __init__(self, settings: Settings) -> None:
        """Bind the client to configuration."""
        self._settings = settings

    @property
    def is_configured(self) -> bool:
        """Whether an API key is present."""
        return self._settings.gemini_configured

    @property
    def model_name(self) -> str:
        """The configured model, recorded on every generated report."""
        return self._settings.gemini_model

    async def generate(self, prompt: str) -> str:
        """Generate text for a prompt.

        Args:
            prompt: The full prompt, built by ``external.prompts``.

        Returns:
            The generated text.

        Raises:
            ExternalServiceUnconfiguredError: If no API key is configured.
            ExternalServiceError: If Gemini failed, refused, or returned a
                response without usable text.
        """
        if not self.is_configured:
            raise ExternalServiceUnconfiguredError(
                "Gemini is not configured, so reports cannot be generated. Set "
                "GEMINI_API_KEY — see the README section 'Prerequisites'.",
                service=SERVICE_NAME,
                details={"missing": ["GEMINI_API_KEY"]},
            )

        logger.info("gemini_generation_started", model=self.model_name, prompt_chars=len(prompt))

        payload = await request_json(
            service=SERVICE_NAME,
            method="POST",
            url=f"{API_BASE_URL}/models/{self.model_name}:generateContent",
            timeout_seconds=constants.GEMINI_TIMEOUT_SECONDS,
            # The key goes in a header, not the query string: query strings are
            # routinely written to access logs and proxy caches.
            headers={"x-goog-api-key": self._settings.gemini_api_key or ""},
            json_body={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    # Deterministic output; see the module docstring.
                    "temperature": 0.0,
                    "candidateCount": 1,
                    "maxOutputTokens": constants.GEMINI_MAX_OUTPUT_TOKENS,
                },
            },
        )

        text = self._extract_text(payload)
        logger.info("gemini_generation_succeeded", model=self.model_name, chars=len(text))
        return text

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        """Pull the generated text out of a Gemini response.

        Raises:
            ExternalServiceError: If the response contains no usable text. The most
                common cause is a safety block, which returns a candidate with a
                ``finishReason`` and no content — that must surface as a clear
                error rather than an empty report.
        """
        candidates = payload.get("candidates")
        if not candidates:
            block_reason = payload.get("promptFeedback", {}).get("blockReason")
            raise ExternalServiceError(
                "Gemini returned no candidates for this report.",
                service=SERVICE_NAME,
                details={"block_reason": block_reason} if block_reason else None,
            )

        candidate = candidates[0]
        parts = candidate.get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts).strip()

        if not text:
            raise ExternalServiceError(
                "Gemini returned an empty report.",
                service=SERVICE_NAME,
                details={"finish_reason": candidate.get("finishReason")},
            )
        return text
