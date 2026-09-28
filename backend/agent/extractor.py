

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from backend.agent.ai_client import (
    AIClientError,
    AIAuthenticationError,
    BaseAIClient,
    Message,
    build_client,
)

from backend.agent.prompts import (
    EXTRACTION_SYSTEM_PROMPT,
    USER_SPEC_PROMPT_TEMPLATE,
    PROMPT_VERSION,
    format_extraction_prompts,
)
from backend.config import config
from backend.inputs.base import SpecificationDocument
from backend.validators.structured_validator import (
    StructuredValidator,
    ValidationStatus,
)


logger = logging.getLogger(__name__)


# Extraction Errors

class ExtractionError(Exception):
    """Raised when AI extraction fails."""

    pass


class ExtractionValidationError(ExtractionError):
    """
    Raised when AI output is parsed but fails structured validation.

    Contains the ValidationResult for downstream inspection.
    """

    def __init__(
        self,
        message: str,
        validation_result: Any,
        raw_ir: Dict[str, Any],
    ):
        super().__init__(message)
        self.validation_result = validation_result
        self.raw_ir = raw_ir


# Extraction Result

class ExtractionResult:
    """Container for the complete extraction output."""

    def __init__(
        self,
        ir: Dict[str, Any],
        raw_response: str,
        validation_result: Any,
        spec_doc: SpecificationDocument,
        provider: str,
        model: str,
        timestamp: datetime,
        prompt_version: str = PROMPT_VERSION,
    ):
        self.ir = ir
        self.raw_response = raw_response
        self.validation_result = validation_result
        self.spec_doc = spec_doc
        self.provider = provider
        self.model = model
        self.timestamp = timestamp
        self.prompt_version = prompt_version

    def save(
        self,
        structured_dir: Optional[Path] = None,
        raw_dir: Optional[Path] = None,
    ) -> Dict[str, Path]:
        """
        Persist IR and raw response to output directories.

        Returns:
            Dictionary containing paths for:
            - structured
            - raw_response
        """

        structured_dir = (
            structured_dir
            or config.output_structured_dir
        )

        raw_dir = (
            raw_dir
            or config.output_dir / "raw_responses"
        )

        structured_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        raw_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        timestamp = self.timestamp.strftime(
            "%Y%m%dT%H%M%SZ"
        )

        system_name = self.ir.get(
            "system_name",
            "UnknownSystem",
        )

        base = f"{system_name}_{timestamp}"

        # Save validated structured IR

        ir_path = structured_dir / f"{base}.json"

        with open(
            ir_path,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                self.ir,
                file,
                indent=2,
                ensure_ascii=False,
            )

        # Save raw AI response

        raw_path = raw_dir / f"{base}_raw.txt"

        with open(
            raw_path,
            "w",
            encoding="utf-8",
        ) as file:
            file.write(
                "# SpecAlive Raw AI Response\n"
            )

            file.write(
                f"# Provider: "
                f"{self.provider} / "
                f"Model: {self.model}\n"
            )

            file.write(
                f"# Prompt Version: "
                f"{self.prompt_version}\n"
            )

            file.write(
                f"# Timestamp: "
                f"{self.timestamp.isoformat()}\n"
            )

            file.write(
                f"# Source: "
                f"{self.spec_doc.file_name} "
                f"(sha256: "
                f"{self.spec_doc.sha256[:16]}...)\n"
            )

            file.write(
                "# NOTE: This file contains only "
                "AI model output. "
                "No API keys are stored.\n\n"
            )

            file.write(self.raw_response)

        logger.info(
            f"Saved IR -> {ir_path}"
        )

        logger.info(
            f"Saved raw response -> {raw_path}"
        )

        return {
            "structured": ir_path,
            "raw_response": raw_path,
        }


# JSON Utility

def _strip_json_fences(text: str) -> str:
    """
    Remove markdown code fences that some models
    wrap around JSON.
    """

    text = text.strip()

    match = re.search(
        r"```(?:json)?\s*([\s\S]*?)```",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).strip()

    return text


