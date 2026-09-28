from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, Optional


class SysMLGenerationError(Exception):
    """Raised when the IR cannot be emitted as a consistent SysML model."""


class SysMLv2Generator:
    """Deterministic IR-to-SysML v2 textual generator.

    Generation deliberately does not ask an LLM to write source code. The
    optional ``SYSML_V2_VALIDATOR_COMMAND`` can point to a locally installed
    parser wrapper; use ``{file}`` as the input-file argument placeholder.
    """

    _RESERVED = {
        "abstract", "action", "attribute", "binding", "connect", "connection",
        "constraint", "def", "else", "enum", "event", "exhibit", "filter",
        "first", "flow", "for", "from", "if", "in", "inout", "interface",
        "item", "metadata", "namespace", "not", "or", "out", "package", "part",
        "port", "private", "public", "redefines", "render", "requirement",
        "return", "state", "subject", "then", "to", "transition", "use", "var",
        "via", "view", "viewpoint", "while",
    }

    def __init__(self, client: Any = None):
        # Kept as an ignored argument for compatibility with existing callers.
        self._client = client

    @classmethod
    def _identifier(cls, value: Any, fallback: str = "Element") -> str:
        token = re.sub(r"[^A-Za-z0-9_]", "_", str(value or ""))
        token = re.sub(r"_+", "_", token).strip("_") or fallback
        if not token[0].isalpha():
            token = f"N_{token}"
        if token.lower() in cls._RESERVED:
            token = f"{token}_element"
        return token

    @staticmethod
    def _comment(value: Any) -> str:
        return str(value or "").replace("*/", "* /").replace("\r", " ").replace("\n", " ").strip()

    @staticmethod
    def _value_type(value: Any) -> str:
        if isinstance(value, bool):
            return "Boolean"
        if isinstance(value, int):
            return "Integer"
        if isinstance(value, float):
            return "Real"
        return "String"

    @classmethod
    def _literal(cls, value: Any) -> Optional[str]:
        if value is None or (isinstance(value, str) and value.strip().lower() in {"", "unknown", "tbd", "unstated", "unspecified", "n/a", "?"}):
            return None
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return repr(value)
        return json.dumps(str(value), ensure_ascii=False)

    @staticmethod
    def _iter_dicts(value: Any) -> list[dict[str, Any]]:
        return [item for item in value or [] if isinstance(item, dict)]

    def _validate_model(self, model: Dict[str, Any]) -> None:
        if not isinstance(model, dict):
            raise SysMLGenerationError("IR must be a JSON object")
        for key in ("system_name", "description", "components", "connections"):
            if key not in model:
                raise SysMLGenerationError(f"IR is missing required field: {key}")
        if not isinstance(model["components"], list) or not isinstance(model["connections"], list):
            raise SysMLGenerationError("IR components and connections must be lists")
        if not model["components"]:
            raise SysMLGenerationError("IR must define at least one component")

        component_ids: set[str] = set()
        component_symbols: set[str] = set()
        port_ids: set[str] = set()
        port_directions: dict[str, str] = {}
        for component in self._iter_dicts(model["components"]):
            raw_id = component.get("id") or component.get("name")
            if not raw_id:
                raise SysMLGenerationError("Every component must have an id or name")
            component_id = str(raw_id)
            if component_id in component_ids:
                raise SysMLGenerationError(f"Duplicate component id: {component_id}")
            component_ids.add(component_id)
            component_symbol = self._identifier(component_id)
            if component_symbol in component_symbols:
                raise SysMLGenerationError(f"Component ids collide after SysML name sanitization: {component_id}")
            component_symbols.add(component_symbol)
            local_port_symbols: set[str] = set()
            for port in self._iter_dicts(component.get("ports")):
                port_name = port.get("name") or port.get("id")
                if not port_name:
                    raise SysMLGenerationError(f"Component {component_id} has a port without a name")
                port_id = str(port.get("id") or f"{component_id}.{port_name}")
                if port_id in port_ids:
                    raise SysMLGenerationError(f"Duplicate port id: {port_id}")
                port_ids.add(port_id)
                port_directions[port_id] = str(port.get("direction", "inout")).lower()
                port_symbol = self._identifier(port_name, "port")
                if port_symbol in local_port_symbols:
                    raise SysMLGenerationError(f"Port names collide after SysML name sanitization on {component_id}: {port_name}")
                local_port_symbols.add(port_symbol)

        if len(component_ids) != len(self._iter_dicts(model["components"])):
            raise SysMLGenerationError("Every component must be an object")

        connection_symbols: set[str] = set()
        for connection in self._iter_dicts(model["connections"]):
            connection_symbol = self._identifier(connection.get("id"), "connection")
            if connection_symbol in connection_symbols:
                raise SysMLGenerationError(f"Connection ids collide after SysML name sanitization: {connection.get('id')}")
            connection_symbols.add(connection_symbol)
            source = connection.get("source_port") or connection.get("source") or connection.get("from")
            target = connection.get("target_port") or connection.get("target") or connection.get("to")
            if not source or not target:
                raise SysMLGenerationError(f"Connection {connection.get('id', '')!r} must define source and target ports")
            if str(source) not in port_ids or str(target) not in port_ids:
                raise SysMLGenerationError(
                    f"Connection endpoint is not declared in the IR: {source} -> {target}"
                )
            if port_directions[str(source)] not in {"out", "inout"}:
                raise SysMLGenerationError(f"Connection source port must be out/inout: {source}")
            if port_directions[str(target)] not in {"in", "inout"}:
                raise SysMLGenerationError(f"Connection target port must be in/inout: {target}")

        state_ids = {
            str(state.get("id"))
            for state in self._iter_dicts(model.get("states"))
            if state.get("id") is not None
        }
        state_symbols = [self._identifier(state.get("id") or state.get("name"), "State") for state in self._iter_dicts(model.get("states"))]
        if len(state_symbols) != len(set(state_symbols)):
            raise SysMLGenerationError("State ids collide after SysML name sanitization")
        for transition in self._iter_dicts(model.get("transitions")):
            for key in ("from_state", "to_state"):
                ref = transition.get(key)
                if ref is not None and str(ref) not in state_ids:
                    raise SysMLGenerationError(
                        f"Transition {transition.get('id', '')!r} references unknown state {ref!r}"
                    )

        requirements = self._iter_dicts(model.get("requirements"))
        constraints = self._iter_dicts(model.get("constraints"))
        constraint_symbols: set[str] = set()
        for constraint in constraints:
            constraint_id = str(constraint.get("id", "")).strip()
            if not constraint_id or not constraint.get("description"):
                raise SysMLGenerationError("Each constraint must have id and description")
            if constraint.get("expression") is not None and not str(constraint["expression"]).strip():
                raise SysMLGenerationError(f"Constraint {constraint_id!r} has an empty formal expression")
            symbol = self._identifier(constraint_id, "constraint")
            if symbol in constraint_symbols:
                raise SysMLGenerationError(f"Duplicate constraint id after SysML name sanitization: {constraint_id}")
            constraint_symbols.add(symbol)
        requirement_ids: set[str] = set()
        known_elements = set(component_ids) | port_ids
        for component in self._iter_dicts(model.get("components")):
            component_id = str(component.get("id") or component.get("name"))
            for parameter in self._iter_dicts(component.get("parameters")):
                if parameter.get("name"):
                    known_elements.add(f"{component_id}.{parameter['name']}")
        for parameter in self._iter_dicts(model.get("parameters")):
            if parameter.get("name"):
                known_elements.add(str(parameter["name"]))
        known_elements.update(
            str(item.get("id")) for item in self._iter_dicts(model.get("connections")) if item.get("id")
        )
        known_elements.update(state_ids)
        # Accept the common extraction alias `state_<ID>` as well as exact IR IDs.
        known_elements.update(f"state_{state_id}" for state_id in state_ids)
        known_elements.update(
            str(item.get("id")) for item in self._iter_dicts(model.get("transitions")) if item.get("id")
        )
        known_elements.update(str(item.get("id")) for item in constraints if item.get("id"))
        for requirement in requirements:
            requirement_id = str(requirement.get("id", "")).strip()
            if not requirement_id or not requirement.get("text"):
                raise SysMLGenerationError("Each requirement trace must have an id and text")
            if requirement_id in requirement_ids:
                raise SysMLGenerationError(f"Duplicate requirement id: {requirement_id}")
            requirement_ids.add(requirement_id)
            covered_by = requirement.get("covered_by", [])
            if not isinstance(covered_by, list):
                raise SysMLGenerationError(f"Requirement {requirement_id} covered_by must be a list")
            invalid_refs = [str(ref) for ref in covered_by if str(ref) not in known_elements]
            if invalid_refs:
                raise SysMLGenerationError(
                    f"Requirement {requirement_id} references unknown IR elements: {invalid_refs}"
                )
            status = requirement.get("status")
            if status not in {"covered", "partial", "not_covered"}:
                raise SysMLGenerationError(f"Requirement {requirement_id} has invalid status: {status!r}")
            if status in {"covered", "partial"} and not covered_by:
                raise SysMLGenerationError(f"Requirement {requirement_id} is {status} but has no mapped IR element")

    def _render_parameter(self, parameter: dict[str, Any], indent: str) -> list[str]:
        raw_name = parameter.get("name") or parameter.get("id")
        if not raw_name:
            return []
        name = self._identifier(raw_name, "parameter")
        value = parameter.get("value")
        literal = self._literal(value)
        declared_type = parameter.get("data_type")
        if declared_type is None and literal is not None:
            declared_type = self._value_type(value)
        if declared_type == "Complex":
            declared_type = "ComplexValue"
        if declared_type is not None and declared_type not in {"Real", "Integer", "Boolean", "String", "ComplexValue"}:
            raise SysMLGenerationError(f"Parameter {raw_name!r} has unsupported data_type {declared_type!r}")
        if literal is None and declared_type is None:
            raise SysMLGenerationError(
                f"Unknown parameter {raw_name!r} must declare data_type so its attribute can be typed"
            )
        line = f"{indent}attribute {name}"
        if declared_type:
            line += f" : {declared_type}"
        if literal is not None:
            line += f" = {literal}"
        line += ";"
        details = []
        if parameter.get("unit"):
            details.append(f"unit: {self._comment(parameter['unit'])}")
        if parameter.get("description"):
            details.append(self._comment(parameter["description"]))
        if parameter.get("source_reference"):
            details.append(f"source: {self._comment(parameter['source_reference'])}")
        if details:
            line += " // " + "; ".join(details)
        return [line]

    def _render_state_machine(self, model: Dict[str, Any], indent: str) -> list[str]:
        states = self._iter_dicts(model.get("states"))
        transitions = self._iter_dicts(model.get("transitions"))
        if not states:
            return []
        lines = [f"{indent}exhibit state operationalStates {{"]
        if any(state.get("is_initial") for state in states):
            lines.append(f"{indent}    entry action initial;")
        for state in states:
            state_id = self._identifier(state.get("id") or state.get("name"), "State")
            lines.append(f"{indent}    state {state_id};")
        for state in states:
            if state.get("is_initial"):
                lines.append(f"{indent}    transition initial then {self._identifier(state.get('id') or state.get('name'), 'State')};")
        for transition in transitions:
            transition_id = self._identifier(transition.get("id"), "transition")
            start = self._identifier(transition.get("from_state"), "State")
            end = self._identifier(transition.get("to_state"), "State")
            lines.extend([
                f"{indent}    transition {transition_id}",
                f"{indent}        first {start}",
            ])
            trigger = transition.get("trigger")
            if trigger:
                lines.append(f"{indent}        accept {self._identifier(trigger, 'trigger')}")
            guard = transition.get("guard")
            if guard:
                lines.append(f"{indent}        if {self._comment(guard)}")
            lines.append(f"{indent}        then {end};")
        lines.append(f"{indent}}}")
        return lines

    def generate(self, model: Dict[str, Any], spec_text: str = "") -> str:
        del spec_text  # retained for call compatibility; IR remains authoritative.
        self._validate_model(model)
        system_name = self._identifier(model.get("system_name"), "SystemModel")
        lines = [
            f"package {system_name} {{",
            "    private import ScalarValues::Real;",
            "    private import ScalarValues::Integer;",
            "    private import ScalarValues::Boolean;",
            "    private import ScalarValues::String;",
            "",
        ]
        all_parameters = [
            *self._iter_dicts(model.get("parameters")),
            *[
                parameter
                for component in self._iter_dicts(model.get("components"))
                for parameter in self._iter_dicts(component.get("parameters"))
            ],
        ]
        if any(parameter.get("data_type") == "Complex" for parameter in all_parameters):
            lines.extend([
                "    attribute def ComplexValue {",
                "        attribute realPart : Real;",
                "        attribute imaginaryPart : Real;",
                "    }",
                "",
            ])
        lines.append(f"    // {self._comment(model.get('description'))}")

        components = self._iter_dicts(model.get("components"))
        component_names: dict[str, str] = {}
        used_types: set[str] = {system_name}
        for component in components:
            component_id = str(component.get("id") or component.get("name"))
            suggested_type = component.get("type") or component.get("name") or component_id
            component_type = self._identifier(suggested_type, "Component")
            # Type identifiers must remain unique even when the IR reuses a type name.
            if component_type in used_types:
                component_type = self._identifier(f"{component_type}_{component_id}")
            used_types.add(component_type)
            component_names[component_id] = component_type
            lines.append(f"    part def {component_type} {{")
            if component.get("description"):
                lines.append(f"        // {self._comment(component['description'])}")
            for port in self._iter_dicts(component.get("ports")):
                raw_port = port.get("name") or str(port.get("id", "")).split(".")[-1]
                direction = str(port.get("direction", "inout")).lower()
                if direction not in {"in", "out", "inout"}:
                    direction = "inout"
                lines.append(f"        {direction} port {self._identifier(raw_port, 'port')};")
            for parameter in self._iter_dicts(component.get("parameters")):
                lines.extend(self._render_parameter(parameter, "        "))
            lines.append("    }")
            lines.append("")

        lines.append(f"    part def {system_name} {{")
        for component in components:
            component_id = str(component.get("id") or component.get("name"))
            component_usage = self._identifier(component_id)
            type_name = component_names[component_id]
            lines.append(f"        part {component_usage} : {type_name};")
        if components:
            lines.append("")

        for parameter in self._iter_dicts(model.get("parameters")):
            lines.extend(self._render_parameter(parameter, "        "))
        if model.get("parameters"):
            lines.append("")

        for constraint in self._iter_dicts(model.get("constraints")):
            name = self._identifier(constraint.get("id"), "constraint")
            description = self._comment(constraint.get("description"))
            if constraint.get("expression"):
                expression = str(constraint["expression"]).strip()
                lines.append(f"        assert constraint {name} {{{expression}}}")
                lines.append(f"        // {description}")
            else:
                lines.append(f"        // Constraint {name} (not formalized): {description}")
            if constraint.get("source_reference"):
                lines.append(f"        // Source: {self._comment(constraint['source_reference'])}")
        if model.get("constraints"):
            lines.append("")

        for connection in self._iter_dicts(model.get("connections")):
            connection_id = self._identifier(connection.get("id"), "connection")
            source = str(connection.get("source_port") or connection.get("source") or connection.get("from"))
            target = str(connection.get("target_port") or connection.get("target") or connection.get("to"))
            src_component, src_port = source.split(".", 1)
            dst_component, dst_port = target.split(".", 1)
            lines.append(
                f"        connection {connection_id} connect "
                f"{self._identifier(src_component)}.{self._identifier(src_port)} "
                f"to {self._identifier(dst_component)}.{self._identifier(dst_port)};"
            )
        if model.get("connections"):
            lines.append("")

        lines.extend(self._render_state_machine(model, "        "))
        for label, key in (("Assumptions", "assumptions"), ("Missing information", "missing_information")):
            values = model.get(key) or []
            if values:
                lines.append(f"        // {label} (traceability)")
                for value in values:
                    lines.append(f"        // - {self._comment(value)}")
        if model.get("requirements"):
            lines.append("        // Requirement traceability")
            for requirement in self._iter_dicts(model.get("requirements")):
                refs = ", ".join(str(ref) for ref in requirement.get("covered_by", [])) or "none"
                lines.append(
                    f"        // {self._comment(requirement.get('id'))} "
                    f"[{self._comment(requirement.get('status'))}]: "
                    f"{self._comment(requirement.get('text'))} (IR: {self._comment(refs)})"
                )
        for ref in self._iter_dicts(model.get("source_references")):
            reference = self._comment(ref.get("text") or ref.get("id"))
            if reference:
                lines.append(f"        // Source {self._comment(ref.get('id', ''))}: {reference}")
        lines.extend(["    }", "}", ""])
        code = "\n".join(lines)
        self.validate_generated(code, model)
        return code

    def validate_generated(self, code: str, model: Dict[str, Any]) -> None:
        """Run offline structural/coverage checks and an optional parser command."""
        if not code.strip().startswith(f"package {self._identifier(model.get('system_name'), 'SystemModel')} {{"):
            raise SysMLGenerationError("Generated SysML has no expected package declaration")
        if code.count("{") != code.count("}"):
            raise SysMLGenerationError("Generated SysML has unbalanced braces")
        for component in self._iter_dicts(model.get("components")):
            identifier = self._identifier(component.get("type") or component.get("name") or component.get("id"), "Component")
            usage = self._identifier(component.get("id") or component.get("name"))
            if not re.search(rf"^\s*part\s+{re.escape(usage)}\s*:", code, re.MULTILINE):
                raise SysMLGenerationError(f"Generated SysML omitted component {component.get('id') or component.get('name')}")
            if f"part def {identifier} {{" not in code and not re.search(rf"part\s+def\s+{re.escape(identifier)}_{re.escape(usage)}\s*{{", code):
                raise SysMLGenerationError(f"Generated SysML omitted component definition for {component.get('id') or component.get('name')}")
            for port in self._iter_dicts(component.get("ports")):
                port_name = self._identifier(port.get("name") or str(port.get("id", "")).split(".")[-1], "port")
                direction = str(port.get("direction", "inout")).lower()
                if direction not in {"in", "out", "inout"}:
                    direction = "inout"
                if not re.search(rf"^\s*{direction}\s+port\s+{re.escape(port_name)}\s*;", code, re.MULTILINE):
                    raise SysMLGenerationError(f"Generated SysML omitted port {port.get('id') or port_name}")
        for connection in self._iter_dicts(model.get("connections")):
            raw_id = self._identifier(connection.get("id"), "connection")
            if not re.search(rf"\bconnection\s+{re.escape(raw_id)}\s+connect\b", code):
                raise SysMLGenerationError(f"Generated SysML omitted connection {connection.get('id')}")
        for parameter in self._iter_dicts(model.get("parameters")):
            name = self._identifier(parameter.get("name") or parameter.get("id"), "parameter")
            if not re.search(rf"^\s*attribute\s+{re.escape(name)}\b", code, re.MULTILINE):
                raise SysMLGenerationError(f"Generated SysML omitted parameter {parameter.get('name') or parameter.get('id')}")
        for constraint in self._iter_dicts(model.get("constraints")):
            name = self._identifier(constraint.get("id"), "constraint")
            expected = (
                rf"^\s*assert\s+constraint\s+{re.escape(name)}\s*\{{"
                if constraint.get("expression")
                else rf"^\s*//\s*Constraint\s+{re.escape(name)}\s+\(not formalized\):"
            )
            if not re.search(expected, code, re.MULTILINE):
                raise SysMLGenerationError(f"Generated SysML omitted constraint {constraint.get('id')}")
        for state in self._iter_dicts(model.get("states")):
            name = self._identifier(state.get("id") or state.get("name"), "State")
            if not re.search(rf"^\s*state\s+{re.escape(name)}\s*;", code, re.MULTILINE):
                raise SysMLGenerationError(f"Generated SysML omitted state {state.get('id') or state.get('name')}")
        for transition in self._iter_dicts(model.get("transitions")):
            name = self._identifier(transition.get("id"), "transition")
            if not re.search(rf"^\s*transition\s+{re.escape(name)}\s*$", code, re.MULTILINE):
                raise SysMLGenerationError(f"Generated SysML omitted transition {transition.get('id')}")
        for requirement in self._iter_dicts(model.get("requirements")):
            requirement_id = self._comment(requirement.get("id"))
            if f"// {requirement_id} [" not in code:
                raise SysMLGenerationError(f"Generated SysML omitted requirement trace {requirement_id}")
        self._run_external_validator(code)

    @staticmethod
    def _run_external_validator(code: str) -> None:
        command_template = os.getenv("SYSML_V2_VALIDATOR_COMMAND", "").strip()
        if not command_template:
            if os.getenv("SYSML_REQUIRE_FULL_VALIDATION", "").lower() in {"1", "true", "yes", "on"}:
                raise SysMLGenerationError(
                    "Full validation is required but SYSML_V2_VALIDATOR_COMMAND is not configured"
                )
            return
        try:
            command = json.loads(command_template)
        except json.JSONDecodeError as exc:
            raise SysMLGenerationError(
                "SYSML_V2_VALIDATOR_COMMAND must be a JSON array, e.g. "
                '["java", "-jar", "sysml-parser-wrapper.jar", "{file}"]'
            ) from exc
        if not isinstance(command, list) or not command or "{file}" not in command:
            raise SysMLGenerationError(
                "SYSML_V2_VALIDATOR_COMMAND must be a JSON argument array containing {file}"
            )
        temp_path: Optional[Path] = None
        try:
            import tempfile
            with tempfile.NamedTemporaryFile("w", suffix=".sysml", encoding="utf-8", delete=False) as handle:
                handle.write(code)
                temp_path = Path(handle.name)
            argv = [str(temp_path) if token == "{file}" else token for token in command]
            completed = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
            if completed.returncode:
                details = (completed.stderr or completed.stdout or "parser returned a non-zero exit code").strip()
                raise SysMLGenerationError(f"SysML v2 parser rejected generated model: {details}")
        except (OSError, subprocess.SubprocessError) as exc:
            raise SysMLGenerationError(f"Could not run configured SysML v2 parser: {exc}") from exc
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)

    @staticmethod
    def _run_diagram_importer(sysml_path: Path, output_dir: Path) -> None:
        command_template = os.getenv("SYSML_V2_DIAGRAM_COMMAND", "").strip()
        if not command_template:
            if os.getenv("SYSML_REQUIRE_FULL_VALIDATION", "").lower() in {"1", "true", "yes", "on"}:
                raise SysMLGenerationError(
                    "Full validation is required but SYSML_V2_DIAGRAM_COMMAND is not configured"
                )
            return
        try:
            command = json.loads(command_template)
        except json.JSONDecodeError as exc:
            raise SysMLGenerationError(
                "SYSML_V2_DIAGRAM_COMMAND must be a JSON argument array containing {file} and {output_dir}"
            ) from exc
        if not isinstance(command, list) or not command or "{file}" not in command or "{output_dir}" not in command:
            raise SysMLGenerationError(
                "SYSML_V2_DIAGRAM_COMMAND must be a JSON argument array containing {file} and {output_dir}"
            )
        staging_dir = output_dir / f".sysml-diagram-{uuid.uuid4().hex}"
        staging_dir.mkdir(parents=True, exist_ok=False)
        try:
            argv = [
                str(sysml_path) if token == "{file}" else
                str(staging_dir) if token == "{output_dir}" else str(token)
                for token in command
            ]
            try:
                completed = subprocess.run(argv, capture_output=True, text=True, timeout=180, check=False)
            except (OSError, subprocess.SubprocessError) as exc:
                raise SysMLGenerationError(f"Could not run configured SysML diagram importer: {exc}") from exc
            if completed.returncode:
                details = (completed.stderr or completed.stdout or "diagram importer returned a non-zero exit code").strip()
                raise SysMLGenerationError(f"SysML diagram import/render failed: {details}")
            images = [
                path for path in staging_dir.rglob("*")
                if path.is_file() and path.suffix.lower() in {".svg", ".png", ".pdf", ".jpg", ".jpeg"}
            ]
            if not images:
                raise SysMLGenerationError("Diagram command succeeded but produced no SVG/PNG/PDF/JPG artifact")
            destination = output_dir / "diagrams" / sysml_path.stem
            destination.mkdir(parents=True, exist_ok=True)
            for image_path in images:
                shutil.copy2(image_path, destination / image_path.name)
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    def save(self, model: Dict[str, Any], output_dir: str | Path, filename: Optional[str] = None, spec_text: str = "") -> Path:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        if filename is None:
            filename = self._identifier(model.get("system_name"), "system")
        output_path = Path(filename)
        if output_path.suffix.lower() != ".sysml":
            output_path = output_path.with_suffix(".sysml")
        if not output_path.is_absolute():
            output_path = output_dir / output_path
        code = self.generate(model, spec_text=spec_text)
        output_path.write_text(code, encoding="utf-8")
        self._run_diagram_importer(output_path, output_dir)
        return output_path


SysMLGenerator = SysMLv2Generator
