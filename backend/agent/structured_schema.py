"""Build Groq's strict JSON Schema subset from the canonical IR schema."""

from copy import deepcopy
from typing import Any, Dict


_ANNOTATIONS = {"title", "description", "$schema", "$id", "default", "examples"}


def groq_strict_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Inline local refs and make every object closed with required properties.

    Optional scalar fields stay semantically optional by accepting null. Arrays
    remain arrays and are represented as [] when there are no entries.
    """
    defs = schema.get("$defs", {})

    def expand(node: Any) -> Any:
        if isinstance(node, list):
            return [expand(item) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            ref = node["$ref"]
            if not ref.startswith("#/$defs/"):
                raise ValueError(f"Unsupported schema reference: {ref}")
            name = ref.rsplit("/", 1)[-1]
            if name not in defs:
                raise ValueError(f"Unresolved schema reference: {ref}")
            merged = deepcopy(defs[name])
            merged.update({k: v for k, v in node.items() if k != "$ref"})
            return expand(merged)

        result = {}
        for key, value in node.items():
            if key in _ANNOTATIONS | {"$defs", "pattern", "minLength", "uniqueItems", "default"}:
                continue
            if key == "properties" and isinstance(value, dict):
                # Property names are data (including a property literally
                # named "description"), so strip annotations only inside
                # each property's schema, never from this mapping.
                result[key] = {name: expand(prop_schema) for name, prop_schema in value.items()}
            else:
                result[key] = expand(value)
        # Groq accepts nullable primitive unions, but represent a genuine
        # multi-type value as a simple anyOf instead of a multi-type array.
        value_type = result.get("type")
        if isinstance(value_type, list) and len([t for t in value_type if t != "null"]) > 1:
            result.pop("type")
            result["anyOf"] = [
                {"type": item} for item in value_type
            ]
        props = result.get("properties")
        if isinstance(props, dict):
            originally_required = set(result.get("required", []))
            result["additionalProperties"] = False
            result["required"] = list(props)
            for key, prop in props.items():
                if key not in originally_required:
                    _nullable(prop)
        return result

    return expand(schema)


def _nullable(schema: Dict[str, Any]) -> None:
    """Make an optional schema accept null without weakening its value type."""
    if "type" in schema:
        value_type = schema["type"]
        if isinstance(value_type, str):
            if value_type == "array":
                # IR consumers treat collection fields uniformly as lists.
                # Strict output therefore requires [] rather than null.
                return
            schema["type"] = [value_type, "null"]
        elif isinstance(value_type, list) and "null" not in value_type:
            schema["type"] = [*value_type, "null"]
    if isinstance(schema.get("enum"), list) and None not in schema["enum"]:
        schema["enum"].append(None)
