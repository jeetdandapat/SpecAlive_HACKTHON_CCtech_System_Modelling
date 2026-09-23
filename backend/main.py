from backend.inputs import load_specification


def main():
    # Step 1: Read engineering specification
    document = load_specification()

    print("Input Spec     :")
    print(
        f"Loaded '{document.file_name}' "
        f"({document.line_count} lines, {document.char_count} chars)"
    )

    print("\nSpec SHA-256   :")
    print(document.sha256)


if __name__ == "__main__":
    main()