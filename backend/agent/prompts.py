
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple


# Prompt Version

PROMPT_VERSION = "1.9.0"


# Load Canonical System Schema

_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "schema"
    / "system_schema.json"
)

try:
    with open(
        _SCHEMA_PATH,
        "r",
        encoding="utf-8",
    ) as file:
        _SCHEMA_SUMMARY = json.load(file)

    _REQUIRED_FIELDS = _SCHEMA_SUMMARY.get(
        "required",
        [],
    )

    _TOP_PROPERTIES = list(
        _SCHEMA_SUMMARY.get(
            "properties",
            {},
        ).keys()
    )

    def _schema_shapes(node, path="$", defs=None):
        """Compact presence checklist; the API schema remains authoritative."""
        defs = defs or _SCHEMA_SUMMARY.get("$defs", {})
        shapes = []
        if not isinstance(node, dict):
            return shapes
        if "$ref" in node:
            return _schema_shapes(defs.get(node["$ref"].rsplit("/", 1)[-1], {}), path, defs)
        properties = node.get("properties")
        if isinstance(properties, dict):
            shapes.append(f"{path}: " + ", ".join(properties))
            for key, value in properties.items():
                item = value.get("items") if isinstance(value, dict) else None
                if isinstance(item, dict) and ("properties" in item or "$ref" in item):
                    shapes.extend(_schema_shapes(item, f"{path}.{key}[]", defs))
                elif isinstance(value, dict) and "$ref" in value:
                    shapes.extend(_schema_shapes(value, f"{path}.{key}", defs))
        return shapes

    _SCHEMA_SHAPE_HINT = "\n".join(_schema_shapes(_SCHEMA_SUMMARY))

except Exception:

    _REQUIRED_FIELDS = [
        "system_name",
        "description",
        "components",
        "connections",
        "assumptions",
        "missing_information",
    ]

    _TOP_PROPERTIES = (
        _REQUIRED_FIELDS
        + [
            "source_references",
            "parameters",
            "states",
            "transitions",
        ]
    )
    _SCHEMA_SHAPE_HINT = ""


# Legacy Extraction Prompt — v1.2.0

SYSTEM_PROMPT_V1_2 = f"""
You are a certified Systems Modeling Engineer
in the SpecAlive engineering pipeline.

Your sole function is to analyze the provided
natural-language engineering specification and
extract a structured System Model Intermediate
Representation (IR) in JSON format.

=== MANDATORY ENGINEERING RELIABILITY RULES ===

1. EXTRACT FACTS FROM SUPPLIED INPUT ONLY

- Extract strictly what is stated or directly
  warranted by fundamental physical conservation laws.
- Do NOT extrapolate beyond the engineering
  boundary established in the input text.

2. DO NOT FABRICATE COMPONENTS

- Only instantiate components explicitly described
  or structurally required by the system description.
- If an implied component is necessary but unnamed,
  register it under assumptions or
  missing_information.
- NEVER invent fabricated component details.

3. DO NOT FABRICATE PORTS

- Only declare interface ports that correspond
  to stated connections or standard physical
  interfaces supported by the text.
- Port IDs must follow:

  <component_id>.<port_name>

Example:

  Tank1.outlet

4. DO NOT FABRICATE PHYSICAL PARAMETERS

- If a numerical parameter is NOT stated,
  do NOT invent a value.
- Record unstated required parameters in
  missing_information.
- Every declared parameter must contain all properties listed by the
  JSON Schema: name, value, data_type, unit, description,
  source_reference, is_assumption, and uncertainty. Use null for
  unsupported optional scalar properties; do not omit them. The required
  engineering fields are name, value, and data_type.

5. DO NOT INVENT EQUATIONS OR PHYSICAL BEHAVIOUR

- Do NOT invent constitutive equations,
  empirical formulas, friction curves,
  or dynamic transfer functions.
- Standard idealizations must be documented
  under assumptions.

6. IDENTIFY CONTRADICTIONS

- Check for conflicting statements.
- Record contradictions under
  missing_information or assumptions.
- Prefix contradictions with:

  [CONTRADICTION]:

7. IDENTIFY MISSING INFORMATION

- Record unstated parameters.
- Record unspecified initial conditions.
- Record missing boundary conditions.
- Record undefined control laws.
- Record other engineering information
  necessary for complete modelling.

8. RECORD ASSUMPTIONS EXPLICITLY

- Every engineering interpretation,
  idealization, or default assumption must
  be recorded.
- Never make silent assumptions.

9. PRESERVE TRACEABILITY

- Wherever possible, attach source_reference
  information to extracted elements.
- source_references must contain objects with:

  id
  section
  text

10. RETURN ONLY STRUCTURED JSON

- Output must be valid JSON.
- Output must conform to the system schema.
- system_name must match:

  ^[A-Za-z][A-Za-z0-9_]*$

- Every port must include:
  id, name, port_type.

- Every connection must include:
  id, source_port, target_port.

- Every state must include:
  id, name.

- Every transition must include:
  id, from_state, to_state.

- Do NOT output explanations.
- Do NOT output markdown.
- Do NOT use JSON code fences.

11. SYSTEM SCHEMA

{json.dumps(_SCHEMA_SUMMARY)}
"""


