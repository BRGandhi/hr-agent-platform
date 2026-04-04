# Platform Spec - 2026-04-03

This document summarizes the product, agent, context-layer, data, and UI changes completed on April 3, 2026.

It is intended to be the single spec-style reference for the current release wave, not just a changelog. It reflects:
- shipped work in commits `904e9cb`, `a1d6a80`, and `db78874`
- the current workspace UI default-state update where `Favorite Topics` opens by default and the other sidebar history sections start collapsed

## 1. Product Intent

The HR Insights Platform is a governed HR analytics workspace for HR leaders and partners. The system is designed to:
- answer HR-only questions
- generate workforce reports
- produce visualizations from approved HR data
- surface saved insights from prior work
- maintain useful conversation continuity without behaving like a generic chatbot

The target user experience is closer to an executive HR analytics assistant than a raw prompt box.

## 2. Release Summary

The April 3 release wave delivered four major outcomes:
- a more agentic retrieval and routing flow before the final answer is generated
- a stronger context and memory layer with durable history, strict relevance, and cached recall
- a more personalized product surface across the home screen, sidebar, and in-chat follow-ups
- a more polished HR-leader UI with clearer KPI language, cleaner response rendering, and tighter navigation defaults

## 3. Functional Scope Added Or Refined Today

### 3.1 Personalized HR workspace

The landing state now acts like a personalized HR workspace rather than a blank chat shell.

Required behavior:
- the center board must highlight KPIs and next questions based on the user's prior HR activity
- headcount must be the first KPI shown when headcount access is available
- additional KPI families should appear only when the user has actually asked about them before
- remaining board slots should be filled with concrete prompt cards phrased as real questions
- prompt cards should emphasize the question itself, with the CTA rendered as a secondary action

### 3.2 Sidebar as a memory navigation surface

The sidebar is now a first-class navigation and recall surface.

Required order:
- `New Conversation`
- `Favorite Topics`
- `Favorite Chats`
- `Relevant Chats`
- `Past Chats`
- `Settings`

Required default state:
- `Favorite Topics` is expanded by default
- `Favorite Chats`, `Relevant Chats`, and `Past Chats` are collapsed by default
- collapse state persists in browser storage once the user changes it

### 3.3 HR leader copy pass

User-facing copy now needs to speak to an HR leadership audience instead of using internal technical language.

Required language behavior:
- prefer `business units`, `workforce`, `total headcount`, `active headcount`, and `attrition`
- avoid overusing `scope` or `scoped` in visible UI copy
- describe access in business language such as approved business units and measures
- keep governance language present but not dominant

Examples now reflected in the UI:
- `Total headcount`
- `Active headcount`
- `Attrition rate`
- `Avg time to promotion`

## 4. Agent And Orchestration Specification

### 4.1 Agent model

The platform uses a governed tool-using HR agent rather than a single prompt template.

Core orchestration responsibilities:
- reject non-HR questions before meaningful model work begins
- resolve the signed-in user's role and approved business coverage
- assemble memory, context documents, and latest-table context before the answer loop
- route the request into the right handling mode
- execute tools iteratively until a final answer is returned

### 4.2 Request routing

The orchestrator now classifies requests into specialized modes before tool execution.

Supported route patterns include:
- `data_query`
- `report`
- `policy`
- `history_lookup`
- `visual_follow_up`

Expected effect:
- database questions should prioritize HR SQL tools
- policy questions should prioritize approved document retrieval
- history and recall flows should avoid unnecessary reruns
- visualization follow-ups should reuse the latest available table context

### 4.3 Short follow-up continuity

Short replies must behave like true follow-ups, not new standalone prompts.

Supported examples:
- `yes`
- `show me`
- `break it down`
- `job level`

Required behavior:
- if the active session contains a recent substantive HR turn, the short reply inherits that context
- if the live session anchor is missing or thin, the agent can fall back to the user's recent stored memory
- access validation must run on the resolved HR intent, not on the raw one-word reply in isolation

