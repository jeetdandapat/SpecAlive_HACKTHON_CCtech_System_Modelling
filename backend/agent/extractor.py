

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from backend.agent.ai_client import (
    AIClientError,
    AIAuthenticationError,
    BaseAIClient,
    Message,
    build_client,
)

from backend.agent.prompts import (
    EXTRACTION_SYSTEM_PROMPT,
    USER_SPEC_PROMPT_TEMPLATE,
    PROMPT_VERSION,
    format_extraction_prompts,
)

from backend.config import config
from backend.inputs.base import SpecificationDocument
from backend.validators.structured_validator import (
    StructuredValidator,
    ValidationStatus,
)


logger = logging.getLogger(__name__)


# Extraction Errors

class ExtractionError(Exception):
    """Raised when AI extraction fails."""

    pass


class ExtractionValidationError(ExtractionError):
    """
    Raised when AI output is parsed but fails structured validation.

    Contains the ValidationResult for downstream inspection.
    """

    def __init__(
        self,
        message: str,
        validation_result: Any,
        raw_ir: Dict[str, Any],
    ):
        super().__init__(message)
        self.validation_result = validation_result
        self.raw_ir = raw_ir


# Extraction Result

class ExtractionResult:
    """Container for the complete extraction output."""

    def __init__(
        self,
        ir: Dict[str, Any],
        raw_response: str,
        validation_result: Any,
        spec_doc: SpecificationDocument,
        provider: str,
        model: str,
        timestamp: datetime,
        prompt_version: str = PROMPT_VERSION,
    ):
        self.ir = ir
        self.raw_response = raw_response
        self.validation_result = validation_result
        self.spec_doc = spec_doc
        self.provider = provider
        self.model = model
        self.timestamp = timestamp
        self.prompt_version = prompt_version

    def save(
        self,
        structured_dir: Optional[Path] = None,
        raw_dir: Optional[Path] = None,
    ) -> Dict[str, Path]:
        """
        Persist IR and raw response to output directories.

        Returns:
            Dictionary containing paths for:
            - structured
            - raw_response
        """

        structured_dir = (
            structured_dir
            or config.output_structured_dir
        )

        raw_dir = (
            raw_dir
            or config.output_dir / "raw_responses"
        )

        structured_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        raw_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        timestamp = self.timestamp.strftime(
            "%Y%m%dT%H%M%SZ"
        )

        system_name = self.ir.get(
            "system_name",
            "UnknownSystem",
        )

        base = f"{system_name}_{timestamp}"

        # Save validated structured IR

        ir_path = structured_dir / f"{base}.json"

        with open(
            ir_path,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                self.ir,
                file,
                indent=2,
                ensure_ascii=False,
            )

        # Save raw AI response

        raw_path = raw_dir / f"{base}_raw.txt"

        with open(
            raw_path,
            "w",
            encoding="utf-8",
        ) as file:
            file.write(
                "# SpecAlive Raw AI Response\n"
            )

            file.write(
                f"# Provider: "
                f"{self.provider} / "
                f"Model: {self.model}\n"
            )

            file.write(
                f"# Prompt Version: "
                f"{self.prompt_version}\n"
            )

            file.write(
                f"# Timestamp: "
                f"{self.timestamp.isoformat()}\n"
            )

            file.write(
                f"# Source: "
                f"{self.spec_doc.file_name} "
                f"(sha256: "
                f"{self.spec_doc.sha256[:16]}...)\n"
            )

            file.write(
                "# NOTE: This file contains only "
                "AI model output. "
                "No API keys are stored.\n\n"
            )

            file.write(self.raw_response)

        logger.info(
            f"Saved IR -> {ir_path}"
        )

        logger.info(
            f"Saved raw response -> {raw_path}"
        )

        return {
            "structured": ir_path,
            "raw_response": raw_path,
        }


# JSON Utility

def _strip_json_fences(text: str) -> str:
    """
    Remove markdown code fences that some models
    wrap around JSON.
    """

    text = text.strip()

    match = re.search(
        r"```(?:json)?\s*([\s\S]*?)```",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).strip()

    return text


# Specification Extractor