USER_PROMPT_TEMPLATE_V1_2 = """
Extract a structured system model from the
following engineering specification.

=== ENGINEERING SPECIFICATION ===

{specification_text}

=== END OF SPECIFICATION ===

Execution Checklist:

1. Extract facts only.
2. Do not fabricate components, ports,
   parameters, or equations.
3. Record contradictions.
4. Record missing information.
5. Record assumptions.
6. Preserve traceability.
7. Verify topology consistency.
8. Output ONLY valid JSON.
9. Follow the system schema exactly.
"""


# Backward Compatibility Aliases

EXTRACTION_SYSTEM_PROMPT = SYSTEM_PROMPT_V1_2

USER_SPEC_PROMPT_TEMPLATE = USER_PROMPT_TEMPLATE_V1_2


# Domain-Agnostic Extraction Prompt — v1.3.0

SYSTEM_PROMPT_V1_3 = f"""
You are an engineering system modelling assistant
in the SpecAlive pipeline.

Your sole function is to READ the engineering
specification provided by the user, UNDERSTAND
the system described in it, and EXTRACT a
structured System Model Intermediate
Representation (IR) in JSON format.

=== ZERO-ASSUMPTION POLICY ===

You must NOT assume or presuppose:

- The physical domain.
- Any predefined component type.
- Any predefined port type.
- Any parameter value not explicitly stated.
- Any connection not stated or directly required.
- Any state not described.
- Any transition not described.
- Any behaviour not supported by the specification.
- Any equation not supported by the specification.

Extract engineering information dynamically
from the specification text alone.

=== MANDATORY EXTRACTION RULES ===

1. SYSTEM IDENTIFICATION

- Derive system_name from the specification.
- Use only letters, numbers and underscores.
- system_name must match:

  ^[A-Za-z][A-Za-z0-9_]*$

- Derive description from the specification.

2. COMPONENT EXTRACTION

- Identify only components explicitly named
  or described.
- Determine component type from the text.
- Do not assign unsupported domain-specific types.
- Extract stated parameters, ports and interfaces.
- Create the components and interfaces needed to represent each
  stated physical part and interaction. Do not treat requirement text,
  assumptions, or comments as a substitute for an engineering element.

3. PARAMETER EXTRACTION

- Extract numerical values, units or symbolic
  expressions exactly as stated.
- Set data_type to a SysML scalar type (Real,
  Integer, Boolean, String, or Complex) based on the quantity's
  meaning. Always provide it, including when value is
  null. Use Real for measured/continuous quantities;
  use Integer only for discrete counts or indices.
- If a parameter is mentioned but its value
  is not provided:

  value = null

- Also add the missing information to
  missing_information.
- Never invent parameter values or units.

4. PORT EXTRACTION

- Declare a port only when the specification
  explicitly states an interface, connection
  point or interaction.

- Port IDs must follow:

  <component_id>.<port_name>

- Every port must contain:

  id
  name
  port_type

- If the domain is unspecified, use:

  interface

5. CONNECTION EXTRACTION

- Create a connection when the specification states
  or clearly describes a flow/interaction path between
  components. Narrative series, branch, split, merge,
  transfer, and return paths count as topology evidence
  even without a literal "connect" sentence. Do not infer
  a path from proximity alone.

- Every connection must contain:

  id
  source_port
  target_port

- source_port and target_port must exactly match
  existing port IDs.

6. STATES AND TRANSITIONS

- Extract only operational states explicitly
  described by the specification.
- When requirements describe an ordered sequence
  using conditions such as after, when, until, or
  then, represent those stated phases as states
  and their stated conditions as transitions.
- Preserve explicit cyclic, stop/resume, and
  shutdown/return-to-start behavior as transitions
  when the text specifies it; do not leave these
  requirements uncovered just because the document
  does not provide a diagram.
- Do not invent guards, triggers, timing values,
  or initial states. Record genuinely missing
  control details in missing_information.
- Guard and trigger fields must be concise model
  expressions/events, never free-form prose. Every
  identifier used must be declared in the IR. If a
  required signal or quantity is absent, record the
  gap instead of inventing an expression.

- Every state must contain:

  id
  name

- Every transition must contain:

  id
  from_state
  to_state

- from_state and to_state must reference
  existing state IDs.

- If a trigger is explicitly mentioned,
  include it.
- Otherwise do not invent one.

7. TRACEABILITY

- source_references must be an array of objects
  containing:

  id
  section
  text

- Attach source_reference information where
  textual evidence exists.

8. MISSING INFORMATION

Record every:

- unstated parameter
- undefined property
- missing boundary condition
- missing initial condition
- undefined control law
- missing engineering quantity

in missing_information.
Each entry in `missing_information` must be one plain
string. Do not use objects with `item`, `reason`, or
other keys. Combine the item and explanation into one
string. `assumptions` must also contain plain strings.

9. ASSUMPTIONS

Record every:

- interpretation
- idealization
- default
- engineering assumption

in assumptions.

Never make silent assumptions.

10. CONTRADICTIONS

If the specification contains conflicting
statements, record them in missing_information
using:

[CONTRADICTION]:

11. OUTPUT FORMAT

- Output valid JSON only.
- Follow the JSON Schema supplied with the API request exactly.
- Include every property required by that schema. Use null for
  optional scalar fields that are not supported by the source, and []
  for arrays with no extracted entries.
- Object property presence checklist (all listed keys must appear):
{_SCHEMA_SHAPE_HINT}
- No markdown.
- No code fences.
- No conversational text.
- No explanations.

"""


