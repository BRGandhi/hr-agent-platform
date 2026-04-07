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
Web Browser
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
  |     - suggest_visualizations
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
[server.py](server.py) is the main runtime for the modern web app.

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
- `POST /api/memories/{memory_id}/recall`: recall a saved chat insight without rerunning the original query
- `POST /api/feedback`: store `Yes` / `No` helpfulness feedback for a saved response
- `POST /api/reports/export/excel`: regenerate a scoped standard report and download it as an Excel-compatible workbook
- `GET /api/context/documents`: list retrieved context docs
- `POST /api/context/documents`: add context docs
- `GET /api/stats`: scoped KPI payload
- `POST /api/reset`: clear the current conversation session
- `POST /api/chat`: SSE chat stream

### 3.2 Web frontend
The browser frontend lives in [static/index.html](static/index.html), [static/app.js](static/app.js), and [static/style.css](static/style.css).

Responsibilities:
- authentication shell
- top-banner LLM connection
- scoped KPI display
- sidebar history and example prompts
- cached recall of saved chats
- clickable topic chips that expand into suggested follow-up questions
- SSE event consumption
- tool-call, chart, visual-option, table, markdown, similar-answer, report-export, and feedback rendering

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
2. The browser posts to `POST /api/chat` with message, provider, model, base URL, API key, session id, and optional latest-table context for follow-up visualization requests.
3. [server.py](server.py) resolves the authenticated user and access profile.
4. The server builds an `LLMConfig` object and gets or creates an `HRAgent`.
5. [agent/orchestrator.py](agent/orchestrator.py) performs:
   - scope validation
   - request routing (`data_query`, `report`, `policy`, `history_lookup`, `visual_follow_up`)
   - in-session conversation history lookup
   - short-follow-up resolution for replies such as `yes` or `job level`
   - recent and related memory lookup across stored user interactions
   - helpful-answer retrieval from previously upvoted responses
   - context document retrieval
   - system prompt construction
6. The selected LLM either:
   - returns tool calls, or
   - returns final text
7. Tool calls are executed through [agent/tool_executor.py](agent/tool_executor.py).
8. Tool results are appended back into the conversation history.
9. The loop continues until the model returns a final response or the iteration limit is hit.
10. Final answer, tool artifacts, and memory updates are streamed back to the UI.

### 4.3 Table action policy
The frontend now treats generated tables differently based on structure:
- standard reports use a `Download Excel` action
- small aggregate tables can expose `Visual options`
- larger employee-level or identifier-heavy tables render without a chart CTA

This avoids encouraging low-value charts for roster-style outputs while keeping guided visualization available for aggregated insights.

### 4.4 Saved-chat recall lifecycle
1. The user clicks a favorite, relevant, or past chat in the sidebar.
2. The browser calls `POST /api/memories/{memory_id}/recall` instead of posting the question back to `/api/chat`.
3. The server retrieves the saved chat from `context_store.db`, enforcing the current user's identity and allowed metric scope.
4. The API returns the stored `question`, `insight_summary`, metadata, and a session id.
5. The server primes the active `HRAgent` session with the original saved user/assistant pair.
6. The UI renders a `Recalled Insight` card in the chat surface.
7. Any follow-up such as `yes`, `show me`, or `break that down` continues from the recalled chat context.

## 5. Provider-Agnostic LLM Layer

[agent/llm_client.py](agent/llm_client.py) is the abstraction boundary between the orchestration loop and the upstream model provider.

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

[agent/orchestrator.py](agent/orchestrator.py) is the core controller.

Responsibilities:
- enforces question scope before the model is called
- loads user memory and allowed context documents
- builds the system prompt dynamically
- runs the tool-call loop
- stores final responses back into memory

Recent additions:
- preserves the latest generated table for visualization follow-ups
- emits helpful-memory events when prior upvoted answers match the current question
- emits report metadata so the frontend can choose between chart exploration and export actions
- primes the active session with recalled saved chats so recalled work behaves like live chat context
- uses stronger memory matching so relevant/history suggestions only surface for close semantic matches
- stores compact recall summaries alongside full answers for later sidebar recall and UX personalization
- routes metric-definition and calculation-explanation questions through the governed HR path instead of treating them as out-of-scope chatter
- promotes the anchored substantive HR question into saved memory when the live user turn is only a shorthand follow-up

