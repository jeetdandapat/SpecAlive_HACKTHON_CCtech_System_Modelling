### Input Layer

Used AI for guidance while implementing the input layer.

### Configuration Layer

Used AI only to explore available free AI API options.

### AI Client Layer

Used AI for guidance while building the AI client layer and connecting multiple AI providers.

### AI Extraction Layer

Implemented the extraction workflow to convert engineering specifications into structured JSON. Worked on handling AI responses, parsing the generated JSON, validating the extracted engineering information, and handling extraction errors. Also maintained raw responses for debugging and traceability.


### Prompt Engineering  Layer
Used AI for guidance in designing and refining versioned extraction prompts. Defined the project-specific extraction rules, validation requirements, anti-fabrication, missing-information, assumptions, and traceability rules.


#### Structured System Model Schema  Layer

Defined the structured engineering model schema, including system information, components, parameters, ports, connections, states, transitions, assumptions, and missing information.
Used AI for guidance in understanding JSON Schema structure, field definitions, and validation concepts.


### Structured Model Validation Layer
 Implemented validation checks for schema structure, component IDs, parameters, ports, connections, physical domains, states, and transitions. Added handling for missing engineering information and generated structured validation results.

Used AI for guidance in understanding validation logic, JSON Schema validation, and organizing validation checks.


#### Model Analysis Layer

Implemented the model analysis layer to identify and organize facts, assumptions, and missing information from the validated engineering model.

Used AI to understand how the model analysis should be structured and how the identified information should be organized.


### SysML Generation Layer

Added the workflow for creating SysML v2 models from the validated engineering data. Integrated the AI client to generate the SysML representation and prepared the output for .sysml file storage.

Used AI to understand SysML v2 generation requirements and improve the generation workflow and output handling.


### Modelica Generation Layer

Added the workflow for creating Modelica models from the validated engineering data. Integrated the AI client to generate the Modelica representation and prepared the output for .mo file storage.

Used AI to understand Modelica generation requirements and improve the generation workflow and output handling.











