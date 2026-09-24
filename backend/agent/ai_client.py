"""AI client adapter layer for SpecAlive Phase 1.

Provides a provider-agnostic wrapper around AI LLM APIs.
Provider-specific code is isolated here.

Supported providers:
    openai
    gemini
    groq
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# AI ERRORS
# ============================================================

class AIClientError(Exception):
    """Raised when an AI API call fails unexpectedly."""
    pass


class AIAuthenticationError(AIClientError):
    """Raised when the API key is missing or rejected."""
    pass


class AIResponseError(AIClientError):
    """Raised when the AI returns an empty or invalid response."""
    pass


class AIRateLimitError(AIClientError):
    """Raised when the AI provider returns a rate-limit error."""

    def __init__(
        self,
        message: str,
        *,
        retry_delay: Optional[int] = None,
        quota_metric: Optional[str] = None,
        quota_id: Optional[str] = None,
        quota_limit: Optional[str] = None,
        quota_location: Optional[str] = None,
        quota_description: Optional[str] = None,
    ):
        super().__init__(message)

        self.retry_delay = retry_delay
        self.quota_metric = quota_metric
        self.quota_id = quota_id
        self.quota_limit = quota_limit
        self.quota_location = quota_location
        self.quota_description = quota_description


# ============================================================
# MESSAGE
# ============================================================

class Message:
    """Lightweight message container for LLM conversations."""

    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content

    def to_dict(self) -> Dict[str, str]:
        return {
            "role": self.role,
            "content": self.content,
        }


# ============================================================
# BASE AI CLIENT
# ============================================================

class BaseAIClient(ABC):
    """Abstract interface for all AI provider clients."""

    @abstractmethod
    def complete(
        self,
        messages: List[Message],
        temperature: float = 0.0,
        timeout: int = 60,
        max_tokens: int = 8192,
        json_mode: bool = False,
    ) -> str:
        """Send messages and return the AI response."""
        pass


# ============================================================
# OPENAI CLIENT
# ============================================================

class OpenAIClient(BaseAIClient):
    """OpenAI API client adapter."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: Optional[str] = None,
    ):
        if not api_key:
            raise AIAuthenticationError(
                "OpenAI API key is not set. "
                "Please configure LLM_API_KEY in .env"
            )

        self._model = model

        try:
            import openai

            self._client = openai.OpenAI(
                api_key=api_key,
                base_url=base_url or None,
            )

        except ImportError:
            raise AIClientError(
                "openai package is not installed. "
                "Run: pip install openai"
            )

    def complete(
        self,
        messages: List[Message],
        temperature: float = 0.0,
        timeout: int = 60,
        max_tokens: int = 8192,
        json_mode: bool = False,
    ) -> str:

        kwargs = {}

        if json_mode:
            kwargs["response_format"] = {
                "type": "json_object"
            }

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    message.to_dict()
                    for message in messages
                ],
                temperature=temperature,
                timeout=timeout,
                max_tokens=max_tokens,
                **kwargs,
            )

            content = response.choices[0].message.content

            if not content:
                raise AIResponseError(
                    "OpenAI returned an empty response."
                )

            return content

        except AIResponseError:
            raise

        except Exception as exc:
            error_text = str(exc).lower()

            if (
                "authentication" in error_text
                or "api_key" in error_text
                or "api key" in error_text
                or "401" in error_text
                or "403" in error_text
            ):
                raise AIAuthenticationError(
                    f"OpenAI authentication error: "
                    f"{type(exc).__name__}"
                ) from exc

            if (
                "429" in error_text
                or "rate limit" in error_text
                or "quota" in error_text
            ):
                raise AIRateLimitError(
                    f"OpenAI rate limit reached: "
                    f"{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc

            raise AIClientError(
                f"OpenAI request failed: "
                f"{type(exc).__name__}: {str(exc)[:300]}"
            ) from exc


# ============================================================
# GEMINI CLIENT
# ============================================================

class GeminiClient(BaseAIClient):
    """Google Gemini API client adapter."""

    def __init__(
        self,
        api_key: str,
        model: str,
    ):
        if not api_key:
            raise AIAuthenticationError(
                "Gemini API key is not set. "
                "Please configure LLM_API_KEY in .env"
            )

        self._model = model

        try:
            import google.generativeai as genai

            genai.configure(api_key=api_key)

            self._client = genai.GenerativeModel(
                model
            )

        except ImportError:
            raise AIClientError(
                "google-generativeai package is not installed. "
                "Run: pip install google-generativeai"
            )

    def complete(
        self,
        messages: List[Message],
        temperature: float = 0.0,
        timeout: int = 60,
        max_tokens: int = 8192,
        json_mode: bool = False,
    ) -> str:

        import google.generativeai as genai

        system_messages = [
            message.content
            for message in messages
            if message.role == "system"
        ]

        system_instruction = (
            "\n\n".join(system_messages)
            if system_messages
            else None
        )

        user_messages = [
            message.content
            for message in messages
            if message.role != "system"
        ]

        combined_message = "\n\n".join(user_messages)

        if system_instruction:
            model = genai.GenerativeModel(
                model_name=self._model,
                system_instruction=system_instruction,
            )
        else:
            model = self._client

        generation_config = genai.types.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        if json_mode:
            generation_config.response_mime_type = (
                "application/json"
            )

        try:
            response = model.generate_content(
                combined_message,
                generation_config=generation_config,
            )

            content = response.text

            if not content:
                raise AIResponseError(
                    "Gemini returned an empty response."
                )

            return content

        except AIResponseError:
            raise

        except Exception as exc:
            error_text = str(exc).lower()

            if (
                "429" in error_text
                or "rate limit" in error_text
                or "quota" in error_text
            ):
                raise AIRateLimitError(
                    f"Gemini rate limit reached: "
                    f"{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc

            if (
                "authentication" in error_text
                or "permission" in error_text
                or "api key" in error_text
            ):
                raise AIAuthenticationError(
                    f"Gemini authentication error: "
                    f"{type(exc).__name__}"
                ) from exc

            raise AIClientError(
                f"Gemini request failed: "
                f"{type(exc).__name__}: {str(exc)[:300]}"
            ) from exc


# ============================================================
# GROQ CLIENT
# ============================================================

class GroqClient(BaseAIClient):
    """Groq API client adapter."""

    def __init__(
        self,
        api_key: str,
        model: str,
    ):
        if not api_key:
            raise AIAuthenticationError(
                "Groq API key is not set. "
                "Please configure LLM_API_KEY in .env"
            )

        self._model = model

        try:
            from groq import Groq

            self._client = Groq(
                api_key=api_key
            )

        except ImportError:
            raise AIClientError(
                "groq package is not installed. "
                "Run: pip install groq"
            )

    def complete(
        self,
        messages: List[Message],
        temperature: float = 0.0,
        timeout: int = 60,
        max_tokens: int = 8192,
        json_mode: bool = False,
    ) -> str:

        kwargs = {}

        if json_mode:
            kwargs["response_format"] = {
                "type": "json_object"
            }

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    message.to_dict()
                    for message in messages
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                **kwargs,
            )

            content = response.choices[0].message.content

            if not content:
                raise AIResponseError(
                    "Groq returned an empty response."
                )

            return content

        except AIResponseError:
            raise

        except Exception as exc:
            error_text = str(exc).lower()

            if (
                "authentication" in error_text
                or "api key" in error_text
                or "401" in error_text
                or "403" in error_text
            ):
                raise AIAuthenticationError(
                    f"Groq authentication error: "
                    f"{type(exc).__name__}"
                ) from exc

            if (
                "429" in error_text
                or "rate limit" in error_text
                or "quota" in error_text
            ):
                raise AIRateLimitError(
                    f"Groq rate limit reached: "
                    f"{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc

            raise AIClientError(
                f"Groq request failed: "
                f"{type(exc).__name__}: {str(exc)[:300]}"
            ) from exc


# ============================================================
# STEP 4.3 — PROVIDER FACTORY
# ============================================================

def build_client(
    provider: str,
    api_key: str,
    model: str,
    base_url: Optional[str] = None,
) -> BaseAIClient:
    """Create the correct AI client from provider configuration."""

    provider_name = (
        provider or ""
    ).strip().lower()

    if provider_name == "openai":
        return OpenAIClient(
            api_key=api_key,
            model=model,
            base_url=base_url,
        )

    if provider_name == "gemini":
        return GeminiClient(
            api_key=api_key,
            model=model,
        )

    if provider_name == "groq":
        return GroqClient(
            api_key=api_key,
            model=model,
        )

    raise AIClientError(
        f"Unsupported AI provider: '{provider_name}'. "
        f"Supported providers: openai, gemini, groq"
    )