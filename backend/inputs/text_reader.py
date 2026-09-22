from pathlib import Path
from typing import Optional, Union

from backend.config import INPUT_DIR
from backend.inputs.base import (
    BaseInputReader,
    InputError,
    SpecificationDocument,
    SpecificationEmptyError,
    SpecificationNotFoundError,
)

DEFAULT_SPECIFICATION_PATH = INPUT_DIR / "specification.txt"


class TextInputReader(BaseInputReader):

    def read(self, source: Union[str, Path]) -> SpecificationDocument:
        path = Path(source).resolve()

        if not path.exists():
            raise SpecificationNotFoundError(
                f"Specification file not found at: '{path}'. "
                f"Please ensure the file exists or check the configured path."
            )

        if not path.is_file():
            raise InputError(
                f"Specified path is not a file: '{path}'"
            )

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

        except UnicodeDecodeError:
            try:
                with open(path, "r", encoding="latin-1") as f:
                    content = f.read()

            except Exception as e:
                raise InputError(
                    f"Failed to read specification file '{path}': {e}"
                ) from e

        except Exception as e:
            raise InputError(
                f"Failed to read specification file '{path}': {e}"
            ) from e

        trimmed = content.strip()

        if not trimmed:
            raise SpecificationEmptyError(
                f"Specification file at '{path}' is empty or contains only whitespace. "
                f"An engineering specification must provide descriptive content."
            )

        return SpecificationDocument(
            raw_text=content,
            source_path=path,
            file_name=path.name,
            modality="text",
            metadata={
                "encoding": "utf-8",
                "file_size_bytes": path.stat().st_size,
            },
        )

    def read_from_string(
        self,
        text: str,
        source_name: str = "in_memory_specification.txt",
    ) -> SpecificationDocument:

        trimmed = text.strip() if text else ""

        if not trimmed:
            raise SpecificationEmptyError(
                "Specification text is empty. "
                "Provide non-empty engineering text."
            )

        return SpecificationDocument(
            raw_text=text,
            source_path=None,
            file_name=source_name,
            modality="text",
            metadata={"source": "in_memory"},
        )


def load_specification(
    file_path: Optional[Union[str, Path]] = None,
) -> SpecificationDocument:

    target = file_path or DEFAULT_SPECIFICATION_PATH
    reader = TextInputReader()

    return reader.read(target)