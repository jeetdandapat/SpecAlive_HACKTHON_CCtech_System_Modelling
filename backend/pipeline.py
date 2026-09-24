
import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from backend.agent.ai_client import BaseAIClient, build_client
from backend.agent.extractor import (
    ExtractionError,
    ExtractionResult,
    ExtractionValidationError,
    SpecificationExtractor,
)
from backend.agent.prompts import PROMPT_VERSION
from backend.config import config
from backend.inputs.base import (
    InputError,
    SpecificationDocument,
    SpecificationEmptyError,
    SpecificationNotFoundError,
)
from backend.inputs.text_reader import load_specification
from backend.validators.structured_validator import (
    StructuredValidator,
    ValidationResult,
)


logger = logging.getLogger("spec_alive.pipeline")


class PipelineStatus(str):
    """Overall pipeline execution status."""

    SUCCESS = "SUCCESS"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    INPUT_ERROR = "INPUT_ERROR"


@dataclass
class PipelineResult:
    """Result returned by the SpecAlive processing pipeline."""

    status: str

    spec_doc: Optional[SpecificationDocument] = None
    extraction_result: Optional[ExtractionResult] = None
    validation_result: Optional[ValidationResult] = None

    structured_output_path: Optional[Path] = None
    raw_response_path: Optional[Path] = None

    error_message: Optional[str] = None

    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def is_success(self) -> bool:
        """Returns True when the pipeline completed successfully."""
        return self.status == PipelineStatus.SUCCESS

    def summary(self) -> str:
        """Return a human-readable pipeline summary."""

        divider = "=" * 65

        lines = [
            divider,
            f" SPECALIVE PIPELINE: {self.status}",
            divider,
        ]

        if self.spec_doc:
            lines.append(
                f"Input Specification : {self.spec_doc.file_name}"
            )

            lines.append(
                f"Spec Statistics     : "
                f"{self.spec_doc.line_count} lines, "
                f"{self.spec_doc.char_count} chars, "
                f"{self.spec_doc.word_count} words"
            )

            lines.append(
                f"Spec SHA-256        : "
                f"{self.spec_doc.sha256[:16]}..."
            )

        if self.extraction_result:
            ir = self.extraction_result.ir

            lines.append(
                f"System Model Name   : "
                f"{ir.get('system_name', 'Unknown')}"
            )

            lines.append(
                f"Components Extracted: "
                f"{len(ir.get('components', []))}"
            )

            lines.append(
                f"Connections Linked  : "
                f"{len(ir.get('connections', []))}"
            )

            lines.append(
                f"States Modeled      : "
                f"{len(ir.get('states', []))}"
            )

        if self.validation_result:
            lines.append(
                f"Validation Status   : "
                f"{self.validation_result.status.value}"
            )

            if self.validation_result.missing_information:
                lines.append(
                    "\n[RECORDED MISSING ENGINEERING INFORMATION]"
                )

                for info in self.validation_result.missing_information:
                    lines.append(f"  ? {info}")

        if self.structured_output_path:
            lines.append(
                f"\nStructured Output   : "
                f"{self.structured_output_path}"
            )

        if self.raw_response_path:
            lines.append(
                f"Raw AI Response     : "
                f"{self.raw_response_path}"
            )

        if self.error_message:
            lines.append(
                f"\nPipeline Error      :\n"
                f"{self.error_message}"
            )

        lines.append(divider)

        return "\n".join(lines)


