# Architecture

This document explains how the HR Insights Platform works end to end. It is written for engineers, architects, and platform owners who need to understand the current design before modifying or deploying the system.

## 1. System Intent

The platform is designed to answer HR analytics questions in a controlled way. The key design principle is that the system should not behave like a general-purpose chatbot. Instead, it should:
- accept only HR-related prompts
- restrict answers to the signed-in user's scope
- use deterministic tools for data access and reporting
- preserve useful memory and reference context
- remain portable across LLM providers

## 2. High-Level Component Map

```text
User
  |
  v
Web Browser / Streamlit
  |
  v
FastAPI server
  |
  +--> auth session handling
  +--> access profile lookup
  +--> scoped stats and history APIs
  +--> SSE chat streaming
  |
  v
HRAgent orchestrator
  |
  +--> question scope validation
  +--> memory retrieval
  +--> context document retrieval
  +--> prompt construction
  +--> LLM response loop
  |
  +--> tool execution
  |     - query_hr_database
  |     - calculate_metrics
  |     - create_visualization
  |     - get_attrition_insights
  |     - generate_standard_report
  |
  v
Data stores
  - hr_data.db
  - access_control.db
  - context_store.db
```

## 3. Runtime Surfaces

### 3.1 FastAPI web application
[server.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/server.py) is the main runtime for the modern web app.

Responsibilities:
- serves `static/` assets
- exposes auth, access, history, stats, context, and chat endpoints
- tracks in-memory auth sessions and agent sessions
- normalizes runtime model configuration
- streams tool events and final answers over SSE

Primary endpoints:
- `GET /`: serves the web app
- `GET /api/config`: LLM provider and model defaults
- `GET /api/auth/config`: auth shell settings
- `GET /api/auth/session`: current auth session
- `POST /api/auth/login`: dev-mode SSO login
- `POST /api/auth/logout`: logout
- `GET /api/me/access`: resolved user access profile
- `GET /api/me/history`: recent questions for sidebar history
- `GET /api/context/documents`: list retrieved context docs
- `POST /api/context/documents`: add context docs
- `GET /api/stats`: scoped KPI payload
- `POST /api/reset`: clear the current conversation session
- `POST /api/chat`: SSE chat stream

### 3.2 Web frontend
The browser frontend lives in [static/index.html](c:/Users/bhavy/Downloads/hr_agent_platform_github/static/index.html), [static/app.js](c:/Users/bhavy/Downloads/hr_agent_platform_github/static/app.js), and [static/style.css](c:/Users/bhavy/Downloads/hr_agent_platform_github/static/style.css).

Responsibilities:
- authentication shell
- top-banner LLM connection
- scoped KPI display
- sidebar history and example prompts
- SSE event consumption
- tool-call, chart, table, and markdown rendering

### 3.3 Legacy Streamlit frontend
[app.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/app.py) remains in the repo as a secondary interface. It is still useful for fast experiments, but it does not reflect the same governed auth and access model as the FastAPI + JS frontend.

## 4. Request Lifecycle

### 4.1 Browser load
1. The browser loads `/`.
2. The UI fetches `/api/config` and `/api/auth/config`.
3. If authentication is enabled, the UI checks `/api/auth/session`.
4. After sign-in, the UI loads:
   - `/api/me/access`
   - `/api/stats`
   - `/api/me/history`

### 4.2 Chat request lifecycle
1. The user enters a question.
2. The browser posts to `POST /api/chat` with message, provider, model, base URL, API key, and session id.
3. [server.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/server.py) resolves the authenticated user and access profile.
4. The server builds an `LLMConfig` object and gets or creates an `HRAgent`.
5. [agent/orchestrator.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/agent/orchestrator.py) performs:
   - scope validation
   - recent memory lookup
   - context document retrieval
   - system prompt construction
6. The selected LLM either:
   - returns tool calls, or
   - returns final text
7. Tool calls are executed through [agent/tool_executor.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/agent/tool_executor.py).
8. Tool results are appended back into the conversation history.
9. The loop continues until the model returns a final response or the iteration limit is hit.
10. Final answer, tool artifacts, and memory updates are streamed back to the UI.

## 5. Provider-Agnostic LLM Layer

[agent/llm_client.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/agent/llm_client.py) is the abstraction boundary between the orchestration loop and the upstream model provider.

### Anthropic path
- Uses native Anthropic tool-use blocks
- supports adaptive thinking
- handles Anthropic-specific authentication and connection errors

### OpenAI-compatible path
- uses the OpenAI SDK
- converts tool schemas to function-calling format
- supports local or hosted providers through `base_url`