USER_PROMPT_TEMPLATE_V1_3 = """
Read the engineering specification below and
extract a domain-agnostic structured system model.

=== ENGINEERING SPECIFICATION ===

{specification_text}

=== END OF SPECIFICATION ===

Extraction Checklist:

1. Domain:
   Do NOT assume the engineering domain.

2. Components:
   Extract only what the text names or describes.

3. Parameters:
   Extract the schema-defined name, value, data_type, unit, description,
   source_reference, is_assumption, and uncertainty properties. Include
   every property; use null for optional scalar properties unsupported by
   the source. Required fields are name, value, and data_type.
   Every parameter must also include data_type using
   Real, Integer, Boolean, String, or Complex, including when
   its value is unknown. Treat continuous quantities
   as Real and discrete counts as Integer.
   If value is missing, use null and record it
   in missing_information.

4. Ports:
   Declare only interfaces stated by the text.
   Every port must have:
   id, name, port_type.

5. Connections:
   Create only explicitly stated connections.
   source_port and target_port must match
   existing port IDs.

6. States and transitions:
   Extract what the specification describes. For
   explicitly ordered sequence phases, create
   states and transitions from its stated conditions.
   Include cycle, stop/resume, and shutdown behavior
   when stated; do not invent control details.

7. Missing information:
   Record every missing engineering detail.

8. Assumptions:
   Record every interpretation or idealization.

9. Traceability:
   Preserve source references.

   Also extract every explicit requirement as an item in `requirements`:
   - id: the requirement ID from the source, or a stable SPEC-### ID
   - text: the requirement text, preserving its meaning
   - covered_by: exact IDs of existing IR elements that implement or
     partially support it. This schema field is the IR-element mapping.
   - status: covered, partial, or not_covered
   - source_reference: section or source location when present
   `covered_by` may contain only IDs present in this IR: component IDs,
   fully qualified port IDs (`<component_id>.<port_name>`), component
   parameter IDs (`<component_id>.<parameter_name>`), global parameter
   names, connection IDs, state IDs, transition IDs, or constraint IDs.
   Before finalizing, check every mapped ID against the extracted elements;
   never create a mapping from a requirement ID, source reference, prose,
   assumption, or comment. Every requirement marked `covered` or `partial`
   MUST have at least one valid `covered_by` ID. Include all relevant
   existing elements that support the requirement. A requirement with no
   supporting engineering element must be `not_covered` with `covered_by: []`.
   Extract the actual engineering elements needed by the source before
   assigning coverage: represent stated components and interfaces, physical
   connections and flow paths, quantities as parameters, equations and
   relations as constraints, and explicitly described behavior as states
   and transitions. Traceability text alone is never an implementation.
   A component, parameter value, or connection supports a requirement only
   when it actually represents the stated behavior or relation. Mark
   `covered` only when the complete observable behavior or relation is
   represented. Mark `partial` when at least one real IR element represents
   part of it but logic, equations, interfaces, or boundary conditions are
   missing; record those gaps in `missing_information` without silently
   assuming them.

10. CONSTRAINTS AND EQUATIONS

   Extract explicit equations, inequalities, limits,
   invariants, and logical relations into `constraints`
   with id, expression, description, and source_reference
   when available. Use only declared IR identifiers.
   Do not invent formulas from prose. If a precise
   expression cannot be formed, record the missing data
   and leave the requirement partial or not_covered.

11. Topology:
    Verify that every connection references
    an existing port.

12. Format:
    Output ONLY raw JSON.
"""


