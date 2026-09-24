import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.inputs import load_specification
from backend.config import config
from backend.validators.structured_validator import StructuredValidator


def main():
    document = load_specification()

    print("Input Spec     :")
    print(
        f"Loaded '{document.file_name}' "
        f"({document.line_count} lines, {document.char_count} chars)"
    )

    print("\nSpec SHA-256   :")
    print(document.sha256)

    print("LLM_PROVIDER:", config.ai.provider)
    print("LLM_MODEL:", config.ai.model)

    StructuredValidator(config.system_schema_path)

    print("Schema Status  : Successfully loaded JSON schema.")

    from backend.pipeline import run_pipeline

    result = run_pipeline()

    print("\n" + result.summary())


if __name__ == "__main__":
    main()