class SpecificationExtractor:
    """
    Orchestrates AI extraction of structured IR
    from engineering specifications.

    Architecture:
    - Uses BaseAIClient for provider-independent AI communication.
    - Provider client is created through build_client().
    - Raw AI response is preserved for debugging.
    - Output is always passed through StructuredValidator.
    - AI client and validation remain separate.
    """

    def __init__(
        self,
        client: Optional[BaseAIClient] = None,
        validator: Optional[StructuredValidator] = None,
        prompt_version: Optional[str] = None,
    ):
        """
        Initialize the extractor.

        Args:
            client:
                Injected AI client for testing.
                If None, the client is built from config.

            validator:
                Injected validator for testing.
                If None, StructuredValidator is used.

            prompt_version:
                Optional prompt version override.
        """

        self._client = client

        self._validator = (
            validator
            or StructuredValidator(
                config.system_schema_path
            )
        )

        self._prompt_version = (
            prompt_version
            or PROMPT_VERSION
        )

    # AI Client

    def _get_client(self) -> BaseAIClient:
        """
        Return the configured AI client.

        The API key is never exposed in logs.
        """

        if self._client is None:

            self._client = build_client(
                provider=config.ai.provider,
                api_key=config.ai.api_key,
                model=config.ai.model,
                base_url=config.ai.base_url,
            )

        return self._client

    # AI Extraction Call

    def _call_ai(
        self,
        specification_text: str,
    ) -> str:
        """
        Send the engineering specification to the AI.

        Returns:
            Raw AI text response.

        Raises:
            ExtractionError:
                If the API request fails or the response is empty.
        """

        system_prompt, user_prompt = (
            format_extraction_prompts(
                specification_text=specification_text,
                version=self._prompt_version,
            )
        )

        messages = [
            Message(
                role="system",
                content=system_prompt,
            ),
            Message(
                role="user",
                content=user_prompt,
            ),
        ]

        logger.info(
            f"Sending extraction request to "
            f"{config.ai.provider}/"
            f"{config.ai.model} "
            f"[prompt_version="
            f"{self._prompt_version}] "
            f"(temp="
            f"{config.ai.temperature}, "
            f"timeout="
            f"{config.ai.timeout}s)"
        )

        try:

            client = self._get_client()

            raw = client.complete(
                messages=messages,
                temperature=config.ai.temperature,
                timeout=config.ai.timeout,
                json_mode=True,
            )

        except AIAuthenticationError as error:

            raise ExtractionError(
                f"AI authentication failed for "
                f"provider "
                f"'{config.ai.provider}'. "
                f"Please set LLM_API_KEY in .env "
                f"and ensure it is valid. "
                f"({type(error).__name__})"
            ) from error

        except AIClientError as error:

            raise ExtractionError(
                f"AI API request failed: {error}"
            ) from error

        if not raw or not raw.strip():

            raise ExtractionError(
                "AI returned an empty response. "
                "Cannot extract structured model."
            )

        return raw

    # JSON Parsing

    def _parse_json(
        self,
        raw_response: str,
    ) -> Dict[str, Any]:
        """
        Parse raw AI text into a JSON dictionary.

        Markdown JSON code fences are removed first.

        Raises:
            ExtractionError:
                If valid JSON cannot be parsed.
        """

        cleaned = _strip_json_fences(
            raw_response
        )

        try:

            parsed = json.loads(cleaned)

            if not isinstance(parsed, dict):
                raise ExtractionError(
                    "AI returned valid JSON, "
                    "but the top-level value "
                    "is not a JSON object."
                )

            return parsed

        except json.JSONDecodeError as error:

            raise ExtractionError(
                f"AI returned malformed JSON "
                f"(line {error.lineno}, "
                f"col {error.colno}): "
                f"{error.msg}. "
                f"First 400 chars of response: "
                f"{cleaned[:400]!r}"
            ) from error

    # Main Extraction Pipeline

    def extract(
        self,
        spec_doc: SpecificationDocument,
    ) -> ExtractionResult:
        """
        Run the complete extraction pipeline.

        Pipeline:

        1. Send specification to AI.
        2. Parse AI response as JSON.
        3. Validate JSON against structured schema.
        4. Reject invalid models.
        5. Return validated ExtractionResult.

        Raises:
            ExtractionError:
                For AI/API or JSON parsing failures.

            ExtractionValidationError:
                If AI output fails structured validation.
        """

        logger.info(
            f"Starting extraction for "
            f"'{spec_doc.file_name}' "
            f"({spec_doc.line_count} lines)"
        )

        # Step 1: AI extraction

        raw_response = self._call_ai(
            spec_doc.raw_text
        )

        logger.info(
            f"Received raw AI response "
            f"({len(raw_response)} chars)"
        )

        # Step 2: Parse JSON

        raw_ir = self._parse_json(
            raw_response
        )

        # Step 3: Structured validation

        validation_result = (
            self._validator.validate(
                raw_ir
            )
        )

        # Step 4: Reject invalid output

        if (
            validation_result.status
            == ValidationStatus.FAIL
        ):

            error_count = len(
                validation_result.all_errors
            )

            logger.warning(
                f"AI output failed validation "
                f"with {error_count} error(s). "
                f"Extraction REJECTED."
            )

            raise ExtractionValidationError(
                (
                    "AI extraction output failed "
                    "structured validation "
                    f"({error_count} error(s)):\n"
                    + validation_result.summary()
                ),
                validation_result=validation_result,
                raw_ir=raw_ir,
            )

        # Step 5: Accept validated IR

        logger.info(
            "Extraction validated successfully: "
            f"PASS "
            f"(missing_info="
            f"{len(validation_result.missing_information)})"
        )

        return ExtractionResult(
            ir=raw_ir,
            raw_response=raw_response,
            validation_result=validation_result,
            spec_doc=spec_doc,
            provider=config.ai.provider,
            model=config.ai.model,
            timestamp=datetime.now(
                timezone.utc
            ),
            prompt_version=self._prompt_version,
        )

    # Convenience Method

    def extract_from_text(
        self,
        text: str,
        source_name: str = "inline",
    ) -> ExtractionResult:
        """
        Extract from a raw text string instead of
        a SpecificationDocument.

        Useful for scripting and testing.
        """

        from backend.inputs.text_reader import (
            TextInputReader,
        )

        reader = TextInputReader()

        spec_doc = reader.read_from_string(
            text,
            source_name=source_name,
        )

        return self.extract(spec_doc)