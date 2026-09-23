from backend.inputs import load_specification
from backend.config import LLM_PROVIDER
from backend.config import LLM_MODEL


def main():
    document = load_specification()

    print("Input Spec     :")
    print(
        f"Loaded '{document.file_name}' "
        f"({document.line_count} lines, {document.char_count} chars)"
    )

    print("\nSpec SHA-256   :")
    print(document.sha256)

    print("LLM_PROVIDER:", LLM_PROVIDER)
    print("LLM_MODEL",LLM_MODEL)


if __name__ == "__main__":
    main()