def run_pipeline(
    spec_path: Optional[Union[str, Path]] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    prompt_version: Optional[str] = None,
    client: Optional[BaseAIClient] = None,
    validator: Optional[StructuredValidator] = None,
) -> PipelineResult:
    """
    Execute the current SpecAlive Phase 1 pipeline.

    Flow:

        1. Load engineering specification.
        2. Create AI client.
        3. Create StructuredValidator.
        4. Create SpecificationExtractor.
        5. Extract structured IR using AI.
        6. Validate the extracted IR.
        7. Save accepted structured output.
        8. Return PipelineResult.
    """

    config.ensure_directories()

    target_spec_path = Path(
        spec_path or config.default_spec_path
    )

    timestamp = datetime.now(timezone.utc)

    # Step 1 — Load Specification

    try:
        spec_doc = load_specification(target_spec_path)

        logger.info(
            f"Loaded specification "
            f"'{spec_doc.file_name}' "
            f"({spec_doc.line_count} lines)"
        )

    except SpecificationNotFoundError as exc:
        logger.error(f"Specification not found: {exc}")

        return PipelineResult(
            status=PipelineStatus.INPUT_ERROR,
            error_message=str(exc),
            timestamp=timestamp,
        )

    except SpecificationEmptyError as exc:
        logger.error(f"Specification is empty: {exc}")

        return PipelineResult(
            status=PipelineStatus.INPUT_ERROR,
            error_message=str(exc),
            timestamp=timestamp,
        )

    except InputError as exc:
        logger.error(f"Input error: {exc}")

        return PipelineResult(
            status=PipelineStatus.INPUT_ERROR,
            error_message=str(exc),
            timestamp=timestamp,
        )

    # Step 2 — Create AI Client

    active_provider = (
        provider or config.ai.provider
    ).strip().lower()

    active_model = model or config.ai.model

    if client is None:
        try:
            client = build_client(
                provider=active_provider,
                api_key=config.ai.api_key,
                model=active_model,
                base_url=config.ai.base_url,
            )

        except Exception as exc:
            message = (
                f"Failed to initialize AI client "
                f"for provider '{active_provider}': {exc}"
            )

            logger.error(message)

            return PipelineResult(
                status=PipelineStatus.EXTRACTION_FAILED,
                spec_doc=spec_doc,
                error_message=message,
                timestamp=timestamp,
            )

    # Step 3 — Create Structured Validator

    active_validator = (
        validator
        or StructuredValidator(config.system_schema_path)
    )

    # Step 4 — Create Specification Extractor

    extractor = SpecificationExtractor(
        client=client,
        validator=active_validator,
        prompt_version=(
            prompt_version or PROMPT_VERSION
        ),
    )

    # Step 5 — AI Extraction + Validation

    try:
        extraction_result = extractor.extract(spec_doc)

        logger.info(
            "Specification extraction and validation completed."
        )

        # Step 6 — Save Accepted Structured Output

        saved_paths = extraction_result.save(
            structured_dir=config.output_structured_dir,
            raw_dir=config.output_raw_responses_dir,
        )

        structured_output_path = saved_paths.get(
            "structured"
        )

        raw_response_path = saved_paths.get(
            "raw_response"
        )

        logger.info(
            f"Structured output saved to: "
            f"{structured_output_path}"
        )

        return PipelineResult(
            status=PipelineStatus.SUCCESS,
            spec_doc=spec_doc,
            extraction_result=extraction_result,
            validation_result=(
                extraction_result.validation_result
            ),
            structured_output_path=structured_output_path,
            raw_response_path=raw_response_path,
            timestamp=timestamp,
        )

    # Step 7 — Validation Failed

    except ExtractionValidationError as exc:

        logger.warning(
            "Pipeline validation failed. "
            "AI-generated model was rejected."
        )

        return PipelineResult(
            status=PipelineStatus.VALIDATION_FAILED,
            spec_doc=spec_doc,
            validation_result=exc.validation_result,
            error_message=str(exc),
            timestamp=timestamp,
        )

    # Step 8 — Extraction Failed

    except ExtractionError as exc:

        logger.error(
            f"AI extraction failed: {exc}"
        )

        return PipelineResult(
            status=PipelineStatus.EXTRACTION_FAILED,
            spec_doc=spec_doc,
            error_message=str(exc),
            timestamp=timestamp,
        )


def build_arg_parser() -> argparse.ArgumentParser:
    """Build command-line argument parser."""

    parser = argparse.ArgumentParser(
        description=(
            "SpecAlive Phase 1: "
            "Specification -> AI -> "
            "Structured Model -> Validation"
        )
    )

    parser.add_argument(
        "--spec",
        type=str,
        default=str(config.default_spec_path),
        help=(
            "Path to the engineering specification "
            "file."
        ),
    )

    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        choices=[
            "openai",
            "gemini",
            "groq",
        ],
        help=(
            "AI provider override. "
            "Defaults to LLM_PROVIDER from .env."
        ),
    )

    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help=(
            "AI model override. "
            "Defaults to LLM_MODEL from .env."
        ),
    )

    parser.add_argument(
        "--prompt-version",
        type=str,
        default=None,
        help=(
            "Prompt version override. "
            "Defaults to current PROMPT_VERSION."
        ),
    )

    return parser


def main() -> None:
    """CLI entry point."""

    parser = build_arg_parser()

    args = parser.parse_args()

    print(
        "\nStarting SpecAlive Phase 1 "
        "Processing Pipeline..."
    )

    result = run_pipeline(
        spec_path=args.spec,
        provider=args.provider,
        model=args.model,
        prompt_version=args.prompt_version,
    )

    print(
        "\n"
        + result.summary()
        + "\n"
    )

    sys.exit(
        0 if result.is_success else 1
    )


if __name__ == "__main__":
    main()