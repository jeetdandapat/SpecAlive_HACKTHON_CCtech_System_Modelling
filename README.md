# SpecAlive — Engineering System Modeling

## Current project status

**What I have built:** A text-based pipeline sends an engineering specification to an AI provider and extracts a JSON system model. The project checks the JSON structure and creates an audit report. For SysML v2, project code reads that JSON and writes the SysML source; I do not ask the AI to write SysML. For Modelica, the project puts the same model into a prompt and asks the AI to generate the Modelica source. Example outputs exist for the two-tank, indoor-air-quality, and magnetic-circuit cases; these outputs still need reliable validation.

**What is not finished:** the generated source has not been consistently validated. I have opened generated code in external tools and checked it manually; some code may pass and some may fail. The application does not yet run those tools automatically, capture their errors, repair the code, or run simulations. Existing generated files are not proof that validation or simulation passed.

**Current limits:** input is text only; the full benchmark is not processed by the project; Modelica may be saved without a `.mo` extension; and there is no repeatable benchmark score/test report yet.

**Next Goal:** Automate the complete model validation and testing workflow. After generating the SysML v2 and Modelica code, the system should automatically validate the generated code using the required tools, identify errors, and send the errors back to the AI for correction. The corrected code should then be tested again automatically. Once the code passes validation and compilation, the system should run the Modelica simulation and collect the results. The workflow should also read and use relevant data from the generated files and tool outputs, while clearly reporting assumptions, missing information, errors, and final validation results. This complete automated workflow should be demonstrated on at least one supplied benchmark case.

## Work completed so far

- Text reader and two sample text specifications.
- OpenAI, Gemini, and Groq client configuration.
- AI extraction into a shared JSON Intermediate Representation (IR), plus schema/structural checks.
- Requirement traceability bookkeeping and audit report for facts, assumptions, and missing information.
- Deterministic SysML v2 generation with internal structural checks.
- AI-assisted Modelica source generation.
- CLI command and sequential pipeline connecting these stages.

## Current workflow: what the code does 

```text
command → main.py → pipeline.py → read specification
                                → create provider client
                                → extractor builds prompts and calls AI API
                                → parse/normalize JSON IR
                                → validate IR and check requirement traceability
                                → save IR and audit report
                                → generate/check SysML locally
                                → ask AI to generate Modelica
                                → save run summary and artifacts
```

The extraction API call is initiated in `backend/agent/extractor.py` via `client.complete(...)`. Provider-specific network calls are in `backend/agent/ai_client.py`. Modelica generation also calls the configured AI client. SysML is generated locally from the IR; no AI API call is needed for that step. If SysML generation fails, the pipeline skips Modelica generation.

## How the code is generated currently

### SysML v2

1. The AI extraction step creates a JSON model containing the system's components, ports, connections, parameters, and behavior.
2. `backend/generators/sysml_generator.py` reads that JSON and writes SysML statements for those elements. I generate SysML from the model in code; I do not ask the AI to write the SysML source.
3. The generator checks that expected elements and basic structure appear in the output, then saves a `.sysml` file.
4. I can open that file in a SysML tool for a manual check. A full parser check only runs when an external parser is configured, so a saved file is not automatically confirmed as valid SysML.

### Modelica

1. `backend/generators/modelica_generator.py` takes the same JSON model, makes a compact version, and places it in a Modelica prompt.
2. The prompt is sent to the configured AI model. The AI writes the Modelica source, and the program saves the response as a file.
3. Right now, the program checks only that the input has basic fields and the AI returned non-empty code. It does not compile or simulate that code; I have to check it manually in a Modelica tool. The saved filename may also be missing the `.mo` extension.

### Current Testing

I am currently testing the system using the test-case data provided in the PDF. The given requirements are used as input to check how the system processes the requirements and generates the corresponding SysML v2 and Modelica models.

## File and folder guide

| Path | Role / status |
|---|---|
| `backend/main.py` | **Created:** command-line entry point; starts the run or performs a readiness check. |
| `backend/pipeline.py` | **Created:** orchestrates input, extraction, validation, reports, and generation. |
| `backend/config.py` | **Created:** project paths and AI settings loaded from `.env`. |
| `backend/inputs/base.py` | **Created:** input document type and input error definitions. |
| `backend/inputs/text_reader.py` | **Created:** reads non-empty text files. Other formats are not supported yet. |
| `backend/agent/ai_client.py` | **Created:** shared AI client interface and OpenAI/Gemini/Groq adapters. |
| `backend/agent/extractor.py` | **Created:** sends specification to AI, parses and normalizes the response, and validates the IR. |
| `backend/agent/prompts.py` | **Created:** versioned extraction and generation prompts. |
| `backend/schema/system_schema.json` | **Created:** required JSON IR structure. |
| `backend/validators/structured_validator.py` | **Created:** schema and model structure/semantic checks. |
| `backend/validators/requirements.py` | **Created:** requirement ID/coverage bookkeeping checks; does not prove semantic satisfaction. |
| `backend/validators/review.py` | **Created:** facts, assumptions, and missing-information audit. |
| `backend/generators/sysml_generator.py` | **Created:** deterministic SysML v2 generation and internal structural checks; external parser is optional and must be configured. |
| `backend/generators/modelica_generator.py` | **Created:** AI-generated Modelica source; currently checks only basic IR shape and non-empty output, not Modelica compilation. |
| Separate specification/SysML/validation/simulation agent modules | **Not created:** planned modules/services if the project is expanded into independently orchestrated agents. |
| OpenModelica compiler/simulator integration | **Not created:** no current code invokes `omc`, checks `.mo` compilation, runs simulations, or produces plots/metrics. |
| `input/specification.txt` | **Present:** quasi-static magnetic-circuit text example. |
| `input/specification2.txt` | **Present:** two-tank sequence text example. |
| `docs/*.svg` | **Present:** visual reference files. |
| `output/` | **Present locally, ignored by Git:** generated examples/reports. Not validation evidence by themselves. |
| `AI-LOG.md`, `DECISIONS.md` | **Present:** development notes and decision history. |
| `.env` | **Local configuration:** contains API settings; keep secret and do not commit. |


## Setup and run

Python 3.10+ is recommended. There is no dependency lock file yet. Install the common packages and the SDK for your provider. Example for OpenAI:

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
python -m pip install openai python-dotenv jsonschema
```

For Gemini or Groq, also install the selected provider SDK (`google-generativeai` or `groq`). Create `.env` in the project root:

```dotenv
LLM_PROVIDER=openai
LLM_API_KEY=your_api_key_here
LLM_MODEL=gpt-4o
LLM_TEMPERATURE=0.0
LLM_TIMEOUT=60
```



```bash
python -m backend.main
```

Run the default specification through the pipeline:

```bash
python -m backend.main --run
```

Choose an input/provider/model:

```bash
python -m backend.main --run --spec input/specification2.txt
python -m backend.main --run --provider groq --model YOUR_GROQ_MODEL --spec input/specification.txt
python -m backend.main --help
```

Generated outputs go under `output/structured/`, `output/raw_responses/`, `output/sysml/`, `output/modelica/`, and `output/validation_errors/`. The current generator call may create Modelica output without a `.mo` suffix; fix this before passing the file to a compiler that expects that extension.


