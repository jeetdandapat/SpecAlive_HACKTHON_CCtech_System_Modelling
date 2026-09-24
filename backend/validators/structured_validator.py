

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple, Union

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

from backend.config import SYSTEM_SCHEMA_PATH


class ValidationStatus(str, Enum):
    """Result status of structured validation."""
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass
class ValidationError:
    """Detailed validation error with contextual location and category."""
    category: str  # 'schema' | 'semantic' | 'topology' | 'state'
    location: str  # JSON path or entity reference (e.g. 'components[0].ports[1]')
    message: str
    code: str      # Machine-readable error code for Phase 2/3 automation

    def __str__(self) -> str:
        return f"[{self.category.upper()}] at '{self.location}': {self.message} (code: {self.code})"


@dataclass
class ValidationResult:
    """Comprehensive validation report produced by StructuredValidator.

    Designed for human inspection and programmatic reuse in Phase 2/3.
    Supports unpacking as `(is_valid, error_messages)` for backward compatibility.
    """
    status: ValidationStatus
    is_valid: bool
    schema_errors: List[ValidationError] = field(default_factory=list)
    semantic_errors: List[ValidationError] = field(default_factory=list)
    missing_information: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def all_errors(self) -> List[str]:
        """Returns all blocking error messages as formatted strings."""
        return [str(e) for e in (self.schema_errors + self.semantic_errors)]

    def __bool__(self) -> bool:
        return self.is_valid

    def __iter__(self) -> Iterator[Any]:
        """Enables backward-compatible unpacking: `is_valid, errors = validator.validate(m)`."""
        yield self.is_valid
        yield self.all_errors

    def to_dict(self) -> Dict[str, Any]:
        """Serializes result into a machine-readable dictionary."""
        return {
            "status": self.status.value,
            "is_valid": self.is_valid,
            "error_count": len(self.schema_errors) + len(self.semantic_errors),
            "schema_errors": [
                {"category": e.category, "location": e.location, "message": e.message, "code": e.code}
                for e in self.schema_errors
            ],
            "semantic_errors": [
                {"category": e.category, "location": e.location, "message": e.message, "code": e.code}
                for e in self.semantic_errors
            ],
            "missing_information": self.missing_information,
            "warnings": self.warnings,
        }

    def summary(self) -> str:
        """Returns a formatted, human-readable PASS/FAIL summary."""
        divider = "=" * 60
        lines = [
            divider,
            f" STRUCTURED VALIDATION RESULT: {self.status.value}",
            divider,
        ]

        if self.schema_errors:
            lines.append(f"\n[SCHEMA ERRORS] ({len(self.schema_errors)}):")
            for err in self.schema_errors:
                lines.append(f"  - {err}")

        if self.semantic_errors:
            lines.append(f"\n[SEMANTIC & TOPOLOGY ERRORS] ({len(self.semantic_errors)}):")
            for err in self.semantic_errors:
                lines.append(f"  - {err}")

        if self.missing_information:
            lines.append(f"\n[RECORDED MISSING ENGINEERING INFORMATION] ({len(self.missing_information)}):")
            for info in self.missing_information:
                lines.append(f"  ? {info}")

        if self.warnings:
            lines.append(f"\n[WARNINGS] ({len(self.warnings)}):")
            for w in self.warnings:
                lines.append(f"  ! {w}")

        if self.is_valid and not self.warnings and not self.missing_information:
            lines.append("Model is fully sound with no errors or missing information recorded.")

        lines.append(divider)
        return "\n".join(lines)


