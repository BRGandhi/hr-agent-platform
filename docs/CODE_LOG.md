# Code Log

This file records the major architectural changes and implementation milestones in the repository. It is intended to help future maintainers understand not only what changed, but why it changed.

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
- kept Streamlit as a secondary interface

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