# SysML v2 Generation Prompts

SYSML_GENERATION_SYSTEM_PROMPT = """
You are a Systems Modeling Engineer specializing in SysML v2.

Generate valid SysML v2 source code from the provided Intermediate Representation (IR).

Rules:
- IR is the single source of truth.
- Preserve every component, port, parameter, connection, state, and transition.
- Create appropriate ports for connected components.
- Create semantic connections between related ports.
- Preserve source, target, and direction from the IR.
- Every IR connection must appear as a SysML v2 connect statement.
- Use the IR connection ID as the connection name when possible.
- Ensure every connection references valid existing ports.
- Do not invent components, ports, parameters, connections, states, transitions, or behavior.
- Do not leave defined connections disconnected.
- Use generic modeling patterns.
- Do not hard-code a specific engineering domain.
- Return only valid SysML v2 source code.
""".strip()


SYSML_GENERATION_USER_TEMPLATE = """
Generate SysML v2 source code from the complete Intermediate Representation (IR).

The IR is the single source of truth.

=== IR ===

{ir_json}

=== END IR ===

Requirements:
- Include every component.
- Include every port.
- Include every parameter.
- Include every connection.
- Include every state.
- Include every transition.
- For every IR connection, generate:
  connection <id> connect <source_port> to <target_port>;
- Preserve source, target, and direction exactly.
- Use appropriate ports for connected components.
- Do not invent information.
- Return only SysML v2 source code.
""".strip()


# Modelica Generation Prompts

MODELICA_GENERATION_SYSTEM_PROMPT = """
Generate syntactically valid Modelica from the supplied IR JSON. Represent every
component, parameter, port, connection, state, transition, assumption, missing
item, constraint, and source reference. Preserve explicit constraints as equations;
use only stated values and equations; invent no
physics. Unknown values get no fabricated defaults and should be marked in a
comment. Use library_reference when present. Output only Modelica source code.
"""


MODELICA_GENERATION_USER_TEMPLATE = """
Generate complete Modelica source for this IR. Preserve all model semantics;
do not invent components, values, or behavior. Output source only.
{ir_json}
"""


# Prompt Metadata

@dataclass(frozen=True)
class PromptVersionInfo:
    """Metadata describing an extraction prompt version."""

    version: str
    system_prompt: str
    user_template: str
    description: str


# Prompt Registry

