# Code Log

This file records the major architectural changes and implementation milestones in the repository. It is intended to help future maintainers understand not only what changed, but why it changed.

## v1.10 - Anchored Follow-Ups, Reuse-Weighted Favorites, And Calculation Explanations

Summary:
- tightened personalization so favorite and featured questions reflect the substantive HR ask rather than thin shorthand follow-ups
- upgraded favorite-chat scoring to reward both repeated reuse and positive feedback
- added a governed explanation path for calculation-definition questions such as how a metric was derived, which columns were used, and what snapshot caveats apply

Key agent and memory changes:
- the orchestrator now recognizes metric-explanation requests as in-scope HR follow-ups instead of routing them into the generic guardrail
- shorthand turns such as `answer question 1` now save under the anchored prior HR question when they are effectively just follow-up selectors
- favorite-question ranking now aggregates reuse count across duplicate asks rather than keeping only a single latest row
- featured-history surfaces now filter thin shorthand follow-ups so the center board and favorite chats stay readable

Key UX and documentation changes:
- center-board prompt cards now favor substantive recent history over placeholder follow-up fragments
- feedback actions immediately refresh personalized history so favorite and relevant chat sections update in the same session
- README, architecture, data-dictionary, and product-spec docs now describe the new methodology-explanation and anchored-history behavior

Why this mattered:
- demo users expect to ask `how did you calculate that?` and receive a governed explanation, not a report-builder prompt or a scope refusal
- favorite surfaces lose credibility quickly when they feature `yes` or `answer question 1` instead of the real business question
- reuse and feedback are stronger signals of value than simple recency for personalized navigation

## v1.9 - Agentic Context Retrieval, Cached Recall, And Personalized Navigation

Summary:
- expanded the governed HR assistant into a richer agentic retrieval system that combines session context, long-term user memory, approved HR documents, and latest-table follow-up context
- upgraded the sidebar and home-screen UX around favorite topics, favorite chats, relevant chats, and full past-chat history
- introduced cached saved-chat recall so users can reopen prior work without rerunning the original question

Key agent and memory changes:
- the orchestrator now routes requests into distinct modes such as `data_query`, `report`, `policy`, `history_lookup`, and `visual_follow_up`
- short replies such as `yes`, `job level`, and `show me` inherit prior HR context before access validation runs
- the context store now saves `insight_summary` alongside the full assistant response
- memory retrieval now supports strong-match relevance scoring based on topic overlap, wording similarity, and query coverage
- relevant-history suggestions are intentionally stricter so the system avoids noisy broad-memory recommendations
- saved chat recall now primes the live session with the original Q&A so follow-ups continue naturally

Key UX and product changes:
- the home screen now leads with platform capabilities, then a personalized KPI/prompt board
- center-board cards were rebalanced for stronger hierarchy and more compact sizing
- the sidebar now separates favorite topics, favorite chats, relevant chats, and past chats into collapsible sections
- `Past Chats` now reads from dedicated full-history data rather than a small recent/relevant subset
- clicking favorite/relevant/past chats now recalls the stored insight summary instead of rerunning the question

Data and documentation outcomes:
- conversation memory is retained indefinitely by default unless retention is explicitly configured
- README, architecture, and data-dictionary docs now describe the agentic retrieval, context, and recall layers in more operational detail
- the project documentation now better explains how `context_store.db` functions as both prompt memory and recall cache

Why this mattered:
- reopening prior work should feel instantaneous and contextual, not like a duplicate fresh query
- history suggestions must be high-signal to improve trust rather than clutter the workspace
- the repo needed clearer documentation of the data, memory, and recall architecture as the product moved from simple memory to a more intentional agentic context layer

## v1.8 - Memory-Aware Agent UX, Visualization Controls, And Report Export

Summary:
- expanded the agent from recent-turn memory into broader past-interaction retrieval with reusable helpful answers
- upgraded the web UX with guided topic exploration, response feedback capture, and more intentional visualization/report actions
- tightened report and visualization behavior so roster-style outputs download cleanly while aggregate tables still support chart exploration

Key agent and UX additions:
- the orchestrator now searches stored user interactions for related question/answer pairs before answering
- positively rated responses can be surfaced as helpful examples for similar future questions
- assistant responses now include `Yes` / `No` feedback controls backed by `conversation_memory.feedback_score`
- home-screen topic chips now expand into sample scoped HR questions
- visualization follow-ups continue to inherit the latest generated table context
- visualization option cards remain available for small aggregate tables, but not for large roster or report-style tables
- standard reports now present a `Download Excel` action instead of a visualization CTA

Reporting and export changes:
- standard reports continue to run through `generate_standard_report`
- the backend now exposes an authenticated Excel export path for standard reports
- report previews can show truncated row counts in the UI while the export regenerates the full scoped report server-side

Documentation outcomes:
- README now includes clearer change-log guidance and a dedicated new-agent-features section
- architecture and implementation docs now describe feedback capture, broader memory retrieval, report export, and visualization gating
- data dictionary and runbook documentation now reflect the richer memory model and operational checks

