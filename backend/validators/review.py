from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.inputs.base import SpecificationDocument


@dataclass
class FactualItem:
    """An engineering fact directly extracted from the specification with evidence."""
    category: str
    identifier: str
    description: str
    source_reference: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AssumptionItem:
    """An explicit engineering assumption or idealization."""
    statement: str
    scope: str
    source_reference: Optional[str] = None


@dataclass
class MissingInfoItem:
    """An explicit missing, unstated, or ambiguous engineering item."""
    statement: str
    severity: str
    component_id: Optional[str] = None
    parameter_name: Optional[str] = None


@dataclass
class EngineeringReview:
    """Complete 3-way audit of an engineering model."""
    system_name: str
    description: str
    facts: List[FactualItem] = field(default_factory=list)
    assumptions: List[AssumptionItem] = field(default_factory=list)
    missing: List[MissingInfoItem] = field(default_factory=list)
    spec_file: Optional[str] = None
    spec_sha256: Optional[str] = None
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def facts_count(self) -> int:
        return len(self.facts)

    @property
    def assumptions_count(self) -> int:
        return len(self.assumptions)

    @property
    def missing_count(self) -> int:
        return len(self.missing)

    def format_report(self) -> str:
        """Renders the comprehensive, human-readable 3-way audit report."""
        divider = "=" * 78
        subdivider = "-" * 78

        lines = [
            divider,
            " SPECALIVE ENGINEERING AUDIT & HUMAN REVIEW REPORT",
            f" System Model: {self.system_name}",
            f" Generated   : {self.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        ]

        if self.spec_file:
            lines.append(
                f" Source Spec : {self.spec_file} "
                f"(SHA-256: {self.spec_sha256[:16] if self.spec_sha256 else 'N/A'}...)"
            )

        lines.extend([
            divider,
            f"Description: {self.description}",
            "",
            subdivider,
            " [1] DIRECT SPECIFICATION FACTS (Extracted from input with citations)",
            f"     Total Factual Items: {self.facts_count}",
            subdivider,
        ])

        if not self.facts:
            lines.append("  (No direct facts recorded)")
        else:
            components = [
                f for f in self.facts if f.category == "component"
            ]
            parameters = [
                f for f in self.facts if f.category == "parameter"
            ]
            connections = [
                f for f in self.facts if f.category == "connection"
            ]
            states = [
                f for f in self.facts if f.category == "state"
            ]
            citations = [
                f for f in self.facts if f.category == "citation"
            ]

            if citations:
                lines.append("  Specification Evidence Citations:")
                for c in citations:
                    lines.append(
                        f'    * [{c.identifier}] "{c.description}"'
                    )
                lines.append("")

            if components:
                lines.append(
                    f"  Verified Components ({len(components)}):"
                )
                for comp in components:
                    src = (
                        f" [Evidence: '{comp.source_reference}']"
                        if comp.source_reference
                        else ""
                    )
                    lines.append(
                        f"    * {comp.identifier} "
                        f"({comp.description}){src}"
                    )
                lines.append("")

            if parameters:
                lines.append(
                    f"  Grounded Parameters ({len(parameters)}):"
                )
                for p in parameters:
                    val_unit = (
                        f"{p.details.get('value')} "
                        f"{p.details.get('unit', '')}"
                    ).strip()

                    src = (
                        f" [Evidence: '{p.source_reference}']"
                        if p.source_reference
                        else ""
                    )

                    unc = (
                        f" (Uncertainty: {p.details.get('uncertainty')})"
                        if p.details.get("uncertainty")
                        else ""
                    )

                    lines.append(
                        f"    * {p.identifier} = "
                        f"{val_unit}{unc}{src}"
                    )
                lines.append("")

            if connections:
                lines.append(
                    f"  Physical & Signal Connections ({len(connections)}):"
                )
                for conn in connections:
                    domain = (
                        f" ({conn.details.get('domain')})"
                        if conn.details.get("domain")
                        else ""
                    )

                    src = (
                        f" [Evidence: '{conn.source_reference}']"
                        if conn.source_reference
                        else ""
                    )

                    lines.append(
                        f"    * {conn.identifier}: "
                        f"{conn.description}{domain}{src}"
                    )
                lines.append("")

            if states:
                lines.append(
                    f"  Operational States ({len(states)}):"
                )
                for s in states:
                    init_tag = (
                        " [INITIAL]"
                        if s.details.get("is_initial")
                        else ""
                    )
                    lines.append(
                        f"    * {s.identifier} "
                        f"({s.description}){init_tag}"
                    )
                lines.append("")

        lines.extend([
            subdivider,
            " [2] EXPLICIT ENGINEERING ASSUMPTIONS "
            "(Modeling idealizations & approximations)",
            f"     Total Assumptions: {self.assumptions_count}",
            subdivider,
        ])

        if not self.assumptions:
            lines.append(
                "  (No explicit assumptions recorded - "
                "verify that no silent assumptions exist)"
            )
        else:
            for idx, a in enumerate(self.assumptions, 1):
                src = (
                    f" [Context: '{a.source_reference}']"
                    if a.source_reference
                    else ""
                )

                lines.append(
                    f"  {idx}. [{a.scope.upper()}] "
                    f"{a.statement}{src}"
                )

        lines.extend([
            "",
            subdivider,
            " [3] MISSING ENGINEERING INFORMATION "
            "(Genuinely unstated / ambiguous items)",
            f"     Total Missing Items: {self.missing_count}",
            subdivider,
        ])

        if not self.missing:
            lines.append(
                "  (All required engineering information was fully specified)"
            )
        else:
            for idx, m in enumerate(self.missing, 1):
                lines.append(f"  ? {m.statement}")

        lines.extend([
            "",
            divider,
            " AUDIT SUMMARY & HUMAN REVIEW ACTION:",
            f"   • Direct Facts Extracted  : {self.facts_count}",
            f"   • Engineering Assumptions : {self.assumptions_count}",
            f"   • Missing Details Flagged : {self.missing_count}",
        ])

        if self.missing_count > 0:
            lines.append(
                f"   [!] ACTION REQUIRED: Review the "
                f"{self.missing_count} missing item(s) above "
                f"before approving model compilation."
            )
        else:
            lines.append(
                "   [OK] Model has no missing engineering information recorded."
            )

        lines.append(divider)

        return "\n".join(lines)

    def save(self, file_path: Path) -> Path:
        """Persists the review report to a text file."""
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(self.format_report())

        return file_path


def audit_system_model(
    model: Dict[str, Any],
    spec_doc: Optional[SpecificationDocument] = None,
) -> EngineeringReview:
    """Builds a structured 3-way EngineeringReview from an IR system model dict.

    Separates:
    - Direct facts (with citations from input)
    - Assumptions
    - Missing information
    """

    system_name = model.get("system_name", "UnknownSystem")
    description = model.get(
        "description",
        "No description provided."
    )

    review = EngineeringReview(
        system_name=system_name,
        description=description,
        spec_file=spec_doc.file_name if spec_doc else None,
        spec_sha256=spec_doc.sha256 if spec_doc else None,
    )

    # 1. Capture Direct Citations
    for ref in model.get("source_references", []):
        if isinstance(ref, dict):
            ref_id = ref.get("id", "REF")
            text = ref.get("text", "")

            review.facts.append(
                FactualItem(
                    category="citation",
                    identifier=ref_id,
                    description=text,
                    source_reference=ref.get("section"),
                )
            )

    # 2. Capture Components and Parameters
    for comp in model.get("components", []):
        if not isinstance(comp, dict):
            continue

        c_id = comp.get("id", "UnknownComp")
        c_name = comp.get("name", c_id)
        c_type = comp.get("type", "Generic")

        review.facts.append(
            FactualItem(
                category="component",
                identifier=c_id,
                description=f"'{c_name}' (type: {c_type})",
                source_reference=comp.get("source_reference"),
            )
        )

        for param in comp.get("parameters", []):
            if not isinstance(param, dict):
                continue

            p_name = param.get("name", "param")
            val = param.get("value")
            unit = param.get("unit", "")
            is_assumed = param.get("is_assumption", False)
            unc = param.get("uncertainty")

            qual_name = f"{c_id}.{p_name}"

            is_unknown = (
                val is None
                or val == ""
                or (
                    isinstance(val, str)
                    and val.strip().lower()
                    in (
                        "unknown",
                        "tbd",
                        "unstated",
                        "unspecified",
                        "none",
                        "n/a",
                        "?",
                    )
                )
            )

            if is_unknown:
                review.missing.append(
                    MissingInfoItem(
                        statement=(
                            f"Component '{c_id}' parameter "
                            f"'{p_name}' has no numeric value "
                            f"in specification."
                        ),
                        severity="critical",
                        component_id=c_id,
                        parameter_name=p_name,
                    )
                )

            elif is_assumed:
                review.assumptions.append(
                    AssumptionItem(
                        statement=(
                            f"Parameter '{qual_name}' assumed "
                            f"to be {val} {unit} "
                            f"({param.get('description', '')})"
                        ),
                        scope="parameter",
                        source_reference=param.get("source_reference"),
                    )
                )

            else:
                review.facts.append(
                    FactualItem(
                        category="parameter",
                        identifier=qual_name,
                        description=param.get(
                            "description",
                            p_name
                        ),
                        source_reference=param.get(
                            "source_reference"
                        ),
                        details={
                            "value": val,
                            "unit": unit,
                            "uncertainty": unc,
                        },
                    )
                )

    # 3. Capture Connections
    for conn in model.get("connections", []):
        if not isinstance(conn, dict):
            continue

        c_id = conn.get("id", "conn")
        src = conn.get("source_port", "")
        tgt = conn.get("target_port", "")
        domain = conn.get("domain", "")

        review.facts.append(
            FactualItem(
                category="connection",
                identifier=c_id,
                description=f"{src} -> {tgt}",
                source_reference=conn.get("source_reference"),
                details={"domain": domain},
            )
        )

    # 4. Capture States
    for state in model.get("states", []):
        if not isinstance(state, dict):
            continue

        s_id = state.get("id", "STATE")
        s_name = state.get("name", s_id)

        review.facts.append(
            FactualItem(
                category="state",
                identifier=s_id,
                description=s_name,
                details={
                    "is_initial": state.get(
                        "is_initial",
                        False
                    )
                },
            )
        )

    # 5. Capture System-Level Assumptions
    for asm in model.get("assumptions", []):
        if isinstance(asm, str) and asm.strip():
            review.assumptions.append(
                AssumptionItem(
                    statement=asm.strip(),
                    scope="system",
                )
            )

    # 6. Capture Root Missing Information
    for mi in model.get("missing_information", []):
        if isinstance(mi, str) and mi.strip():
            stmt = mi.strip()

            if not any(
                existing.statement == stmt
                for existing in review.missing
            ):
                review.missing.append(
                    MissingInfoItem(
                        statement=stmt,
                        severity="informational",
                    )
                )

    return review