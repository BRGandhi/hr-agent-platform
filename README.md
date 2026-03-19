# HR Insights Platform

The HR Insights Platform is a governed HR analytics assistant designed to answer workforce questions, generate scoped reports, and visualize approved HR data through a controlled tool-using agent. The repository is intended as an internal-tooling foundation that can be adapted for a bank or other regulated enterprise environment.

This repo currently combines:
- a FastAPI backend and vanilla JS web frontend
- a legacy Streamlit interface for experimentation
- a provider-agnostic LLM layer that supports Anthropic and OpenAI-compatible endpoints
- role-based access controls tied to the signed-in user
- a context and memory layer for prior questions, HR policies, and schema notes
- deterministic guardrails that reject non-HR and out-of-scope requests

## Why This Project Exists

This codebase is aimed at a common internal-bank problem: teams want self-service HR analytics without exposing unrestricted raw people data or allowing a general-purpose chatbot to answer anything it wants. The platform constrains the AI experience to:
- HR-only scope
- department and metric level access controls
- traceable tool calls
- scoped metrics and reports
- configurable model providers

In other words, this is not a generic chat app. It is a governed HR analytics copilot pattern.

## Core Features

### 1. HR-only response policy
- The platform refuses non-HR prompts before the model does any meaningful work.
- Questions unrelated to workforce analytics, HR policy, headcount, attrition, or approved people-data use cases are returned as out of scope.

### 2. Role-based access control
- Access is resolved from the signed-in user email through `access_control.db`.
- Each user receives a role, scope name, allowed departments, allowed metric domains, and allowed document tags.
- SQL is checked against restricted columns and automatically department-scoped before execution.

### 3. Context and memory layer
- User-specific prior questions are stored in `context_store.db`.
- HR policy and schema reference documents are retrieved per question and injected into the system prompt.
- The UI surfaces previously asked questions in the sidebar.

### 4. Standard HR reports
- The agent can generate a scoped active headcount report.
- The agent can generate a scoped attrition report.
- The current demo dataset does not include real employee names, so employee-level reports use `EmployeeNumber`-derived labels.

### 5. LLM-agnostic orchestration
- Anthropic native tool use is supported.
- OpenAI-compatible chat-completions tool use is supported.
- Local models can be used through Ollama or any OpenAI-compatible gateway.
- Hosted providers such as Kimi-compatible endpoints can be connected without changing the agent loop.

### 6. Bank-friendly operating model
- The architecture separates model calls, access policy, SQL execution, and UI rendering into distinct layers.
- The repo is suitable as a reference implementation for internal deployment behind enterprise identity and network controls.
- The docs call out what is already in place and what still needs hardening for production in a regulated environment.

## Architecture At A Glance

```text
Browser UI / Streamlit
        |
        v
FastAPI server.py
  - auth session handling
  - request/session routing
  - SSE response streaming
        |
        v
HRAgent orchestrator
  - scope validation
  - memory retrieval
  - prompt construction
  - tool-use loop
        |
        +--> LLM adapter
        |     - Anthropic native tools
        |     - OpenAI-compatible tools
        |
        +--> Tool executor
              - query_hr_database
              - calculate_metrics
              - create_visualization
              - get_attrition_insights
              - generate_standard_report
        |
        v
SQLite stores
  - hr_data.db
  - access_control.db
  - context_store.db
```

For the full architecture walkthrough, see [docs/ARCHITECTURE.md](c:/Users/bhavy/Downloads/hr_agent_platform_github/docs/ARCHITECTURE.md).

## Fresh Start: Clone And Run

This is the fastest path for someone new to the project.

### Prerequisites
- Python 3.10 or newer
- `pip`
- one model endpoint:
  - Anthropic API key, or
  - any OpenAI-compatible endpoint, or
  - a local Ollama server
- the IBM HR Attrition CSV used by `setup_db.py`

### 1. Clone the repository