Why this mattered:
- recent conversations and positively rated answers are high-signal context for a governed internal analytics assistant
- users needed clearer affordances: charts for aggregates, exports for rosters, and guided prompts for discovery
- the repo needed an explicit release narrative so future maintainers can understand the cluster of related frontend, orchestration, and reporting changes together

## v1.7 - Security Tightening And Browser API Key Support

Summary:
- tightened several auth and access-control paths after the FastAPI-only migration
- restored direct API key entry in the web UI while keeping environment keys as a supported fallback
- refreshed the docs to match the current runtime behavior

Key fixes and updates:
- fixed local cookie defaults so dev sign-in works over plain HTTP
- changed unknown access profiles from a server error into a controlled 403 response
- hardened department scoping so lowercase SQL does not bypass or break scoped queries
- restricted context-document endpoints to the caller's allowed document tags
- restored optional API key entry in the Connect LLM modal and request payload
- updated README, architecture, implementation, and runbook docs to match the live platform

Why this mattered:
- the security hardening introduced a few regressions in local usability and access handling
- the browser UI had lost a workflow that was still useful for developer testing
- the docs needed to reflect the current agent contract, not an intermediate refactor state

## v1.6 - Legacy Streamlit Removal

Summary:
- removed the obsolete Streamlit frontend and its leftover deployment references
- aligned the repo around a single supported runtime: FastAPI plus the browser UI

Files and surfaces removed or updated:
- removed `app.py`
- removed `.streamlit/` configuration files
- removed the `streamlit` dependency from `requirements.txt`
- updated Windows launchers to start `uvicorn` instead of Streamlit
- updated `Dockerfile` and `render.yaml` to target the FastAPI app

Why this change was made:
- the Streamlit app no longer matched the live agent contract
- it required a different auth and session story than the supported web product
- leaving it in the repo created onboarding confusion and stale deployment paths

## v1.5 - Documentation Refresh For Internal Deployment

Summary:
- rewrote repository documentation to match the current governed HR platform
- added architecture and onboarding guidance for engineers new to the repo
- documented the system as an internal-tooling foundation for a bank or other regulated environment

Key documentation outcomes:
- README now explains the current platform, not the earlier prototype
- architecture is documented in a dedicated guide
- implementation and runbook docs now distinguish demo defaults from bank-ready expectations
- data dictionary now covers all three SQLite stores instead of only the HR dataset

Why this matters:
- the code had evolved faster than the docs
- new engineers needed a realistic clone-and-run path
- deployment stakeholders needed clarity on what is already governed and what still needs hardening

## v1.4 - Governed HR Platform Upgrade

Summary:
- transformed the app from a general HR analytics assistant into a governed HR-only platform
- introduced role-based access control, context memory, standard reports, and a modernized web UI

Major changes:
- added `database/access_control.py`
- added `database/context_store.py`
- updated `server.py` with auth-aware access lookup, history, and context endpoints
- updated `agent/orchestrator.py` to enforce scope before model execution
- updated `agent/prompts.py` to inject access, memory, and retrieved documents
- updated `database/connector.py` to apply department scoping
- added standard report generation through `generate_standard_report`
- updated the web UI to show scoped metrics, history, and provider controls in the top banner

Design rationale:
- internal HR tools need explicit scope enforcement
- memory and policy retrieval increase answer quality without widening the model's freedom
- provider abstraction prevents the rest of the agent loop from depending on a single vendor

## v1.3 - FastAPI And Vanilla JS Frontend

Summary:
- introduced the FastAPI backend and browser UI

Why the change was made:
- the browser UI allows better streaming, richer cards, and clearer control over auth and scope
- SSE is a good fit for one-way streamed agent responses
- vanilla JS kept the frontend lightweight and easy to deploy without a Node toolchain

Architectural notes:
- `server.py` became the runtime entry point for the primary app
- `static/index.html`, `static/app.js`, and `static/style.css` formed the browser interface
- in-memory server-side sessions were introduced for conversation continuity

## v1.2 - Visual Refresh And Interaction Improvements

Summary:
- improved the frontend presentation and chart rendering experience

Why it mattered:
- the platform was intended for stakeholder-facing demos and internal adoption
- charts, KPI cards, and clearer interaction patterns made the output more useful for non-engineers

## v1.1 - Compatibility And Packaging Fixes

Summary:
- addressed environment issues encountered during setup and testing

Examples:
- package installation fixes
- UI adjustments
- deployment script cleanup

## v1.0 - Initial Release

Summary:
- established the first working HR analytics agent prototype

Core concepts introduced:
- tool-based HR analytics agent
- SQLite-backed dataset
- prompt-driven SQL generation
- report and visualization helpers

Initial design choices:
- keep dependencies light
- avoid heavy agent frameworks
- use Python-native tools and a straightforward orchestration loop

## Ongoing Technical Debt

The following items remain important for future maintainers:
- replace dev SSO with real enterprise identity
- replace in-memory auth and chat sessions with shared persistence
- restrict CORS for production
- add automated tests across auth, access control, and tool flows
- decide whether SQLite remains appropriate for long-term internal-bank use
- harden audit logging and secrets management