The orchestrator does not need to know which provider is active. It only consumes normalized `LLMResponse` and `ToolCall` objects.

## 6. Orchestration Layer

[agent/orchestrator.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/agent/orchestrator.py) is the core controller.

Responsibilities:
- enforces question scope before the model is called
- loads user memory and allowed context documents
- builds the system prompt dynamically
- runs the tool-call loop
- stores final responses back into memory

The orchestrator uses `MAX_AGENT_ITERATIONS` from [config.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/config.py) to limit runaway tool loops.

## 7. Access Control Model

[database/access_control.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/database/access_control.py) defines the current access policy model.

Each access profile contains:
- `email`
- `role`
- `scope_name`
- `allowed_departments`
- `allowed_metrics`
- `allowed_doc_tags`

### Enforcement points

Question-level enforcement:
- non-HR questions are rejected
- metric domains are inferred from keywords
- requests for unauthorized metric domains are rejected

SQL-level enforcement:
- SQL is scanned for restricted columns
- department scope is applied by wrapping the `employees` table access

This means even if the LLM proposes a broader query, the execution layer still narrows the available data.

## 8. Context And Memory Layer

[database/context_store.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/database/context_store.py) provides two functions:

### 8.1 Conversation memory
- stores prior user question/response pairs
- retrieves recent memory for the current user
- powers the sidebar history list

### 8.2 Context document retrieval
- stores HR policies, schema notes, and metric definitions
- retrieves documents by token overlap and allowed tags
- injects matched content into the system prompt

The prompt builder in [agent/prompts.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/agent/prompts.py) merges:
- access profile
- recent memory
- relevant context docs
- schema summary

## 9. Data Layer

### 9.1 `hr_data.db`
Primary analytics database used by [database/connector.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/database/connector.py). It contains the `employees` table loaded from the IBM HR dataset.

### 9.2 `access_control.db`
SQLite store mapping user emails to access profiles. It is currently seeded with demo identities for Microsoft, Google, and Okta sign-ins.

### 9.3 `context_store.db`
SQLite store for:
- conversation memory
- context documents

## 10. Tool Layer

[agent/tools.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/agent/tools.py) declares the canonical tool schemas used by every provider.

Current tools:
- `query_hr_database`
- `calculate_metrics`
- `create_visualization`
- `get_attrition_insights`
- `generate_standard_report`

[agent/tool_executor.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/agent/tool_executor.py) implements their runtime behavior.

Important design choice:
- tools return structured JSON whenever possible so the UI can render tables and charts without guessing

## 11. UI State And Session Model

### Browser session state
[static/app.js](c:/Users/bhavy/Downloads/hr_agent_platform_github/static/app.js) stores:
- current conversation session id
- selected provider/model/base URL
- tool-call visibility preference

### Server session state
[server.py](c:/Users/bhavy/Downloads/hr_agent_platform_github/server.py) stores:
- `_sessions`: active `HRAgent` instances
- `_auth_sessions`: current auth sessions

Both are in-memory dictionaries with TTL cleanup. This is sufficient for local and small internal use, but not sufficient for resilient multi-instance deployment.

## 12. Trust Boundaries

The most important boundaries in the system are:

### User interface boundary
- untrusted user input enters through chat and auth-related requests

### Policy boundary
- access profile resolution
- metric-level and department-level scope enforcement
- HR-only question filtering

### Data boundary
- read-only SQL validation
- department-scoped query execution

### Model boundary
- the model can propose tools, but cannot bypass the Python execution layer

## 13. Current Strengths

- strong separation between orchestration and provider implementation
- clear place to attach real access-control sources
- deterministic tool interfaces
- useful path for internal HR reporting with controlled access

## 14. Current Gaps For A Bank Deployment

The following items should be treated as implementation gaps rather than documentation gaps:
- `allow_origins=["*"]` is too open for production
- auth cookies are not yet hardened for HTTPS-only enterprise use
- dev SSO is a stub and not real OIDC or SAML integration
- sessions are in-memory rather than centralized
- SQLite is convenient but not the likely final persistence choice for enterprise usage
- automated tests are limited

## 15. Recommended Next Architecture Steps

For a bank-internal deployment, the next architectural milestones should be:
1. Replace dev SSO with the bank identity provider.
2. Replace `access_control.db` with an authoritative enterprise mapping source.
3. Move session state to Redis or another shared store.
4. Move conversational memory and context documents to managed persistence.
5. Restrict CORS and enforce TLS.
6. Add audit logging for access decisions, SQL execution, and report generation.