def _normalize_string_lists(ir: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize common compact AI shapes without asserting missing semantics."""
    # Keep IR collection fields canonical: local validators and generators
    # consume lists, while strict-schema responses may represent empty optional
    # collections as null. Null here means no entries were extracted.
    for field in (
        "source_references", "requirements", "constraints", "assumptions",
        "missing_information", "parameters", "states", "transitions",
        "components", "connections",
    ):
        if ir.get(field) is None and field in ir:
            ir[field] = []
    for component in ir.get("components", []) if isinstance(ir.get("components"), list) else []:
        if not isinstance(component, dict):
            continue
        for field in ("parameters", "ports", "states", "transitions"):
            if component.get(field) is None and field in component:
                component[field] = []

    for field in ("assumptions", "missing_information"):
        values = ir.get(field)
        if not isinstance(values, list):
            continue
        normalized = []
        changed = False
        for value in values:
            if isinstance(value, str):
                normalized.append(value)
                continue
            changed = True
            if isinstance(value, dict):
                item = value.get("item")
                reason = value.get("reason")
                if item is not None and reason is not None:
                    normalized.append(f"{item}: {reason}")
                elif item is not None:
                    normalized.append(str(item))
                else:
                    normalized.append("; ".join(
                        f"{key}: {json.dumps(detail, ensure_ascii=False) if isinstance(detail, (dict, list)) else detail}"
                        for key, detail in value.items()
                    ))
            else:
                normalized.append(json.dumps(value, ensure_ascii=False))
        if changed:
            logger.warning(
                "Normalized non-string entries in IR field '%s' to schema strings",
                field,
            )
            ir[field] = normalized

    # Ports have a canonical, domain-neutral identity and type fallback.
    for component in ir.get("components", []) if isinstance(ir.get("components"), list) else []:
        if not isinstance(component, dict) or not isinstance(component.get("ports"), list):
            continue
        component_id = component.get("id") or component.get("name")
        for port in component["ports"]:
            if not isinstance(port, dict):
                continue
            port_name = port.get("name")
            if port_name and not port.get("id") and component_id:
                port["id"] = f"{component_id}.{port_name}"
                logger.warning("Generated missing port id from its component and local name")
            if port_name and not port.get("port_type"):
                port["port_type"] = "interface"
                logger.warning("Assigned neutral 'interface' type to a port missing port_type")

    requirements = ir.get("requirements")
    if isinstance(requirements, list):
        used_ids = {
            str(item.get("id")) for item in requirements
            if isinstance(item, dict) and item.get("id")
        }
        normalized_requirements = []
        sequence = 1
        for item in requirements:
            if not isinstance(item, str):
                normalized_requirements.append(item)
                continue
            while f"SPEC-{sequence:03d}" in used_ids:
                sequence += 1
            normalized_requirements.append({
                "id": f"SPEC-{sequence:03d}",
                "text": item,
                "covered_by": [],
                "status": "not_covered",
            })
            used_ids.add(f"SPEC-{sequence:03d}")
            sequence += 1
            logger.warning("Preserved prose requirement as not_covered because no IR mapping was supplied")
        ir["requirements"] = normalized_requirements

    # Parameters: if the model returns a null unit, normalize it to an
    # empty string. This preserves the fact that the unit is unknown without
    # inventing an engineering unit, while satisfying the schema type.
    parameters = ir.get("parameters")
    if isinstance(parameters, list):
        for parameter in parameters:
            if not isinstance(parameter, dict):
                continue
            if "unit" in parameter and parameter.get("unit") is None:
                parameter["unit"] = ""
                logger.warning(
                    "Normalized null parameter unit to empty string"
                )

    constraints = ir.get("constraints")
    if isinstance(constraints, list):
        used_ids = {
            str(item.get("id")) for item in constraints
            if isinstance(item, dict) and item.get("id")
        }
        normalized_constraints = []
        sequence = 1
        for item in constraints:
            if not isinstance(item, str):
                normalized_constraints.append(item)
                continue
            while f"constraint_{sequence:03d}" in used_ids:
                sequence += 1
            normalized_constraints.append({
                "id": f"constraint_{sequence:03d}",
                "description": item,
            })
            used_ids.add(f"constraint_{sequence:03d}")
            sequence += 1
            logger.warning("Preserved prose constraint as descriptive text; no formal expression was supplied")
        ir["constraints"] = normalized_constraints
    return ir


def _normalize_optional_nulls(
    ir: Dict[str, Any],
    schema: Dict[str, Any],
) -> Dict[str, Any]:
    """Normalize null values dynamically using the canonical IR schema.

    Optional scalar/object fields with null are omitted because the canonical
    validator treats their declared type as non-nullable. Optional arrays are
    normalized to empty lists. Required fields remain untouched so the
    authoritative validator can report them as invalid when necessary.

    This function is schema-driven and does not hard-code field names such as
    ``library_reference``. Local ``$defs`` references are resolved recursively.
    """
    if not isinstance(ir, dict) or not isinstance(schema, dict):
        return ir

    defs = schema.get("$defs", {})

    def resolve(node: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            name = ref.rsplit("/", 1)[-1]
            target = defs.get(name)
            if isinstance(target, dict):
                merged = dict(target)
                merged.update({k: v for k, v in node.items() if k != "$ref"})
                return merged
        return node

    def walk(value: Any, node: Dict[str, Any]) -> Any:
        node = resolve(node)

        if value is None:
            return None

        node_type = node.get("type")

        if node_type == "object" and isinstance(value, dict):
            properties = node.get("properties", {})
            required = set(node.get("required", []))
            cleaned: Dict[str, Any] = {}

            for key, item in value.items():
                prop_schema = properties.get(key)

                if item is None:
                    # Required nulls must reach the validator so they are
                    # reported instead of being silently repaired.
                    if key in required:
                        cleaned[key] = None
                    else:
                        logger.warning(
                            "Removed null optional field '%s'",
                            key,
                        )
                    continue

                if isinstance(prop_schema, dict):
                    cleaned[key] = walk(item, prop_schema)
                else:
                    cleaned[key] = item

            return cleaned

        if node_type == "array" and isinstance(value, list):
            item_schema = node.get("items", {})
            return [walk(item, item_schema) for item in value]

        return value

    return walk(ir, schema)


def _normalize_structural_references(ir: Dict[str, Any]) -> Dict[str, Any]:
    """Repair only deterministic IR structure; never invent engineering meaning."""
    components = ir.get("components")
    if not isinstance(components, list):
        return ir

    # Component type is a required structural field in the system schema.
    # Prefer an already-present semantic field; otherwise use the neutral
    # structural value "component" rather than inventing an engineering class.
    for component in components:
        if not isinstance(component, dict):
            continue
        if not component.get("type"):
            fallback_type = (
                component.get("kind")
                or component.get("category")
                or "component"
            )
            component["type"] = str(fallback_type)
            logger.warning(
                "Normalized missing component type for '%s' -> '%s'",
                component.get("id", "<unknown>"),
                component["type"],
            )

    port_ids = set()
    local_name_to_ids = {}

    for component in components:
        if not isinstance(component, dict):
            continue
        component_id = component.get("id")
        ports = component.get("ports")
        if not component_id or not isinstance(ports, list):
            continue
        for port in ports:
            if not isinstance(port, dict):
                continue
            port_id = port.get("id")
            port_name = port.get("name")
            if port_id:
                port_ids.add(str(port_id))
            if port_name:
                local_name_to_ids.setdefault(str(port_name), []).append(
                    f"{component_id}.{port_name}"
                )

    connections = ir.get("connections")
    if isinstance(connections, list):
        used_ids = {
            str(x.get("id")) for x in connections
            if isinstance(x, dict) and x.get("id")
        }
        number = 1
        for connection in connections:
            if not isinstance(connection, dict):
                continue
            if not connection.get("id"):
                while f"conn_{number:03d}" in used_ids:
                    number += 1
                connection["id"] = f"conn_{number:03d}"
                used_ids.add(connection["id"])
                number += 1
                logger.warning(
                    "Generated missing connection id '%s'",
                    connection["id"],
                )

            for field in ("source_port", "target_port"):
                endpoint = connection.get(field)
                if not isinstance(endpoint, str):
                    continue
                endpoint = endpoint.strip()
                if endpoint in port_ids:
                    connection[field] = endpoint
                    continue
                candidates = local_name_to_ids.get(endpoint, [])
                if len(candidates) == 1:
                    connection[field] = candidates[0]
                    logger.warning(
                        "Qualified %s '%s' -> '%s'",
                        field, endpoint, candidates[0],
                    )

    constraints = ir.get("constraints")
    if isinstance(constraints, list):
        for index, constraint in enumerate(constraints, start=1):
            if not isinstance(constraint, dict):
                continue
            if not constraint.get("id"):
                constraint["id"] = f"constraint_{index:03d}"
                logger.warning(
                    "Generated missing constraint id '%s'",
                    constraint["id"],
                )
            if not constraint.get("description"):
                expression = constraint.get("expression")
                if isinstance(expression, str) and expression.strip():
                    constraint["description"] = expression.strip()
                    logger.warning(
                        "Copied existing constraint expression into missing description"
                    )

    return ir


# Specification Extractor

class SpecificationExtractor:
    """
    Orchestrates AI extraction of structured IR
    from engineering specifications.

    Architecture:
    - Uses BaseAIClient for provider-independent AI communication.
    - Provider client is created through build_client().
    - Raw AI response is preserved for debugging.
    - Output is always passed through StructuredValidator.
    - AI client and validation remain separate.
    """

    def __init__(
        self,
        client: Optional[BaseAIClient] = None,
        validator: Optional[StructuredValidator] = None,
        prompt_version: Optional[str] = None,
    ):
        """
        Initialize the extractor.

        Args:
            client:
                Injected AI client for testing.
                If None, the client is built from config.

            validator:
                Injected validator for testing.
                If None, StructuredValidator is used.

            prompt_version:
                Optional prompt version override.
        """

        self._client = client

        self._validator = (
            validator
            or StructuredValidator(
                config.system_schema_path
            )
        )

        self._prompt_version = (
            prompt_version
            or PROMPT_VERSION
        )

    # AI Client

    def _get_client(self) -> BaseAIClient:
        """
        Return the configured AI client.

        The API key is never exposed in logs.
        """

        if self._client is None:

            self._client = build_client(
                provider=config.ai.provider,
                api_key=config.ai.api_key,
                model=config.ai.model,
                base_url=config.ai.base_url,
            )

        return self._client

    # AI Extraction Call

    def _call_ai(
        self,
        specification_text: str,
    ) -> str:
        """
        Send the engineering specification to the AI.

        Returns:
            Raw AI text response.

        Raises:
            ExtractionError:
                If the API request fails or the response is empty.
        """

        system_prompt, user_prompt = (
            format_extraction_prompts(
                specification_text=specification_text,
                version=self._prompt_version,
            )
        )

        messages = [
            Message(
                role="system",
                content=system_prompt,
            ),
            Message(
                role="user",
                content=user_prompt,
            ),
        ]

        logger.info(
            f"Sending extraction request to "
            f"{config.ai.provider}/"
            f"{config.ai.model} "
            f"[prompt_version="
            f"{self._prompt_version}] "
            f"(temp="
            f"{config.ai.temperature}, "
            f"timeout="
            f"{config.ai.timeout}s)"
        )

        try:

            client = self._get_client()

            # Build the provider-compatible strict schema dynamically from
            # the canonical IR schema. No field names are hard-coded here.
            raw = client.complete(
                messages=messages,
                temperature=config.ai.temperature,
                timeout=config.ai.timeout,

                # Keep the initial extraction request within Groq's
                # 8000 TPM organization limit.
                max_tokens=5000,

                # Groq receives the strict structured-output schema while the
                # local StructuredValidator remains the authoritative check.
                json_mode=True,
                json_schema=None,
            )

        except AIAuthenticationError as error:

            raise ExtractionError(
                f"AI authentication failed for "
                f"provider "
                f"'{config.ai.provider}'. "
                f"Please set LLM_API_KEY in .env "
                f"and ensure it is valid. "
                f"({type(error).__name__})"
            ) from error

        except AIClientError as error:

            raise ExtractionError(
                f"AI API request failed: {error}"
            ) from error

        if not raw or not raw.strip():

            raise ExtractionError(
                "AI returned an empty response. "
                "Cannot extract structured model."
            )

        return raw

    def _repair_incomplete_ir(
        self,
        specification_text: str,
        partial_ir: Dict[str, Any],
        validation_summary: str,
    ) -> str:
        """
        Perform one compact IR repair request.

        If the extracted IR has zero components, include the source
        specification because a schema-valid empty component list is not
        useful for SysML generation. The large Groq strict schema is never
        resent during repair.
        """

        compact_validation = validation_summary[:2500]

        compact_ir = json.dumps(
            partial_ir,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        if len(compact_ir) > 14000:
            logger.warning(
                "Partial IR is large (%s chars); truncating repair context.",
                len(compact_ir),
            )
            compact_ir = compact_ir[:14000]

        components = partial_ir.get("components")
        needs_component_repair = (
            not isinstance(components, list)
            or len(components) == 0
        )

        source_context = ""
        if needs_component_repair:
            source_context = (
                "SOURCE SPECIFICATION:\n"
                f"{specification_text[:7000]}\n\n"
            )

        system_text = (
            "You are repairing a previously extracted engineering IR. "
            "Return ONLY one complete JSON object. "
            "Use the source specification as authoritative evidence. "
            "Do not invent facts, values, connections, ports, states, or behavior. "
            "Preserve valid information already present in the IR. "
            "Required root fields are: system_name, description, "
            "components, connections, assumptions, missing_information, "
            "requirements, constraints. "
            "Use [] for genuinely empty arrays. "
            "assumptions and missing_information must contain plain strings. "
            "STRUCTURAL RULES: every component MUST have id, name, and type. "
            "The type field must always be a non-empty string; if the source "
            "does not specify a more specific class, use the neutral value "
            "'component' rather than omitting the field. "
            "Every port must have id, name, and port_type; port id MUST be "
            "component_id.port_name. Every connection MUST have id, "
            "source_port, and target_port. Both connection endpoints MUST "
            "be exact existing port ids from components; never use bare local "
            "port names. Never create a connection to a missing port. Never "
            "connect a port to itself unless explicitly stated in the source. "
            "Every constraint MUST have id and description. If an existing "
            "expression is present but description is missing, use that "
            "expression as the description. Do not create dummy ports such as "
            "magnetic_port or ground_port merely to satisfy a connection. "
            "If an endpoint cannot be supported by the source, remove that "
            "unsupported connection and record the missing information instead."
        )

        if needs_component_repair:
            system_text += (
                " IMPORTANT: The previous IR contains zero components. "
                "Extract every explicitly named or clearly described physical "
                "or logical engineering element from the source specification "
                "as a component. Do not leave components empty when the source "
                "describes engineering elements. Create ports only for stated "
                "interfaces or connections."
            )

        messages = [
            Message(
                role="system",
                content=system_text,
            ),
            Message(
                role="user",
                content=(
                    "VALIDATION / REPAIR REASONS:\n"
                    f"{compact_validation}\n\n"
                    f"{source_context}"
                    "PARTIAL IR:\n"
                    f"{compact_ir}\n\n"
                    "TASK:\n"
                    "Return the complete repaired IR. "
                    "Ensure engineering elements supported by the source "
                    "are represented as components. Before returning JSON, "
                    "verify that every component has id, name, and non-empty "
                    "type; every connection endpoint exactly matches a real "
                    "port id; no connection is self-referential; and every "
                    "constraint has id and description. "
                    "Return raw JSON only."
                ),
            ),
        ]

        try:
            response = self._get_client().complete(
                messages=messages,
                temperature=0.0,
                timeout=config.ai.timeout,
                max_tokens=3500,
                json_mode=True,
                json_schema=None,
            )

        except AIClientError as error:
            raise ExtractionError(
                f"AI IR repair request failed: {error}"
            ) from error

        if not response or not response.strip():
            raise ExtractionError(
                "AI returned an empty response while repairing incomplete IR"
            )

        return response

    # JSON Parsing

    def _parse_json(
        self,
        raw_response: str,
    ) -> Dict[str, Any]:
        """
        Parse raw AI text into a JSON dictionary.

        Markdown JSON code fences are removed first.

        Raises:
            ExtractionError:
                If valid JSON cannot be parsed.
        """

        cleaned = _strip_json_fences(
            raw_response
        )

        try:

            parsed = json.loads(cleaned)

            if not isinstance(parsed, dict):
                raise ExtractionError(
                    "AI returned valid JSON, "
                    "but the top-level value "
                    "is not a JSON object."
                )

            return parsed

        except json.JSONDecodeError as error:

            raise ExtractionError(
                f"AI returned malformed JSON "
                f"(line {error.lineno}, "
                f"col {error.colno}): "
                f"{error.msg}. "
                f"First 400 chars of response: "
                f"{cleaned[:400]!r}"
            ) from error

    # Main Extraction Pipeline

    def extract(
        self,
        spec_doc: SpecificationDocument,
    ) -> ExtractionResult:
        """
        Run the complete extraction pipeline.

        Pipeline:

        1. Send specification to AI.
        2. Parse AI response as JSON.
        3. Validate JSON against structured schema.
        4. Reject invalid models.
        5. Return validated ExtractionResult.

        Raises:
            ExtractionError:
                For AI/API or JSON parsing failures.

            ExtractionValidationError:
                If AI output fails structured validation.
        """

        logger.info(
            f"Starting extraction for "
            f"'{spec_doc.file_name}' "
            f"({spec_doc.line_count} lines)"
        )

        # Step 1: AI extraction

        raw_response = self._call_ai(
            spec_doc.raw_text
        )

        logger.info(
            f"Received raw AI response "
            f"({len(raw_response)} chars)"
        )

        # Step 2: Parse JSON

        raw_ir = _normalize_string_lists(
            self._parse_json(raw_response)
        )
        raw_ir = _normalize_optional_nulls(
            raw_ir,
            self._validator._schema,
        )
        raw_ir = _normalize_structural_references(raw_ir)

        # Step 3: Structured + semantic validation.
        validation_result = self._validator.validate(raw_ir)

        components = raw_ir.get("components")
        no_components = (
            not isinstance(components, list)
            or len(components) == 0
        )

        # JSON Schema may legally allow an empty components array, but SysML
        # generation cannot proceed without at least one engineering element.
        needs_repair = (
            validation_result.status == ValidationStatus.FAIL
            or no_components
        )

        if needs_repair:
            if no_components:
                logger.warning(
                    "AI extraction produced zero components; "
                    "requesting focused semantic repair for SysML generation."
                )
            else:
                logger.warning(
                    "AI extraction failed schema validation; "
                    "requesting one focused compact repair."
                )

            repair_summary = validation_result.summary()

            if no_components:
                repair_summary += (
                    "\nSemantic validation error: components must not be empty "
                    "when the engineering specification describes system elements."
                )

            raw_response = self._repair_incomplete_ir(
                spec_doc.raw_text,
                raw_ir,
                repair_summary,
            )

            logger.info(
                "Received repaired AI response (%s chars)",
                len(raw_response),
            )

            raw_ir = _normalize_string_lists(
                self._parse_json(raw_response)
            )
            raw_ir = _normalize_optional_nulls(
                raw_ir,
                self._validator._schema,
            )
            raw_ir = _normalize_structural_references(raw_ir)

            validation_result = self._validator.validate(raw_ir)

        # Step 4: Reject invalid output

        if (
            validation_result.status
            == ValidationStatus.FAIL
        ):

            error_count = len(
                validation_result.all_errors
            )

            logger.warning(
                f"AI output failed validation "
                f"with {error_count} error(s). "
                f"Extraction REJECTED."
            )

            raise ExtractionValidationError(
                (
                    "AI extraction output failed "
                    "structured validation "
                    f"({error_count} error(s)):\n"
                    + validation_result.summary()
                ),
                validation_result=validation_result,
                raw_ir=raw_ir,
            )

        # Step 5: Accept validated IR

        logger.info(
            "Extraction validated successfully: "
            f"PASS "
            f"(missing_info="
            f"{len(validation_result.missing_information)})"
        )

        return ExtractionResult(
            ir=raw_ir,
            raw_response=raw_response,
            validation_result=validation_result,
            spec_doc=spec_doc,
            provider=config.ai.provider,
            model=config.ai.model,
            timestamp=datetime.now(
                timezone.utc
            ),
            prompt_version=self._prompt_version,
        )

    # Convenience Method

    def extract_from_text(
        self,
        text: str,
        source_name: str = "inline",
    ) -> ExtractionResult:
        """
        Extract from a raw text string instead of
        a SpecificationDocument.

        Useful for scripting and testing.
        """

        from backend.inputs.text_reader import (
            TextInputReader,
        )

        reader = TextInputReader()

        spec_doc = reader.read_from_string(
            text,
            source_name=source_name,
        )

        return self.extract(spec_doc)
