
import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Imports
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
from backend.validators.review import EngineeringReview, audit_system_model
from backend.generators.sysml_generator import (
    SysMLv2Generator,
    SysMLGenerationError,
)
from backend.generators.modelica_generator import (
    ModelicaGenerator,
    ModelicaGenerationError,
)
from backend.validators.structured_validator import (
    StructuredValidator,
    ValidationResult,
    ValidationStatus,
)

logger = logging.getLogger("spec_alive.pipeline")


# Pipeline status
class PipelineStatus(str, Enum):
    """Overall pipeline execution status."""

    SUCCESS = "SUCCESS"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    INPUT_ERROR = "INPUT_ERROR"


# Pipeline result
@dataclass
class PipelineResult:
    """Comprehensive pipeline execution report."""

    status: PipelineStatus
    spec_doc: Optional[SpecificationDocument] = None
    extraction_result: Optional[ExtractionResult] = None
    validation_result: Optional[ValidationResult] = None
    audit_review: Optional[EngineeringReview] = None
    structured_output_path: Optional[Path] = None
    sysml_output_path: Optional[Path] = None
    modelica_output_path: Optional[Path] = None
    raw_response_path: Optional[Path] = None
    audit_report_path: Optional[Path] = None
    error_report_path: Optional[Path] = None
    rejected_ir_path: Optional[Path] = None
    error_message: Optional[str] = None
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def is_success(self) -> bool:
        return self.status == PipelineStatus.SUCCESS

    def summary(self) -> str:
        """Returns a formatted human-readable summary."""

        divider = "=" * 65
        subdivider = "-" * 65

        lines = [
            divider,
            f" SPECALIVE PHASE 1 PIPELINE: {self.status.value}",
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

        if self.audit_review:
            lines.extend(
                [
                    "",
                    subdivider,
                    " HUMAN REVIEW & AUDIT TRIAGE:",
                    f"   [1] Direct Stated Facts    : "
                    f"{self.audit_review.facts_count} items "
                    f"(with evidence citations)",
                    f"   [2] Engineering Assumptions: "
                    f"{self.audit_review.assumptions_count} items "
                    f"(transparent idealizations)",
                    f"   [3] Missing Information    : "
                    f"{self.audit_review.missing_count} items "
                    f"(unstated/uncertain)",
                    subdivider,
                ]
            )

        if self.validation_result:
            lines.append(
                f"Validation Status   : "
                f"{self.validation_result.status.value}"
            )

            if self.validation_result.missing_information:
                lines.append(
                    f"\n[RECORDED MISSING ENGINEERING INFORMATION] "
                    f"({len(self.validation_result.missing_information)}):"
                )

                for info in self.validation_result.missing_information:
                    lines.append(f"  ? {info}")

        if self.structured_output_path:
            lines.append(
                f"\nAccepted Structured Output : "
                f"{self.structured_output_path}"
            )

        if self.sysml_output_path:
            lines.append(
                f"Generated SysML v2 File    : "
                f"{self.sysml_output_path}"
            )

        if self.modelica_output_path:
            lines.append(
                f"Generated Modelica File    : "
                f"{self.modelica_output_path}"
            )

        if self.audit_report_path:
            lines.append(
                f"Human Review Audit Report  : "
                f"{self.audit_report_path}"
            )

        if self.raw_response_path:
            lines.append(
                f"Raw Response Debug File    : "
                f"{self.raw_response_path}"
            )

        if self.error_report_path:
            lines.append(
                f"\nValidation Error Report    : "
                f"{self.error_report_path}"
            )

        if self.rejected_ir_path:
            lines.append(
                f"Rejected Raw Model         : "
                f"{self.rejected_ir_path}"
            )

        if self.error_message:
            lines.append(
                f"\nPipeline Error Details     :\n"
                f"{self.error_message}"
            )

        lines.append(divider)

        return "\n".join(lines)


# Main pipeline
def run_pipeline(
    spec_path: Optional[Union[str, Path]] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    prompt_version: Optional[str] = None,
    client: Optional[BaseAIClient] = None,
    validator: Optional[StructuredValidator] = None,
) -> PipelineResult:
    """Executes the complete Phase 1 pipeline.

    Flow:
        Specification
            ↓
        Input Reader
            ↓
        AI Extraction
            ↓
        Structured JSON
            ↓
        Validation
            ↓
        Audit
            ↓
        SysML Generation
            ↓
        Modelica Generation
    """

    # Initialize directories
    config.ensure_directories()

    target_spec_path = Path(
        spec_path or config.default_spec_path
    )

    ts = datetime.now(timezone.utc)
    ts_str = ts.strftime("%Y%m%dT%H%M%SZ")

    # Load specification
    try:
        spec_doc = load_specification(target_spec_path)

        logger.info(
            f"Loaded specification "
            f"'{spec_doc.file_name}' "
            f"({spec_doc.line_count} lines)"
        )

    except SpecificationNotFoundError as e:
        logger.error(f"Specification not found: {e}")

        return PipelineResult(
            status=PipelineStatus.INPUT_ERROR,
            error_message=str(e),
            timestamp=ts,
        )

    except SpecificationEmptyError as e:
        logger.error(f"Specification is empty: {e}")

        return PipelineResult(
            status=PipelineStatus.INPUT_ERROR,
            error_message=str(e),
            timestamp=ts,
        )

    except InputError as e:
        logger.error(f"Input error: {e}")

        return PipelineResult(
            status=PipelineStatus.INPUT_ERROR,
            error_message=str(e),
            timestamp=ts,
        )

    # Create AI client
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

        except Exception as e:
            msg = (
                f"Failed to initialize AI client "
                f"for provider '{active_provider}': {e}"
            )

            logger.error(msg)

            return PipelineResult(
                status=PipelineStatus.EXTRACTION_FAILED,
                spec_doc=spec_doc,
                error_message=msg,
                timestamp=ts,
            )

    # Create validator and extractor
    active_validator = (
        validator
        or StructuredValidator(config.system_schema_path)
    )

    extractor = SpecificationExtractor(
        client=client,
        validator=active_validator,
        prompt_version=(
            prompt_version or PROMPT_VERSION
        ),
    )

    # Extract and validate
    try:
        extraction_result = extractor.extract(spec_doc)

        # Save accepted structured output
        saved_paths = extraction_result.save(
            structured_dir=config.output_structured_dir,
            raw_dir=config.output_raw_responses_dir,
        )

        # Save canonical system JSON
        system_name = extraction_result.ir.get(
            "system_name",
            "SystemModel",
        )

        canonical_path = (
            config.output_structured_dir
            / f"{system_name}.json"
        )

        with open(
            canonical_path,
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                extraction_result.ir,
                f,
                indent=2,
                ensure_ascii=False,
            )

        # Audit model
        review = audit_system_model(
            extraction_result.ir,
            spec_doc=spec_doc,
        )

        audit_path = (
            config.output_structured_dir
            / f"{system_name}_audit.txt"
        )

        review.save(audit_path)

        logger.info(
            f"Pipeline SUCCESS: "
            f"Accepted structured output -> "
            f"{canonical_path}"
        )

        logger.info(
            f"Generated Human Review Audit Report -> "
            f"{audit_path}"
        )

        # Generate SysML
        sysml_path: Optional[Path] = None

        try:
            sysml_generator = SysMLv2Generator(
                client=client
            )

            sysml_path = sysml_generator.save(
                extraction_result.ir,
                output_dir=config.output_sysml_dir,
                filename=system_name,
                spec_text=spec_doc.raw_text,
            )

            logger.info(
                f"Generated SysML v2 output -> "
                f"{sysml_path}"
            )

        except SysMLGenerationError as sysml_err:
            logger.error(
                f"SysML generation failed "
                f"(pipeline still succeeded): "
                f"{sysml_err}"
            )

        # Generate Modelica
        modelica_path: Optional[Path] = None

        try:
            modelica_generator = ModelicaGenerator(
                client=client
            )

            modelica_path = modelica_generator.save(
                extraction_result.ir,
                output_dir=config.output_modelica_dir,
                filename=system_name,
                spec_text=spec_doc.raw_text,
            )

            logger.info(
                f"Generated Modelica output -> "
                f"{modelica_path}"
            )

        except ModelicaGenerationError as mo_err:
            logger.error(
                f"Modelica generation failed "
                f"(pipeline still succeeded): "
                f"{mo_err}"
            )

        # Return successful result
        return PipelineResult(
            status=PipelineStatus.SUCCESS,
            spec_doc=spec_doc,
            extraction_result=extraction_result,
            validation_result=(
                extraction_result.validation_result
            ),
            audit_review=review,
            structured_output_path=canonical_path,
            sysml_output_path=sysml_path,
            modelica_output_path=modelica_path,
            raw_response_path=saved_paths[
                "raw_response"
            ],
            audit_report_path=audit_path,
            timestamp=ts,
        )

    # Validation failure
    except ExtractionValidationError as e:
        logger.warning(
            "Pipeline VALIDATION_FAILED: "
            "AI output was rejected by "
            "schema/topology validator."
        )

        val_result = e.validation_result
        raw_ir = e.raw_ir

        system_name = (
            raw_ir.get(
                "system_name",
                "RejectedSystem",
            )
            if isinstance(raw_ir, dict)
            else "MalformedSystem"
        )

        base_name = (
            f"{system_name}_{ts_str}"
        )

        # Save rejected JSON
        rejected_json_path = (
            config.output_validation_errors_dir
            / f"{base_name}_rejected.json"
        )

        with open(
            rejected_json_path,
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                raw_ir,
                f,
                indent=2,
                ensure_ascii=False,
            )

        # Save text error report
        error_report_path = (
            config.output_validation_errors_dir
            / f"{base_name}_errors.txt"
        )

        with open(
            error_report_path,
            "w",
            encoding="utf-8",
        ) as f:
            f.write(
                "# SpecAlive Validation Error Report\n"
            )
            f.write(
                f"# Timestamp: {ts.isoformat()}\n"
            )
            f.write(
                f"# Input Specification: "
                f"{spec_doc.file_name} "
                f"(sha256: "
                f"{spec_doc.sha256[:16]}...)\n"
            )
            f.write(
                f"# Provider: "
                f"{active_provider} / "
                f"Model: {active_model}\n"
            )
            f.write(
                f"# Prompt Version: "
                f"{prompt_version or PROMPT_VERSION}\n\n"
            )
            f.write(
                val_result.summary()
            )

        # Save JSON error report
        error_json_path = (
            config.output_validation_errors_dir
            / f"{base_name}_errors.json"
        )

        with open(
            error_json_path,
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                val_result.to_dict(),
                f,
                indent=2,
                ensure_ascii=False,
            )

        return PipelineResult(
            status=PipelineStatus.VALIDATION_FAILED,
            spec_doc=spec_doc,
            validation_result=val_result,
            error_report_path=error_report_path,
            rejected_ir_path=rejected_json_path,
            error_message=str(e),
            timestamp=ts,
        )

    # Extraction failure
    except ExtractionError as e:
        logger.error(
            f"Pipeline EXTRACTION_FAILED: {e}"
        )

        return PipelineResult(
            status=PipelineStatus.EXTRACTION_FAILED,
            spec_doc=spec_doc,
            error_message=str(e),
            timestamp=ts,
        )


# CLI parser
def build_arg_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser."""

    parser = argparse.ArgumentParser(
        description=(
            "SpecAlive Phase 1: "
            "Natural-Language Specification -> "
            "Validated Structured Model Pipeline"
        ),
        formatter_class=(
            argparse.ArgumentDefaultsHelpFormatter
        ),
    )

    parser.add_argument(
        "--spec",
        type=str,
        default=str(
            config.default_spec_path
        ),
        help=(
            "Path to the input engineering "
            "specification file."
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
            "AI provider override "
            "(defaults to LLM_PROVIDER from .env)."
        ),
    )

    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help=(
            "AI model name override "
            "(defaults to LLM_MODEL from .env)."
        ),
    )

    parser.add_argument(
        "--prompt-version",
        type=str,
        default=None,
        help=(
            "Prompt template version override "
            "(defaults to current version)."
        ),
    )

    return parser


# CLI entry point
def main():
    """CLI entry point for running the pipeline."""

    parser = build_arg_parser()
    args = parser.parse_args()

    print(
        "\nStarting SpecAlive Phase 1 "
        "Extraction Pipeline..."
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