"""
Configuration and path settings 

Provides environment variable loading via python-dotenv, safe configuration
validation, provider-agnostic AI settings, and secret masking to prevent
accidental leaks in logs or console output.
"""

import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv


# Base project paths

BASE_DIR = Path(__file__).resolve().parent.parent

BACKEND_DIR = BASE_DIR / "backend"

INPUT_DIR = BASE_DIR / "input"

OUTPUT_DIR = BASE_DIR / "output"

OUTPUT_STRUCTURED_DIR = OUTPUT_DIR / "structured"

OUTPUT_SYSML_DIR = OUTPUT_DIR / "sysml"

OUTPUT_MODELICA_DIR = OUTPUT_DIR / "modelica"

OUTPUT_RAW_RESPONSES_DIR = OUTPUT_DIR / "raw_responses"

OUTPUT_VALIDATION_ERRORS_DIR = OUTPUT_DIR / "validation_errors"

SCHEMA_DIR = BACKEND_DIR / "schema"

SYSTEM_SCHEMA_PATH = SCHEMA_DIR / "system_schema.json"

DEFAULT_SPEC_PATH = INPUT_DIR / "specification.txt"


# Environment file

ENV_FILE = BASE_DIR / ".env"

if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=False)


# Supported AI Providers

class SupportedProvider(str, Enum):
    """Supported AI model providers."""

    OPENAI = "openai"
    GEMINI = "gemini"
    GROQ = "groq"

    @classmethod
    def list_values(cls) -> List[str]:
        """Return provider names as strings."""
        return [provider.value for provider in cls]


# Secret masking

def mask_secret(secret: Optional[str]) -> str:
    """
    Safely mask a secret string so it can be logged without exposure.

    Examples:
        None or "" -> "<not set>"
        "sk-123456789abcdef" -> "sk-1...cdef"
        "short" -> "***"
    """

    if not secret:
        return "<not set>"

    if len(secret) <= 8:
        return "***"

    return f"{secret[:4]}...{secret[-4:]}"


# AI Configuration

class AIConfig:
    """Isolated, provider-agnostic configuration for AI models."""

    def __init__(
        self,
        provider: str = "openai",
        api_key: Optional[str] = None,
        model: str = "gpt-4o",
        base_url: Optional[str] = None,
        temperature: float = 0.0,
        timeout: int = 60,
    ):
        self.provider = (provider or "openai").strip().lower()

        self.api_key = (api_key or "").strip()

        self.model = (model or "").strip()

        self.base_url = (base_url or "").strip() or None

        self.temperature = float(temperature)

        self.timeout = int(timeout)

    @property
    def has_api_key(self) -> bool:
        """Indicates whether an API key has been provided."""
        return bool(self.api_key)

    def safe_dict(self) -> Dict[str, Any]:
        """
        Return configuration dictionary with secrets masked
        for safe logging.
        """

        return {
            "provider": self.provider,
            "model": self.model,
            "has_api_key": self.has_api_key,
            "api_key_masked": mask_secret(self.api_key),
            "base_url": self.base_url or "<default>",
            "temperature": self.temperature,
            "timeout": self.timeout,
        }

    def __repr__(self) -> str:
        """Return a safe representation without exposing the API key."""

        masked = mask_secret(self.api_key)

        return (
            f"AIConfig("
            f"provider='{self.provider}', "
            f"model='{self.model}', "
            f"api_key='{masked}', "
            f"temperature={self.temperature}, "
            f"timeout={self.timeout}"
            f")"
        )

    def validate(
        self,
        require_api_key: bool = False,
    ) -> Tuple[bool, List[str]]:
        """
        Validate AI configuration values safely.

        Args:
            require_api_key:
                If True, a missing API key is treated as an error.
                If False, a missing API key is returned as a warning.
        """

        errors: List[str] = []

        warnings: List[str] = []

        # Validate provider

        if self.provider not in SupportedProvider.list_values():
            errors.append(
                f"Unsupported provider '{self.provider}'. "
                f"Supported providers: "
                f"{SupportedProvider.list_values()}"
            )

        # Validate model

        if not self.model:
            errors.append("Model name cannot be empty.")

        # Validate temperature

        if not (0.0 <= self.temperature <= 2.0):
            errors.append(
                "Temperature must be between 0.0 and 2.0 "
                f"(got {self.temperature})."
            )

        # Validate timeout

        if self.timeout <= 0:
            errors.append(
                "Timeout must be a positive integer "
                f"(got {self.timeout})."
            )

        # Validate API key

        if not self.has_api_key:
            message = (
                f"API key for provider '{self.provider}' "
                "is not set."
            )

            if require_api_key:
                errors.append(message)
            else:
                warnings.append(message)

        # Final result

        is_valid = len(errors) == 0

        return is_valid, errors + warnings


# Application Configuration

class AppConfig:
    """
    Top-level application configuration containing
    project paths and AI settings.
    """

    def __init__(self):

        # Project paths

        self.base_dir = BASE_DIR

        self.input_dir = INPUT_DIR

        self.output_dir = OUTPUT_DIR

        self.output_structured_dir = OUTPUT_STRUCTURED_DIR

        self.output_sysml_dir = OUTPUT_SYSML_DIR

        self.output_modelica_dir = OUTPUT_MODELICA_DIR

        self.output_raw_responses_dir = (
            OUTPUT_RAW_RESPONSES_DIR
        )

        self.output_validation_errors_dir = (
            OUTPUT_VALIDATION_ERRORS_DIR
        )

        self.system_schema_path = SYSTEM_SCHEMA_PATH

        self.default_spec_path = DEFAULT_SPEC_PATH

        # AI configuration from environment variables

        self.ai = AIConfig(
            provider=os.getenv(
                "LLM_PROVIDER",
                "openai",
            ),
            api_key=os.getenv(
                "LLM_API_KEY",
                "",
            ),
            model=os.getenv(
                "LLM_MODEL",
                "gpt-4o",
            ),
            base_url=os.getenv(
                "LLM_BASE_URL",
                None,
            ),
            temperature=float(
                os.getenv(
                    "LLM_TEMPERATURE",
                    "0.0",
                )
            ),
            timeout=int(
                os.getenv(
                    "LLM_TIMEOUT",
                    "60",
                )
            ),
        )

    # Configuration validation

    def validate(
        self,
        require_api_key: bool = False,
    ) -> Tuple[bool, List[str]]:
        """Validate application settings and AI configuration."""

        errors: List[str] = []

        # Validate schema path

        if not self.system_schema_path.exists():
            errors.append(
                f"System schema file not found at "
                f"{self.system_schema_path}"
            )

        # Validate AI configuration

        ai_valid, ai_messages = self.ai.validate(
            require_api_key=require_api_key
        )

        if not ai_valid:
            errors.extend(ai_messages)

        return len(errors) == 0, errors

    # Directory creation

    def ensure_directories(self) -> None:
        """Create standard project directories if needed."""

        self.input_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.output_structured_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.output_sysml_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.output_modelica_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.output_raw_responses_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.output_validation_errors_dir.mkdir(
            parents=True,
            exist_ok=True,
        )


# ============================================================
# Global configuration instance
# ============================================================

config = AppConfig()


# Backwards-compatible convenience exports

LLM_PROVIDER = config.ai.provider

LLM_API_KEY = config.ai.api_key

LLM_MODEL = config.ai.model

LLM_BASE_URL = config.ai.base_url

LLM_TEMPERATURE = config.ai.temperature

LLM_TIMEOUT = config.ai.timeout