from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from backend.agent.ai_client import BaseAIClient, Message
from backend.agent.prompts import (
    SYSML_GENERATION_SYSTEM_PROMPT,
    SYSML_GENERATION_USER_TEMPLATE,
)


class SysMLGenerationError(Exception):
    """Raised when SysML generation fails."""

    pass


class SysMLv2Generator:
    """
    Generate SysML v2 code from validated SpecAlive IR
    using the configured AI client.
    """

    def __init__(self, client: BaseAIClient):
        self._client = client

    def _validate_model(self, model: Dict[str, Any]) -> None:
        """Validate the minimum structure required by the generator."""

        required = [
            "system_name",
            "description",
            "components",
            "connections",
        ]

        missing = [
            key
            for key in required
            if key not in model
        ]

        if missing:
            raise SysMLGenerationError(
                f"Validated IR is missing required fields: {missing}"
            )

        if not isinstance(model["components"], list):
            raise SysMLGenerationError(
                "IR field 'components' must be a list"
            )

        if not isinstance(model["connections"], list):
            raise SysMLGenerationError(
                "IR field 'connections' must be a list"
            )

    def generate(
        self,
        model: Dict[str, Any],
        spec_text: str = "",
    ) -> str:
        """
        Generate SysML v2 from the complete validated IR.

        The validated IR is the single source of truth.

        spec_text is retained for compatibility with the existing
        pipeline, but is intentionally NOT sent to the generation model.
        """

        try:
            self._validate_model(model)

            # Complete validated IR.
            # Compact JSON reduces input token usage.
            ir_json = json.dumps(
                model,
                ensure_ascii=False,
                separators=(",", ":"),
            )

            # Only validated IR is sent to the AI.
            user_prompt = SYSML_GENERATION_USER_TEMPLATE.format(
                ir_json=ir_json
            )

            messages = [
                Message(
                    role="system",
                    content=SYSML_GENERATION_SYSTEM_PROMPT,
                ),
                Message(
                    role="user",
                    content=user_prompt,
                ),
            ]

            # IMPORTANT:
            # Groq Free Plan has 8K TPM for this model.
            # Keep the requested output budget lower so that
            # input + output stays within the TPM limit.
            response = self._client.complete(
                messages=messages,
                temperature=0.0,
                max_tokens=2500,
            )

            # The AI client can return either:
            #   1. a string
            #   2. an object with .content
            if hasattr(response, "content"):
                code = response.content.strip()
            else:
                code = str(response).strip()

            # Remove Markdown code fences if returned by the model.
            if code.startswith("```"):
                lines = code.splitlines()

                if lines and lines[0].startswith("```"):
                    lines = lines[1:]

                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]

                code = "\n".join(lines).strip()

            if not code:
                raise SysMLGenerationError(
                    "AI returned empty SysML output"
                )

            return code

        except SysMLGenerationError:
            raise

        except Exception as exc:
            raise SysMLGenerationError(
                f"SysML generation failed: {exc}"
            ) from exc

    def save(
        self,
        model: Dict[str, Any],
        output_dir: str | Path,
        filename: Optional[str] = None,
        spec_text: str = "",
    ) -> Path:
        """
        Generate SysML and save it inside output_dir.

        This signature is compatible with the existing pipeline.
        """

        output_dir = Path(output_dir)

        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        if filename is None:
            system_name = str(
                model.get(
                    "system_name",
                    "system",
                )
            )

            # Make filename filesystem-safe.
            safe_name = "".join(
                character
                if character.isalnum() or character in "_-"
                else "_"
                for character in system_name
            )

            filename = f"{safe_name}.sysml"

        output_path = output_dir / filename

        code = self.generate(
            model,
            spec_text=spec_text,
        )

        output_path.write_text(
            code,
            encoding="utf-8",
        )

        return output_path


# Backward compatibility.
SysMLGenerator = SysMLv2Generator