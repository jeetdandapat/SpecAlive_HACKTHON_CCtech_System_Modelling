from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from backend.agent.ai_client import BaseAIClient, Message
from backend.agent.prompts import (
    MODELICA_GENERATION_SYSTEM_PROMPT,
    MODELICA_GENERATION_USER_TEMPLATE,
)


class ModelicaGenerationError(Exception):
    """Raised when Modelica generation fails."""

    pass


class ModelicaGenerator:
    """
    Generate Modelica code from validated SpecAlive IR
    using the configured AI client.
    """

    def __init__(self, client: BaseAIClient):
        self._client = client

    def _validate_model(self, model: Dict[str, Any]) -> None:
        """
        Validate the minimum structure required by the generator.
        """

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
            raise ModelicaGenerationError(
                f"Validated IR is missing required fields: {missing}"
            )

        if not isinstance(model["components"], list):
            raise ModelicaGenerationError(
                "IR field 'components' must be a list"
            )

        if not isinstance(model["connections"], list):
            raise ModelicaGenerationError(
                "IR field 'connections' must be a list"
            )

    @staticmethod
    def _generation_view(model: Dict[str, Any]) -> Dict[str, Any]:
        """Drop bulky evidence quotes while preserving model semantics."""
        parameter_fields = ("name", "value", "data_type", "unit", "description", "is_assumption", "uncertainty")
        port_fields = ("id", "name", "port_type", "domain", "direction", "description")
        state_fields = ("id", "name", "is_initial", "description")
        transition_fields = ("id", "from_state", "to_state", "trigger", "guard", "action", "description")

        def pick(item: Dict[str, Any], fields: tuple[str, ...]) -> Dict[str, Any]:
            return {key: item[key] for key in fields if key in item}

        def selected(items: Any, fields: tuple[str, ...]) -> list[Dict[str, Any]]:
            return [pick(item, fields) for item in items or [] if isinstance(item, dict)]

        components = []
        for item in model.get("components", []):
            if not isinstance(item, dict):
                continue
            component = {key: item[key] for key in ("id", "name", "type", "library_reference", "description") if key in item}
            component["ports"] = selected(item.get("ports"), port_fields)
            component["parameters"] = selected(item.get("parameters"), parameter_fields)
            component["states"] = selected(item.get("states"), state_fields)
            component["transitions"] = selected(item.get("transitions"), transition_fields)
            components.append(component)

        result: Dict[str, Any] = {
            "system_name": model["system_name"],
            "description": model["description"],
            "components": components,
            "connections": [
                {key: item[key] for key in ("id", "source_port", "target_port", "domain", "description") if key in item}
                for item in model.get("connections", []) if isinstance(item, dict)
            ],
            "parameters": selected(model.get("parameters"), parameter_fields),
            "states": selected(model.get("states"), state_fields),
            "transitions": selected(model.get("transitions"), transition_fields),
            "constraints": [
                {key: item[key] for key in ("id", "expression", "description", "source_reference") if key in item}
                for item in model.get("constraints", []) if isinstance(item, dict)
            ],
            "assumptions": model.get("assumptions", []),
            "missing_information": model.get("missing_information", []),
            "requirements": [
                {key: item[key] for key in ("id", "text", "covered_by", "status") if key in item}
                for item in model.get("requirements", []) if isinstance(item, dict)
            ],
            "source_references": [
                {key: item[key] for key in ("id", "section") if key in item}
                for item in model.get("source_references", []) if isinstance(item, dict)
            ],
        }
        return result

    def generate(
        self,
        model: Dict[str, Any],
        spec_text: str = "",
    ) -> str:
        """
        Generate Modelica code from the complete validated IR.

        The validated IR is the single source of truth.

        spec_text is retained for compatibility with the existing
        pipeline, but is intentionally NOT sent to the generation model.
        """

        try:
            # Validate IR first.
            self._validate_model(model)

            # Omit long evidence quotes and extraction-only metadata to reduce TPM use.
            ir_json = json.dumps(
                self._generation_view(model),
                ensure_ascii=False,
                separators=(",", ":"),
            )

            # Build AI generation prompt.
            # Only validated IR is sent.
            user_prompt = MODELICA_GENERATION_USER_TEMPLATE.format(
                ir_json=ir_json
            )

            messages = [
                Message(
                    role="system",
                    content=MODELICA_GENERATION_SYSTEM_PROMPT,
                ),
                Message(
                    role="user",
                    content=user_prompt,
                ),
            ]

            # Ask configured AI provider to generate Modelica.
            response = self._client.complete(
                messages=messages,
                temperature=0.0,
                max_tokens=6000,
            )

            # AI client may return either:
            # 1. a string
            # 2. an object containing .content
            if hasattr(response, "content"):
                code = response.content.strip()
            else:
                code = str(response).strip()

            # Remove Markdown code fences if the model returned them.
            if code.startswith("```"):
                lines = code.splitlines()

                if lines and lines[0].startswith("```"):
                    lines = lines[1:]

                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]

                code = "\n".join(lines).strip()

            if not code:
                raise ModelicaGenerationError(
                    "AI returned empty Modelica output"
                )

            return code

        except ModelicaGenerationError:
            raise

        except Exception as exc:
            raise ModelicaGenerationError(
                f"Modelica generation failed: {exc}"
            ) from exc

    def save(
        self,
        model: Dict[str, Any],
        output_dir: str | Path,
        filename: Optional[str] = None,
        spec_text: str = "",
    ) -> Path:
        """
        Generate Modelica and save it inside output_dir.

        This signature is compatible with the existing pipeline.
        """

        output_dir = Path(output_dir)

        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        # Generate filename automatically if not supplied.
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

            filename = f"{safe_name}.mo"

        output_path = output_dir / filename

        # Generate Modelica.
        code = self.generate(
            model,
            spec_text=spec_text,
        )

        # Save generated code.
        output_path.write_text(
            code,
            encoding="utf-8",
        )

        return output_path
