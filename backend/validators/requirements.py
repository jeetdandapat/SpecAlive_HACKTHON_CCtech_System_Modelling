"""Source-to-IR requirement traceability checks."""

import re
from typing import Any


_REQUIREMENT_ID = re.compile(
    r"\b(?:(?:URS-[A-Z0-9]+(?:-[A-Z0-9]+)*)|"
    r"(?:SW-REQ|HW-REQ|SAFETY-REQ|REQ|FR|NFR|SRS|SR|SYS))-\d+\b",
    re.IGNORECASE,
)
_NORMATIVE_CLAUSE = re.compile(r"\b(?:shall|must|is required to|are required to|needs to)\b", re.IGNORECASE)


def validate_requirement_coverage(spec_text: str, model: dict[str, Any]) -> list[str]:
    """Ensure explicitly numbered requirements appear and are marked covered.

    This verifies traceability bookkeeping. It does not prove that the linked
    model element semantically satisfies the natural-language requirement.
    """
    source_ids = {value.upper() for value in _REQUIREMENT_ID.findall(spec_text or "")}
    raw_requirements = model.get("requirements", [])
    if not isinstance(raw_requirements, list):
        return ["IR field 'requirements' must be a list"]

    requirements: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for item in raw_requirements:
        if not isinstance(item, dict) or not item.get("id"):
            errors.append("Each requirement trace must be an object with an id")
            continue
        req_id = str(item["id"]).strip().upper()
        if req_id in requirements:
            errors.append(f"Duplicate requirement trace: {req_id}")
        requirements[req_id] = item

    missing = sorted(source_ids - requirements.keys())
    if missing:
        errors.append("Source requirements missing from IR: " + ", ".join(missing))

    for req_id in sorted(source_ids & requirements.keys()):
        status = requirements[req_id].get("status")
        if status != "covered":
            errors.append(f"Source requirement {req_id} is marked {status or 'unclassified'}")

    # Unnumbered specifications still need trace entries for their explicit
    # obligations. This is a conservative count check, not semantic proof.
    if not source_ids:
        normative_count = len(_NORMATIVE_CLAUSE.findall(spec_text or ""))
        if normative_count and len(requirements) < normative_count:
            errors.append(
                f"Specification contains {normative_count} explicit obligation marker(s), "
                f"but IR traces only {len(requirements)} requirement(s)"
            )
        if normative_count:
            for req_id, item in requirements.items():
                if item.get("status") != "covered":
                    errors.append(f"Requirement {req_id} is marked {item.get('status') or 'unclassified'}")
    return errors
