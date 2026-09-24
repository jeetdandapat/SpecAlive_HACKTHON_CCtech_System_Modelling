
import argparse
import logging
import sys
from pathlib import Path


# Project Root

PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


# Project Imports

from backend.config import config

from backend.inputs import (
    load_specification,
    SpecificationNotFoundError,
    SpecificationEmptyError,
)

from backend.validators.structured_validator import (
    StructuredValidator,
)


# Logging

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(name)s: %(message)s",
)


# Foundation Check

def check_foundation() -> bool:
    """
    Verify that Phase 1 foundation paths,
    configuration, input, schema, and output
    directories are operational.
    """

    print(
        "===================="
    )

    print(
        " SpecAlive Phase 1 - "
        "AI Engineering System Model"
    )

    print(
        "======================="
    )

    print(
        f"Project Root   : "
        f"{config.base_dir}"
    )

    print(
        f"Input Dir      : "
        f"{config.input_dir}"
    )

    print(
        f"Output Dir     : "
        f"{config.output_dir}"
    )

    print(
        f"Schema File    : "
        f"{config.system_schema_path}"
    )

    # Safe AI configuration display

    ai_info = (
        config.ai.safe_dict()
    )

    print(
        f"AI Provider    : "
        f"{ai_info['provider']}"
    )

    print(
        f"AI Model       : "
        f"{ai_info['model']}"
    )

    print(
        f"API Key Status : "
        f"{ai_info['api_key_masked']}"
    )

    # Validate configuration

    is_valid, messages = (
        config.validate(
            require_api_key=False
        )
    )

    if not is_valid:

        print(
            f"Config Error   : "
            f"{messages}"
        )

        return False

    # Verify schema

    try:

        StructuredValidator(
            config.system_schema_path
        )

        print(
            "Schema Status  : "
            "Successfully loaded JSON schema."
        )

    except Exception as exc:

        print(
            "Schema Error   : "
            f"Failed to load schema: {exc}"
        )

        return False

    # Verify input specification

    try:

        spec_doc = load_specification(
            config.default_spec_path
        )

        print(
            "Input Spec     : "
            f"Loaded '{spec_doc.file_name}' "
            f"({spec_doc.line_count} lines, "
            f"{spec_doc.char_count} chars)"
        )

        print(
            "Spec SHA-256   : "
            f"{spec_doc.sha256[:16]}..."
        )

    except SpecificationNotFoundError:

        print(
            "Input Spec     : "
            "No specification found at default path "
            "(ready for user input)."
        )

    except SpecificationEmptyError as exc:

        print(
            "Input Spec Warn: "
            f"{exc}"
        )

    except Exception as exc:

        print(
            "Input Spec Err : "
            f"{exc}"
        )

    # AI configuration status

    if config.ai.has_api_key:

        print(
            "AI Extraction  : "
            f"Configured "
            f"({ai_info['provider']} / "
            f"{ai_info['model']})"
        )

    else:

        print(
            "AI Extraction  : "
            f"Provider '{ai_info['provider']}' "
            "(API key not set)"
        )

    # Ensure output directories

    config.ensure_directories()

    print(
        "Directory Tree : "
        "Foundation directories verified."
    )

    print(
        "Phase 1 Status : Ready."
    )

    print(
        "==================="
    )

    return True


# Main

def main():
    """Main execution entry point."""

    parser = argparse.ArgumentParser(
        description=(
            "SpecAlive Phase 1 Entry Point"
        ),
        formatter_class=(
            argparse.ArgumentDefaultsHelpFormatter
        ),
    )

    # Run pipeline

    parser.add_argument(
        "--run",
        "--pipeline",
        action="store_true",
        dest="run_pipeline",
        help=(
            "Execute the full "
            "AI -> Validation -> "
            "Generation pipeline."
        ),
    )

    # Specification path

    parser.add_argument(
        "--spec",
        type=str,
        default=str(
            config.default_spec_path
        ),
        help=(
            "Path to input specification "
            "text file."
        ),
    )

    # AI provider

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
            "AI provider override."
        ),
    )

    # AI model

    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help=(
            "AI model name override."
        ),
    )

    # Prompt version

    parser.add_argument(
        "--prompt-version",
        type=str,
        default=None,
        help=(
            "Prompt template version override."
        ),
    )

    args = parser.parse_args()

    # Full Pipeline

    if args.run_pipeline:

        from backend.pipeline import (
            run_pipeline
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
            0
            if result.is_success
            else 1
        )

    # Foundation Check

    else:

        success = (
            check_foundation()
        )

        if not success:
            sys.exit(1)

        print(
            "SpecAlive Phase 1 foundation "
            "initialized successfully."
        )


# Script Entry

if __name__ == "__main__":
    main()