# HR Insights Platform

The HR Insights Platform is a governed HR analytics assistant designed to answer workforce questions, generate scoped reports, and visualize approved HR data through a controlled tool-using agent. The repository is intended as an internal-tooling foundation that can be adapted for a bank or other regulated enterprise environment.

This repo currently combines:
- a FastAPI backend and vanilla JS web frontend
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
- The orchestrator now searches broader past interactions for related answers, not just the most recent turns.
- Users can upvote or downvote responses, and positively rated answers can be surfaced later for similar questions.
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

### 6. Stronger visualization workflow
- The agent can render polished Plotly visuals for approved HR data.
- When a user asks to convert a generated table into a visual, the agent can now return multiple chart options and recommend the strongest view.
- The web UI preserves the latest table context so follow-up prompts such as "turn that into a chart" work more reliably.

### 7. Bank-friendly operating model
- The architecture separates model calls, access policy, SQL execution, and UI rendering into distinct layers.
- The repo is suitable as a reference implementation for internal deployment behind enterprise identity and network controls.
- The docs call out what is already in place and what still needs hardening for production in a regulated environment.

### 8. Guided question discovery
- Topic chips on the home screen are clickable and now expand into sample questions for that metric or workflow.
- Similar-question matches can show previously helpful answers before the agent generates a fresh response.
- Assistant responses include `Yes` / `No` helpfulness controls so teams can curate strong examples over time.

## New Agent Features

The newest generation of the agent is optimized around governed follow-up work instead of one-off answers.

- Broader memory retrieval: the orchestrator now searches prior user interactions for relevant answers, not just the last few turns.
- Helpful-answer reuse: positively rated responses can be surfaced when a later question looks similar.
- Guided discovery UX: empty-state topic chips expand into sample scoped prompts so users can explore approved HR workflows faster.
- Table-aware visualization flow: when a user asks to turn a generated table into a chart, the latest table context is preserved and reused automatically.
- Visualization gating: `Visual options` is now reserved for smaller aggregate tables that are actually chartable.
- Report export flow: standard employee-level reports now favor `Download Excel` instead of a chart CTA.
- Inline feedback loop: each assistant answer supports `Yes` / `No` helpfulness feedback for future curation.

## Architecture At A Glance

```text
Browser UI
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
              - suggest_visualizations
              - get_attrition_insights
              - generate_standard_report
        |
        v
SQLite stores
  - hr_data.db
  - access_control.db
  - context_store.db
```

For the full architecture walkthrough, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

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

You can provide API keys either in `.env` or directly in the Connect LLM modal.

### 5. Prepare the dataset

Download the IBM HR dataset CSV and place it one folder above the repo, or update `CSV_PATH` in [config.py](config.py).

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
- clickable topic chips that expand into sample prompts
- previously asked questions in the sidebar
- `Yes` / `No` helpfulness controls after assistant responses
- the ability to connect an LLM provider from the top banner

For a much more detailed onboarding guide, see [docs/IMPLEMENTATION_GUIDE.md](docs/IMPLEMENTATION_GUIDE.md).

## Repo Map

### Runtime entry points
- [server.py](server.py): FastAPI app and SSE backend
- [setup_db.py](setup_db.py): CSV-to-SQLite loader

### Agent layer
- [agent/llm_client.py](agent/llm_client.py): provider adapters
- [agent/orchestrator.py](agent/orchestrator.py): Think -> Act -> Observe loop
- [agent/prompts.py](agent/prompts.py): system prompt construction
- [agent/tool_executor.py](agent/tool_executor.py): tool implementations
- [agent/tools.py](agent/tools.py): tool schemas

### Data and policy layer
- [database/connector.py](database/connector.py): scoped SQLite query layer
- [database/access_control.py](database/access_control.py): role and scope resolution
- [database/context_store.py](database/context_store.py): memory and context docs
- [database/schema.py](database/schema.py): schema prompt reference

### Frontend
- [static/index.html](static/index.html): web UI shell
- [static/app.js](static/app.js): client behavior and SSE rendering
- [static/style.css](static/style.css): visual system

## Documentation Guide

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): detailed system architecture, trust boundaries, and request lifecycle
- [docs/IMPLEMENTATION_GUIDE.md](docs/IMPLEMENTATION_GUIDE.md): fresh-clone setup and server deployment instructions
- [docs/RUNBOOK.md](docs/RUNBOOK.md): day-2 operations, health checks, and incident handling
- [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md): logical data model and store definitions
- [docs/CODE_LOG.md](docs/CODE_LOG.md): implementation history and major design decisions

## Change Logging

Repository change history is tracked in [docs/CODE_LOG.md](docs/CODE_LOG.md).

Recommended practice for future updates:
- add one top-level version entry per feature cluster or release-sized change
- capture both the user-visible behavior and the architectural reason behind the change
- update README and architecture docs whenever a changelog entry introduces a new runtime capability

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
| `SECURE_COOKIES` | `false` | Set auth cookies as HTTPS-only; enable in production |
| `SSO_PROVIDERS` | `Microsoft,Google,Okta` | Providers shown on the login shell |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` | Allowed browser origins |
| `RATE_LIMIT_MAX_REQUESTS` | `20` | Chat requests allowed per IP in the rate-limit window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Length of the rate-limit window |
| `LLM_TIMEOUT_SECONDS` | `60` | Upstream LLM request timeout |
| `MAX_CONVERSATION_HISTORY` | `40` | Sliding window size for agent conversation history |
| `MEMORY_RETENTION_DAYS` | `90` | How long conversation memory is retained |
| `PORT` | `8000` | Backend port when using `server.py` or `uvicorn` |

Runtime-created stores:
- `hr_data.db`: employee analytics dataset
- `access_control.db`: user-to-scope mapping
- `context_store.db`: conversation memory and retrieved context docs

## Production Reality Check

This repository is useful as a bank-internal prototype or reference implementation, but it is not fully production-ready out of the box. Before deploying to a real internal bank environment, plan to address the following:

### Identity and session hardening
- Replace the dev SSO simulation with real OIDC or SAML
- set `SECURE_COOKIES=true` behind HTTPS
- move auth sessions out of in-memory Python dictionaries

### Data and storage hardening
- Replace SQLite with enterprise-grade stores where needed
- move access control to an authoritative corporate source
- define retention and purge policies for stored conversation memory

### Network and API hardening
- set `CORS_ALLOWED_ORIGINS` to your real internal domains
- use TLS termination and internal reverse proxies
- route provider credentials through approved secret-management tooling

### Platform operations
- centralize logs
- add automated tests for auth, tooling, access controls, and SSE flows
- consider moving the in-memory rate limiter to shared infrastructure for multi-instance deployments

These gaps are documented in more detail in [docs/RUNBOOK.md](docs/RUNBOOK.md) and [docs/IMPLEMENTATION_GUIDE.md](docs/IMPLEMENTATION_GUIDE.md).