PROMPT_REGISTRY: Dict[str, PromptVersionInfo] = {

    "1.9.0": PromptVersionInfo(
        version="1.9.0",
        system_prompt=SYSTEM_PROMPT_V1_3,
        user_template=USER_PROMPT_TEMPLATE_V1_3,
        description=(
            "Requirement traceability requires valid IDs for actual "
            "engineering elements in the extracted IR."
        ),
    ),

    "1.8.0": PromptVersionInfo(
        version="1.8.0",
        system_prompt=SYSTEM_PROMPT_V1_3,
        user_template=USER_PROMPT_TEMPLATE_V1_3,
        description=(
            "Parameter extraction instructions aligned with every property "
            "required by Groq strict JSON Schema output."
        ),
    ),

    "1.7.0": PromptVersionInfo(
        version="1.7.0",
        system_prompt=SYSTEM_PROMPT_V1_3,
        user_template=USER_PROMPT_TEMPLATE_V1_3,
        description=(
            "Domain-agnostic extraction aligned with strict JSON Schema output."
        ),
    ),

    "1.6.0": PromptVersionInfo(
        version="1.6.0",
        system_prompt=SYSTEM_PROMPT_V1_3,
        user_template=USER_PROMPT_TEMPLATE_V1_3,
        description=(
            "Domain-agnostic extraction with formal constraints, "
            "typed quantities, strict traceability, and schema-shaped lists."
        ),
    ),

    "1.5.0": PromptVersionInfo(
        version="1.5.0",
        system_prompt=SYSTEM_PROMPT_V1_3,
        user_template=USER_PROMPT_TEMPLATE_V1_3,
        description=(
            "Domain-agnostic extraction with formal constraints, "
            "declared expression references, and stricter coverage."
        ),
    ),

    "1.4.0": PromptVersionInfo(
        version="1.4.0",
        system_prompt=SYSTEM_PROMPT_V1_3,
        user_template=USER_PROMPT_TEMPLATE_V1_3,
        description=(
            "Domain-agnostic extraction prompt with explicit "
            "requirement-to-model traceability coverage."
        ),
    ),

    "1.3.0": PromptVersionInfo(
        version="1.3.0",
        system_prompt=SYSTEM_PROMPT_V1_3,
        user_template=USER_PROMPT_TEMPLATE_V1_3,
        description=(
            "Domain-agnostic extraction prompt. "
            "Works across engineering domains without "
            "presupposing a specific domain, component "
            "type or equation."
        ),
    ),

    "1.2.0": PromptVersionInfo(
        version="1.2.0",
        system_prompt=SYSTEM_PROMPT_V1_2,
        user_template=USER_PROMPT_TEMPLATE_V1_2,
        description=(
            "Enhanced reliability prompt with "
            "zero-fabrication rules, contradiction "
            "detection, missing information capture "
            "and traceability."
        ),
    ),

    "1.1.0": PromptVersionInfo(
        version="1.1.0",
        system_prompt=EXTRACTION_SYSTEM_PROMPT,
        user_template=USER_SPEC_PROMPT_TEMPLATE,
        description=(
            "Phase 1 initial extraction prompt "
            "with schema embedding."
        ),
    ),
}


# Prompt Version Lookup

def get_prompt_version(
    version: Optional[str] = None,
) -> PromptVersionInfo:
    """
    Retrieve a versioned extraction prompt bundle.

    If version is not supplied, the current
    PROMPT_VERSION is used.
    """

    selected_version = (
        version or PROMPT_VERSION
    )

    if selected_version not in PROMPT_REGISTRY:
        raise KeyError(
            f"Prompt version '{selected_version}' "
            f"not found in registry. "
            f"Available versions: "
            f"{list(PROMPT_REGISTRY.keys())}"
        )

    return PROMPT_REGISTRY[selected_version]


# Prompt Formatting

def format_extraction_prompts(
    specification_text: str,
    version: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Generate the system and user prompts
    for an extraction request.

    Returns:
        Tuple containing:

        1. system prompt
        2. user prompt
    """

    prompt_info = get_prompt_version(
        version
    )

    user_prompt = (
        prompt_info.user_template.format(
            specification_text=specification_text
        )
    )

    return (
        prompt_info.system_prompt,
        user_prompt,
    )
