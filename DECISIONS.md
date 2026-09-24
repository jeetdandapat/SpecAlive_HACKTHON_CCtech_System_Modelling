D1 | Started the input layer and added the basic reading structure | Needed to organize and validate the input before moving to the AI part

D2 | Added the configuration layer | To manage AI settings securely

D3 | Added the AI client and configuration layers | Added provider selection, environment-based AI settings, configuration validation, API-key masking, and the common AI client structure for OpenAI, Gemini, and Groq

D4 | Added the AI extraction layer | Connected the specification to the AI client, added prompt-based extraction, parsed the AI response into structured JSON, and validated the extracted model before accepting it

D5 | Added prompt engineering | Designed structured prompts to guide AI in reliable engineering data extraction.


D6 | Added the structured system model schema | Defined a structured format for organizing extracted engineering information before SysML and Modelica generation.

D7 | Added the structured model validation layer | Added validation checks for the extracted engineering model before the generation stages.

D8 | Added the main processing pipeline | Connected the specification input, AI extraction, and structured validation into a single processing flow, while keeping future generation stages for later updates.