## 5. Tooling And Agentic Retrieval Specification

### 5.1 Tool categories

The platform now combines direct data tools with retrieval tools.

Current tooling model:
- workforce data access and calculation tools for reports and metrics
- visualization suggestion and generation tools for chart follow-ups
- memory retrieval tools for prior chat lookup
- context-document retrieval tools for policies, schema, and metric definitions

Notable retrieval tools introduced into the agent loop:
- `search_past_chats`
- `search_context_documents`

Expected behavior:
- the agent should use targeted retrieval instead of prompt-stuffing broad history every turn
- retrieval should stay narrow and relevant
- saved memory should support both answer generation and explicit recall

### 5.2 Helpful-answer reuse

The system can now use previously helpful answers as high-signal examples.

Required behavior:
- `Yes` and `No` feedback is stored against saved responses
- positively rated or repeatedly reused answers can influence future recommendations
- helpful prior answers should only surface when the current question is genuinely close, not just loosely related

## 6. Context And Memory Layer Specification

### 6.1 Durable memory

Conversation history is now durable by default.

Required behavior:
- past chats are retained indefinitely unless retention is explicitly configured later
- memory is stored per signed-in user
- memory must support both prompt-time retrieval and direct recall

### 6.2 Stored memory model

Each saved interaction now stores more than just raw question and answer text.

Each memory record should include:
- original question
- full response
- compact `insight_summary`
- timestamps
- feedback score
- topic labels where available

### 6.3 Strict relevance

Prior chat recommendations should be intentionally strict.

Required behavior:
- `Relevant Chats` must only surface when prior questions are very close in wording and topic
- broad KPI similarity alone is not enough
- if no strong match exists, the UI should show nothing rather than low-quality suggestions

### 6.4 Cached recall instead of rerun

Clicking a saved chat should reopen the saved insight, not rerun the original question.

Required behavior:
- sidebar clicks use a recall path instead of posting the old question back through standard chat
- the recalled interaction should render a saved summary in the conversation surface
- the original Q&A should seed the active session so a new follow-up continues naturally from recalled context
- recall should enforce the current signed-in user and current access rules

### 6.5 Sidebar memory buckets

The sidebar now separates memory into four distinct navigation modes.

Definitions:
- `Favorite Topics`: the HR themes the user revisits most often
- `Favorite Chats`: the user's strongest prior work based on reuse and feedback
- `Relevant Chats`: strict role-aware and topic-aware matches
- `Past Chats`: the broader cross-session question history for the signed-in user

## 7. Data And Access Specification

### 7.1 Current demo data model

The current platform runs on the original IBM HR attrition dataset.

Current assumptions:
- the analytics dataset is a single current-state snapshot
- the system should not claim month-over-month or rolling-12-month insight from synthetic panel data
- employee-level outputs rely on `EmployeeNumber` rather than real employee names

### 7.2 Current workforce KPIs

The home screen and top summaries now emphasize executive-style workforce metrics.

Primary KPIs in the current product:
- total headcount
- active headcount
- attrited employees
- attrition rate
- promoted in last year
- average time to promotion

KPI presentation rule:
- headcount is always the anchor KPI when available

### 7.3 Access enforcement

The platform remains governed and role-based.

Required enforcement:
- only HR and workforce analytics use cases are supported
- answers are restricted to approved business units
- answers are restricted to approved HR measure domains
- restricted requests are blocked rather than partially answered

## 8. Home Screen And Center Board UI Specification

### 8.1 Hero state

The empty state should introduce the platform in product language first.

Required message order:
- first explain that the platform generates reports, visualizations, and insights from HR data
- then explain that the board is personalized by prior HR questions

### 8.2 KPI board

The center board is now the primary discovery surface.

Required design behavior:
- use compact KPI cards rather than oversized panels
- use larger number treatment for KPI values
- keep the KPI label and note readable for an HR leadership audience
- keep cards visually balanced with the composer beneath them
- remove internal-sounding helper text such as `Pinned first...`