The orchestrator uses `MAX_AGENT_ITERATIONS` from [config.py](../config.py) to limit runaway tool loops.

## 7. Access Control Model

[database/access_control.py](database/access_control.py) defines the current access policy model.

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

[database/context_store.py](database/context_store.py) provides two functions:

### 8.1 Conversation memory
- stores prior user question/response pairs
- stores a compact `insight_summary` alongside each saved response
- retrieves recent memory for the current user
- searches broader past interactions for related question/answer pairs
- stores per-response feedback so helpful answers can be reused as examples
- powers the sidebar history list
- powers saved-chat recall without rerunning the original query
- keeps favorite-chat ranking sensitive to reuse count and positive feedback
- filters thin shorthand follow-ups out of featured-history ranking so the UI keeps showing the real HR question

The context store now supports multiple retrieval modes:
- `recent_memory`: compact prompt context for the current turn
- `search_memories`: scored retrieval across prior chats
- `relevant_questions`: strict strong-match history for sidebar relevance
- `past_questions_for_sidebar`: broader cross-session history for the full past-chat list
- `get_memory`: authenticated recall lookup for a specific saved chat

Important retrieval behavior:
- memory search uses topic overlap, query coverage, and wording similarity rather than simple recency alone
- relevant-history suggestions require a strong match so the UI does not surface noisy prior chats
- past chats are retained indefinitely by default unless retention is explicitly enabled through configuration
- metric-explanation follow-ups inherit the latest meaningful HR anchor so methodology questions stay attached to the original result

### 8.2 Context document retrieval
- stores HR policies, schema notes, and metric definitions
- retrieves documents by token overlap and allowed tags
- injects matched content into the system prompt
- includes seeded snapshot-calculation guidance for promotion metrics such as `YearsSinceLastPromotion < 1`

The prompt builder in [agent/prompts.py](agent/prompts.py) merges:
- access profile
- recent memory
- related and helpful memory
- current follow-up context
- relevant context docs
- latest table context
- schema summary

## 9. Data Layer

### 9.1 `hr_data.db`
Primary analytics database used by [database/connector.py](database/connector.py). It contains the `employees` table loaded from the IBM HR dataset.

### 9.2 `access_control.db`
SQLite store mapping user emails to access profiles. It is currently seeded with demo identities for Microsoft, Google, and Okta sign-ins.

### 9.3 `context_store.db`
SQLite store for:
- conversation memory
- context documents

The conversation-memory table now acts as both:
- the long-term user memory store
- the cached recall store for saved prior answers

The context-store payload supports:
- sidebar history
- positive/negative feedback curation
- strict relevant-chat suggestions
- cached recall of prior insight summaries

## 10. Tool Layer

[agent/tools.py](agent/tools.py) declares the canonical tool schemas used by every provider.

Current tools:
- `search_past_chats`
- `search_context_documents`
- `query_hr_database`
- `calculate_metrics`
- `create_visualization`
- `suggest_visualizations`
- `get_attrition_insights`
- `generate_standard_report`

[agent/tool_executor.py](agent/tool_executor.py) implements their runtime behavior.

Important design choice:
- tools return structured JSON whenever possible so the UI can render tables and charts without guessing

## 11. UI State And Session Model

### Browser session state
[static/app.js](static/app.js) stores:
- current conversation session id
- selected provider/model/base URL
- tool-call visibility preference
- sidebar collapse state
- active favorite-topic filter

### Server session state
[server.py](server.py) stores:
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
- `CORS_ALLOWED_ORIGINS` must be locked to trusted internal domains per deployment
- `SECURE_COOKIES` should be enabled behind HTTPS in production
- dev SSO is a stub and not real OIDC or SAML integration
- sessions are in-memory rather than centralized
- SQLite is convenient but not the likely final persistence choice for enterprise usage
- automated tests are still limited

## 15. Recommended Next Architecture Steps

For a bank-internal deployment, the next architectural milestones should be:
1. Replace dev SSO with the bank identity provider.
2. Replace `access_control.db` with an authoritative enterprise mapping source.
3. Move session state to Redis or another shared store.
4. Move conversational memory and context documents to managed persistence.
5. Restrict CORS and enforce TLS.
6. Add audit logging for access decisions, SQL execution, and report generation.