```bash
git clone https://github.com/BRGandhi/hr-agent-platform.git
cd hr-agent-platform
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it:
- Windows PowerShell: `.venv\Scripts\Activate.ps1`
- macOS/Linux: `source .venv/bin/activate`

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create your environment file

```bash
copy .env.example .env
```

Populate `.env` for either Anthropic or OpenAI-compatible usage.

Anthropic example:

```env
DEFAULT_LLM_PROVIDER=anthropic
DEFAULT_LLM_MODEL=claude-opus-4-6
ANTHROPIC_API_KEY=sk-ant-...
AUTH_REQUIRED=true
DEV_SSO_ENABLED=true
```

Local Ollama example:

```env
DEFAULT_LLM_PROVIDER=openai-compatible
DEFAULT_OPENAI_COMPAT_MODEL=llama3.1:8b
DEFAULT_OPENAI_COMPAT_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=
AUTH_REQUIRED=true
DEV_SSO_ENABLED=true
```

### 5. Prepare the dataset

Download the IBM HR dataset CSV and place it one folder above the repo, or update `CSV_PATH` in [config.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/config.py).

Then build the SQLite database:

```bash
python setup_db.py
```

### 6. Start the web server

```bash
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`.

### 7. Sign in and test

With the default dev SSO flow enabled, sign in using one of the seeded demo providers:
- Microsoft
- Google
- Okta

You should then see:
- a scoped KPI strip
- role-aware example questions
- previously asked questions in the sidebar
- the ability to connect an LLM provider from the top banner

For a much more detailed onboarding guide, see [docs/IMPLEMENTATION_GUIDE.md](c:/Users/bhavy/Downloads/hr_agent_platform_github/docs/IMPLEMENTATION_GUIDE.md).

## Repo Map

### Runtime entry points
- [server.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/server.py): FastAPI app and SSE backend
- [app.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/app.py): legacy Streamlit frontend
- [setup_db.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/setup_db.py): CSV-to-SQLite loader

### Agent layer
- [agent/llm_client.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/agent/llm_client.py): provider adapters
- [agent/orchestrator.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/agent/orchestrator.py): Think -> Act -> Observe loop
- [agent/prompts.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/agent/prompts.py): system prompt construction
- [agent/tool_executor.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/agent/tool_executor.py): tool implementations
- [agent/tools.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/agent/tools.py): tool schemas

### Data and policy layer
- [database/connector.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/database/connector.py): scoped SQLite query layer
- [database/access_control.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/database/access_control.py): role and scope resolution
- [database/context_store.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/database/context_store.py): memory and context docs
- [database/schema.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/database/schema.py): schema prompt reference

### Frontend
- [static/index.html](c:/Users/bhavy/Downloads/hr_agent_platform_github/static/index.html): web UI shell
- [static/app.js](c:/Users/bhavy/Downloads/hr_agent_platform_github/static/app.js): client behavior and SSE rendering
- [static/style.css](c:/Users/bhavy/Downloads/hr_agent_platform_github/static/style.css): visual system

## Documentation Guide

- [docs/ARCHITECTURE.md](c:/Users/bhavy/Downloads/hr_agent_platform_github/docs/ARCHITECTURE.md): detailed system architecture, trust boundaries, and request lifecycle
- [docs/IMPLEMENTATION_GUIDE.md](c:/Users/bhavy/Downloads/hr_agent_platform_github/docs/IMPLEMENTATION_GUIDE.md): fresh-clone setup and server deployment instructions
- [docs/RUNBOOK.md](c:/Users/bhavy/Downloads/hr_agent_platform_github/docs/RUNBOOK.md): day-2 operations, health checks, and incident handling
- [docs/DATA_DICTIONARY.md](c:/Users/bhavy/Downloads/hr_agent_platform_github/docs/DATA_DICTIONARY.md): logical data model and store definitions
- [docs/CODE_LOG.md](c:/Users/bhavy/Downloads/hr_agent_platform_github/docs/CODE_LOG.md): implementation history and major design decisions

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `DEFAULT_LLM_PROVIDER` | `anthropic` | Active provider family |
| `DEFAULT_LLM_MODEL` | `claude-opus-4-6` | Anthropic model id |
| `ANTHROPIC_API_KEY` | empty | Anthropic credential |
| `OPENAI_API_KEY` | empty | OpenAI-compatible provider credential |
| `DEFAULT_OPENAI_COMPAT_MODEL` | `llama3.1:8b` | OpenAI-compatible default model |
| `DEFAULT_OPENAI_COMPAT_BASE_URL` | `http://localhost:11434/v1` | OpenAI-compatible base URL |
| `SESSION_TTL_MINUTES` | `120` | Idle session cleanup window |
| `AUTH_REQUIRED` | `true` | Require sign-in before use |
| `DEV_SSO_ENABLED` | `true` | Enable demo SSO flow |
| `SSO_PROVIDERS` | `Microsoft,Google,Okta` | Providers shown on the login shell |
| `PORT` | `8000` | Backend port when using `server.py` or `uvicorn` |

Runtime-created stores:
- `hr_data.db`: employee analytics dataset
- `access_control.db`: user-to-scope mapping
- `context_store.db`: conversation memory and retrieved context docs

## Production Reality Check

This repository is useful as a bank-internal prototype or reference implementation, but it is not fully production-ready out of the box. Before deploying to a real internal bank environment, plan to address the following:

### Identity and session hardening
- Replace the dev SSO simulation with real OIDC or SAML
- Set secure cookie flags for HTTPS
- move auth sessions out of in-memory Python dictionaries

### Data and storage hardening
- Replace SQLite with enterprise-grade stores where needed
- move access control to an authoritative corporate source
- define retention and purge policies for stored conversation memory

### Network and API hardening
- tighten `allow_origins=["*"]` CORS in [server.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/server.py)
- use TLS termination and internal reverse proxies
- route provider credentials through approved secret-management tooling

### Platform operations
- centralize logs
- add request timeouts and rate limits
- add automated tests for auth, tooling, access controls, and SSE flows

These gaps are documented in more detail in [docs/RUNBOOK.md](c:/Users/bhavy/Downloads/hr_agent_platform_github/docs/RUNBOOK.md) and [docs/IMPLEMENTATION_GUIDE.md](c:/Users/bhavy/Downloads/hr_agent_platform_github/docs/IMPLEMENTATION_GUIDE.md).