class StructuredValidator:
    """Validates Intermediate Representation (IR) system models against schemas and physics rules.

    Principles:
    - Never mutates or silently repairs incoming model data.
    - Strictly distinguishes schema violations from recorded missing engineering details.
    - Modular and reusable for Phase 2 automated test loops and Phase 3 agents.
    """

    def __init__(self, schema_path: Path = SYSTEM_SCHEMA_PATH):
        self.schema_path = Path(schema_path)
        self._schema = self._load_schema()

    def _load_schema(self) -> Dict[str, Any]:
        if not self.schema_path.exists():
            raise FileNotFoundError(f"Schema file not found at {self.schema_path}")
        with open(self.schema_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def validate_schema(self, model: Dict[str, Any]) -> List[ValidationError]:
        """Validates the model dictionary against JSON schema without modifying data."""
        errors: List[ValidationError] = []

        if HAS_JSONSCHEMA:
            validator = jsonschema.Draft202012Validator(self._schema)
            for err in sorted(validator.iter_errors(model), key=lambda e: e.path):
                location = " -> ".join([str(p) for p in err.path]) or "root"
                code = err.validator.upper() if err.validator else "SCHEMA_VIOLATION"
                errors.append(ValidationError(
                    category="schema",
                    location=location,
                    message=err.message,
                    code=f"SCHEMA_{code}"
                ))
        else:
            # Fallback when jsonschema library is unavailable
            required_keys = self._schema.get("required", [])
            for key in required_keys:
                if key not in model:
                    errors.append(ValidationError(
                        category="schema",
                        location="root",
                        message=f"Missing required property: '{key}'",
                        code="SCHEMA_MISSING_REQUIRED"
                    ))

            properties = self._schema.get("properties", {})
            for prop_name, prop_spec in properties.items():
                if prop_name in model:
                    expected_type = prop_spec.get("type")
                    val = model[prop_name]
                    if expected_type == "string" and not isinstance(val, str):
                        errors.append(ValidationError(
                            category="schema",
                            location=prop_name,
                            message=f"'{prop_name}' must be of type string, got {type(val).__name__}",
                            code="SCHEMA_TYPE_MISMATCH"
                        ))
                    elif expected_type == "array" and not isinstance(val, list):
                        errors.append(ValidationError(
                            category="schema",
                            location=prop_name,
                            message=f"'{prop_name}' must be of type array, got {type(val).__name__}",
                            code="SCHEMA_TYPE_MISMATCH"
                        ))
                    elif expected_type == "object" and not isinstance(val, dict):
                        errors.append(ValidationError(
                            category="schema",
                            location=prop_name,
                            message=f"'{prop_name}' must be of type object, got {type(val).__name__}",
                            code="SCHEMA_TYPE_MISMATCH"
                        ))

        return errors

    def validate_semantics(self, model: Dict[str, Any]) -> Tuple[List[ValidationError], List[str]]:
        """Checks internal semantic consistency, physical domains, and state topology."""
        errors: List[ValidationError] = []
        warnings: List[str] = []

        components = model.get("components", []) if isinstance(model.get("components"), list) else []
        connections = model.get("connections", []) if isinstance(model.get("connections"), list) else []
        states = model.get("states", []) if isinstance(model.get("states"), list) else []
        transitions = model.get("transitions", []) if isinstance(model.get("transitions"), list) else []

        # 1. Component ID Uniqueness & Parameters
        seen_component_ids: Set[str] = set()
        for idx, comp in enumerate(components):
            if not isinstance(comp, dict):
                continue
            comp_id = comp.get("id")
            loc = f"components[{idx}]"
            if not comp_id:
                continue

            if comp_id in seen_component_ids:
                errors.append(ValidationError(
                    category="semantic",
                    location=loc,
                    message=f"Duplicate component ID '{comp_id}'. Component IDs must be globally unique.",
                    code="DUPLICATE_COMPONENT_ID"
                ))
            seen_component_ids.add(comp_id)

            # Check parameters
            param_names: Set[str] = set()
            for p_idx, param in enumerate(comp.get("parameters", [])):
                if not isinstance(param, dict):
                    continue
                p_name = param.get("name")
                p_loc = f"{loc}.parameters[{p_idx}]"
                if p_name in param_names:
                    errors.append(ValidationError(
                        category="semantic",
                        location=p_loc,
                        message=f"Duplicate parameter '{p_name}' on component '{comp_id}'.",
                        code="DUPLICATE_PARAMETER_NAME"
                    ))
                param_names.add(p_name)

                # Warn if unit is absent for numeric parameters
                if isinstance(param.get("value"), (int, float)) and not param.get("unit"):
                    warnings.append(
                        f"Component '{comp_id}' parameter '{p_name}' has numeric value without an engineering unit."
                    )

        # 2. Port collection & ID prefixing
        known_ports: Dict[str, Dict[str, Any]] = {}
        for c_idx, comp in enumerate(components):
            if not isinstance(comp, dict):
                continue
            comp_id = comp.get("id", "")
            for p_idx, port in enumerate(comp.get("ports", [])):
                if not isinstance(port, dict):
                    continue
                port_id = port.get("id")
                port_loc = f"components[{c_idx}].ports[{p_idx}]"
                if not port_id:
                    continue

                if port_id in known_ports:
                    errors.append(ValidationError(
                        category="semantic",
                        location=port_loc,
                        message=f"Duplicate port ID '{port_id}'.",
                        code="DUPLICATE_PORT_ID"
                    ))
                known_ports[port_id] = port

                # Enforce <comp_id>.<port_name> naming convention
                if not port_id.startswith(f"{comp_id}."):
                    errors.append(ValidationError(
                        category="semantic",
                        location=port_loc,
                        message=f"Port ID '{port_id}' must start with component ID '{comp_id}.'",
                        code="INVALID_PORT_PREFIX"
                    ))

        # 3. Connection Topology & Domain Integrity
        seen_conn_ids: Set[str] = set()
        for idx, conn in enumerate(connections):
            if not isinstance(conn, dict):
                continue
            conn_id = conn.get("id", f"conn_{idx}")
            loc = f"connections[{idx}]"

            if conn_id in seen_conn_ids:
                errors.append(ValidationError(
                    category="topology",
                    location=loc,
                    message=f"Duplicate connection ID '{conn_id}'.",
                    code="DUPLICATE_CONNECTION_ID"
                ))
            seen_conn_ids.add(conn_id)

            src = conn.get("source_port")
            tgt = conn.get("target_port")

            # Check self-connection
            if src and tgt and src == tgt:
                errors.append(ValidationError(
                    category="topology",
                    location=loc,
                    message=f"Connection '{conn_id}' links port '{src}' to itself.",
                    code="SELF_CONNECTION"
                ))

            # Verify source and target port existence
            if src not in known_ports:
                errors.append(ValidationError(
                    category="topology",
                    location=f"{loc}.source_port",
                    message=f"Connection '{conn_id}': source_port '{src}' does not exist on any component.",
                    code="DANGLING_SOURCE_PORT"
                ))
            if tgt not in known_ports:
                errors.append(ValidationError(
                    category="topology",
                    location=f"{loc}.target_port",
                    message=f"Connection '{conn_id}': target_port '{tgt}' does not exist on any component.",
                    code="DANGLING_TARGET_PORT"
                ))

            # Physical domain consistency check
            if src in known_ports and tgt in known_ports:
                src_domain = known_ports[src].get("domain")
                tgt_domain = known_ports[tgt].get("domain")
                if src_domain and tgt_domain and src_domain != tgt_domain:
                    errors.append(ValidationError(
                        category="topology",
                        location=loc,
                        message=(
                            f"Connection '{conn_id}' links incompatible physical domains: "
                            f"source '{src}' is in domain '{src_domain}', "
                            f"target '{tgt}' is in domain '{tgt_domain}'."
                        ),
                        code="DOMAIN_MISMATCH"
                    ))

        # 4. State Machine Consistency
        known_state_ids: Set[str] = set()
        initial_states: List[str] = []
        for idx, state in enumerate(states):
            if not isinstance(state, dict):
                continue
            s_id = state.get("id")
            loc = f"states[{idx}]"
            if not s_id:
                continue

            if s_id in known_state_ids:
                errors.append(ValidationError(
                    category="state",
                    location=loc,
                    message=f"Duplicate state ID '{s_id}'.",
                    code="DUPLICATE_STATE_ID"
                ))
            known_state_ids.add(s_id)

            if state.get("is_initial"):
                initial_states.append(s_id)

        if len(states) > 0 and len(initial_states) > 1:
            warnings.append(
                f"Multiple initial states defined: {initial_states}. Exactly one initial state is recommended."
            )

        seen_trans_ids: Set[str] = set()
        for idx, trans in enumerate(transitions):
            if not isinstance(trans, dict):
                continue
            t_id = trans.get("id", f"trans_{idx}")
            loc = f"transitions[{idx}]"

            if t_id in seen_trans_ids:
                errors.append(ValidationError(
                    category="state",
                    location=loc,
                    message=f"Duplicate transition ID '{t_id}'.",
                    code="DUPLICATE_TRANSITION_ID"
                ))
            seen_trans_ids.add(t_id)

            from_s = trans.get("from_state")
            to_s = trans.get("to_state")

            if from_s and from_s not in known_state_ids:
                errors.append(ValidationError(
                    category="state",
                    location=f"{loc}.from_state",
                    message=f"Transition '{t_id}': from_state '{from_s}' does not exist in declared states.",
                    code="UNDECLARED_FROM_STATE"
                ))
            if to_s and to_s not in known_state_ids:
                errors.append(ValidationError(
                    category="state",
                    location=f"{loc}.to_state",
                    message=f"Transition '{t_id}': to_state '{to_s}' does not exist in declared states.",
                    code="UNDECLARED_TO_STATE"
                ))

        return errors, warnings

    def extract_missing_information(self, model: Dict[str, Any]) -> List[str]:
        """Extracts recorded missing engineering specifications.

        Separates unstated/ambiguous engineering requirements from structural syntax errors.
        Identifies:
        - Root declared missing_information entries.
        - Parameters with null, empty, or placeholder values ("unknown", "tbd", "unstated", etc.).
        """
        missing: List[str] = []
        seen = set()

        def _add(item_str: str):
            clean = item_str.strip()
            if clean and clean not in seen:
                seen.add(clean)
                missing.append(clean)

        # 1. Directly declared missing information array
        declared = model.get("missing_information", [])
        if isinstance(declared, list):
            for item in declared:
                if isinstance(item, str):
                    _add(item)

        # 2. Components with null/empty/placeholder values for parameters
        placeholder_strings = {"unknown", "tbd", "unstated", "unspecified", "none", "n/a", "?"}
        for comp in model.get("components", []):
            if isinstance(comp, dict):
                c_id = comp.get("id", "unknown_comp")
                for param in comp.get("parameters", []):
                    if isinstance(param, dict):
                        p_name = param.get("name", "unnamed")
                        val = param.get("value")
                        if val is None or val == "":
                            _add(f"Component '{c_id}' parameter '{p_name}' value was left unspecified.")
                        elif isinstance(val, str) and val.strip().lower() in placeholder_strings:
                            _add(f"Component '{c_id}' parameter '{p_name}' value is marked as unknown ('{val}').")

        return missing

    def validate(self, model: Dict[str, Any]) -> ValidationResult:
        """Runs full validation and returns a rich ValidationResult.

        Never alters the underlying model data.
        Distinguishes schema errors from missing engineering information.
        """
        # Step 1: Schema validation
        schema_errors = self.validate_schema(model)

        # Step 2: Semantic validation (only if top-level structure is parseable)
        semantic_errors: List[ValidationError] = []
        warnings: List[str] = []
        if isinstance(model, dict):
            semantic_errors, warnings = self.validate_semantics(model)

        # Step 3: Extract missing engineering information
        missing_info = self.extract_missing_information(model) if isinstance(model, dict) else []

        total_errors = len(schema_errors) + len(semantic_errors)
        is_valid = (total_errors == 0)
        status = ValidationStatus.PASS if is_valid else ValidationStatus.FAIL

        return ValidationResult(
            status=status,
            is_valid=is_valid,
            schema_errors=schema_errors,
            semantic_errors=semantic_errors,
            missing_information=missing_info,
            warnings=warnings,
        )

    def validate_file(self, file_path: Union[str, Path]) -> ValidationResult:
        """Loads a JSON model file from disk and validates it."""
        path = Path(file_path)
        if not path.exists():
            err = ValidationError(
                category="schema",
                location=str(path),
                message=f"File not found: {path}",
                code="FILE_NOT_FOUND"
            )
            return ValidationResult(
                status=ValidationStatus.FAIL,
                is_valid=False,
                schema_errors=[err]
            )

        try:
            with open(path, "r", encoding="utf-8") as f:
                model = json.load(f)
        except json.JSONDecodeError as e:
            err = ValidationError(
                category="schema",
                location=f"line {e.lineno}, col {e.colno}",
                message=f"Malformed JSON: {e.msg}",
                code="JSON_DECODE_ERROR"
            )
            return ValidationResult(
                status=ValidationStatus.FAIL,
                is_valid=False,
                schema_errors=[err]
            )

        return self.validate(model)
