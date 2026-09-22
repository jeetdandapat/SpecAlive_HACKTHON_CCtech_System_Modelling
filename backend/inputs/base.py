from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Dict, Optional, Union


class InputError(Exception):
    pass


class SpecificationNotFoundError(InputError):
    pass


class SpecificationEmptyError(InputError):
    pass


@dataclass(frozen=True)
class SpecificationDocument:
    raw_text: str
    source_path: Optional[Path] = None
    file_name: str = "unknown"
    modality: str = "text"
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            self.raw_text.encode("utf-8")
        ).hexdigest()

    @property
    def line_count(self) -> int:
        return len(self.raw_text.splitlines())

    @property
    def char_count(self) -> int:
        return len(self.raw_text)

    @property
    def word_count(self) -> int:
        return len(self.raw_text.split())

    def get_line_snippet(
        self,
        start_line: int,
        end_line: int
    ) -> str:
        lines = self.raw_text.splitlines()
        start = max(0, start_line - 1)
        end = min(len(lines), end_line)

        return "\n".join(lines[start:end])

    def __str__(self) -> str:
        return (
            f"SpecificationDocument("
            f"file='{self.file_name}', "
            f"modality='{self.modality}', "
            f"lines={self.line_count}, "
            f"chars={self.char_count}, "
            f"sha256={self.sha256[:8]}...)"
        )


class BaseInputReader(ABC):

    @abstractmethod
    def read(
        self,
        source: Union[str, Path]
    ) -> SpecificationDocument:
        pass