### 8.3 Prompt cards

Prompt cards should work like intelligent next-step recommendations.

Required behavior:
- the actual question is the most visually prominent text
- CTA text is smaller and secondary
- generic giant `Ask` or `Explore` treatments should not dominate the card
- the prompts should reflect current access and prior interests

## 9. Sidebar UI Specification

### 9.1 Navigation behavior

The sidebar should function as a compact executive navigation rail.

Required behavior:
- `New Conversation` appears at the top
- history sections are collapsible
- DB status and tool-call toggles live inside `Settings`
- favorite topics appear above all chat-history sections

### 9.2 Content behavior

Required copy and interaction behavior:
- topic chips are clickable
- clicking a topic filters favorite chats to that theme
- saved chat buttons should use the question as the button label
- weakly related past questions should not appear under `Relevant Chats`

## 10. Top Bar Specification

The top bar now uses compact information chips with reveal content.

Required chips:
- role
- coverage
- access
- model
- my KPIs

Required reveal behavior:
- hover and click affordances should feel compact and lightweight
- copy should explain the user's role, business coverage, access envelope, current model, and history-shaped measures
- the top row should avoid long raw text strings

## 11. Chat Surface Specification

### 11.1 Response rendering

The response UI has been upgraded toward a more mature assistant experience.

Required rendering behavior:
- preserve clean Markdown structure
- support short sections, bullets, tables, quotes, links, and code blocks
- render metric-heavy outputs in a scannable way
- provide copy affordances for answer content where appropriate
- maintain strong visual hierarchy and spacing closer to mature platforms like ChatGPT and Anthropic

### 11.2 In-chat memory behavior

The chat surface must preserve thread continuity.

Required behavior:
- a short follow-up after a generated answer continues the current thread
- a short follow-up after a recalled saved chat continues the recalled thread
- the latest table remains available for visual follow-ups when appropriate

## 12. API And Backend Surface Changes From Today

Important backend and API behaviors in today's release wave:
- `GET /api/me/history` now supports richer personalized sidebar payloads
- `POST /api/memories/{memory_id}/recall` returns saved insight summaries without rerunning the original query
- memory retention defaults to keep history indefinitely
- history lookup and relevance scoring are stricter and more intentional

## 13. Current Acceptance Criteria

The product should be considered consistent with today's spec when all of the following are true:
- the home screen leads with HR reports, visualizations, and insights
- the center board shows headcount first and uses HR-leader KPI labels
- saved chats recall cached insights instead of rerunning SQL
- `yes` and similar short replies continue the active or recalled HR thread
- `Relevant Chats` is intentionally sparse unless a close historical match exists
- `Past Chats` reflects broader cross-session history
- `Favorite Topics` is open by default and other sidebar history sections start collapsed
- visible UI copy avoids overusing `scope` and instead speaks in business-unit and workforce terms

## 14. Files Most Directly Affected By Today's Work

Primary product and runtime files:
- `server.py`
- `config.py`
- `agent/orchestrator.py`
- `agent/prompts.py`
- `agent/tool_executor.py`
- `agent/tools.py`
- `database/context_store.py`
- `database/connector.py`
- `setup_db.py`
- `static/index.html`
- `static/app.js`
- `static/style.css`

Primary tests and docs updated during today's work:
- `tests/test_chat_context.py`
- `tests/test_history_personalization.py`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_DICTIONARY.md`
- `docs/CODE_LOG.md`

## 15. Notes For Future Work

Areas intentionally left for future refinement:
- replace in-memory auth and chat session storage with shared persistent session state
- deepen true semantic ranking for history relevance beyond the current strong-match heuristic
- expand the recall model from compact summaries into richer structured insight objects if needed
- add more formal UI acceptance tests for personalized navigation and recall behavior
- decide whether a larger production data model should replace the current demo snapshot dataset
