# Release Notes - 2026-04-16

This document captures the full product and codebase changes added after the last GitHub baseline on branch `codex/hr-intent-guardrail-fix`.

Baseline for this release note:
- latest committed baseline before this release wave: `903d8ae` (`Tighten contextual memory and metric explanations`)

This release materially expands the platform in five areas:
- personalized workspace and proactive insight UX
- simulated trend intelligence and period-based reporting
- governed export artifacts for Excel, PDF, and PowerPoint
- stronger visualization recommendation and rendering
- more accurate trend routing, follow-up handling, and memory tagging

## 1. Executive Summary

The platform has moved from a strong governed HR assistant into a more complete HR insights workspace.

The most important new outcomes are:
- the home screen and active chat now surface proactive, role-aware insight tiles
- users can customize, pin, hide, and reorder which KPI and insight tiles matter to them
- the product now ships with a 36-month simulated workforce trend layer for MoM, YoY, rolling-12, and tenure-mix analysis
- trend metrics are now integrated into KPI payloads, reports, exports, memory, and visualization flows
- standard exports now include a configurable Excel workbook builder
- insight surfaces can generate a one-page PDF brief and a PowerPoint deck
- visualization recommendations now go beyond bar and pie charts toward more consultant-style storytelling views
- direct trend-chart asks now route straight to chart generation instead of incorrectly triggering the report workflow

## 2. User-Facing Product Changes

### 2.1 Personalized home screen and chat workspace

The landing experience is no longer just a KPI strip plus starter prompts.

New behavior:
- the center board now surfaces proactive insight tiles based on role, past chats, current scoped data, and trend signals
- the active chat surface can keep those same insights visible near the conversation
- pinned tiles stay closer to the user's working context
- users can hide the `While You Chat` strip with a close control and restore it later through a compact `Show insight tiles` affordance

Why this matters:
- HR partners often need a quick analytical starting point before typing a fresh prompt
- keeping role-aware insights visible reduces navigation cost during iterative analysis
- allowing the strip to be dismissed reduces visual noise for users who want a cleaner chat surface

### 2.2 Customizable main panel and KPI catalog

The main panel is now user-configurable rather than a fixed default board.

New behavior:
- tiles can be pinned with a thumbtack icon instead of a text-heavy `Pin` label
- tiles can be hidden from the default workspace
- tile preferences persist in browser storage
- the configurable KPI catalog now includes a broader set of workforce measures, including:
  - active headcount
  - coverage in scope
  - attrited employees
  - retention rate
  - promotion rate
  - average salary hike
  - employees with 5+ years since promotion
  - rolling-12 promotion and trend-oriented KPI variants

Why this matters:
- users can shape the board around their role and recurring questions
- the board stays compact by default while still exposing a much richer catalog behind customization

### 2.3 HR-friendly copy and simplified controls

The center console language was simplified for HR partners and business users.

Changes include:
- shorter hero and tile copy
- less technical phrasing in the center board
- smaller, clearer CTAs
- pin controls rendered as icons rather than words
- cleaner, more readable main-panel and export-builder language

### 2.4 Sidebar defaults and history behavior

The left navigation now defaults to a more compact posture.

Updated behavior:
- the sidebar history sections load collapsed by default
- saved local storage no longer forces an unexpectedly expanded default on first login after the fix
- favorite, relevant, and past chat surfaces continue to use anchored substantive questions rather than thin shorthand follow-ups

## 3. Simulated Trend Intelligence

### 3.1 New simulated workforce history layer

The platform now includes a governed historical layer generated from the base IBM HR snapshot.

Implementation summary:
- 36 months of monthly workforce history ending in March 2026
- hiring assumption of 20% year over year
- monthly hires, exits, and promotions simulated within bounded variation
- logic constrained by base patterns in headcount mix, department mix, role mix, attrition risk, promotion propensity, overtime, and tenure
- synthetic new employees created without violating core logical relationships in the base dataset

Main data structures:
- `employees_monthly_history`
- `employees_trend_current`
- `workforce_monthly_events`
- `workforce_monthly_summary`
- `workforce_trend_latest_summary`

### 3.2 Trend metrics now integrated into the product contract

Trend data is no longer a sidecar experiment. It now feeds the runtime product.

Integrated measures include:
- month-over-month headcount change
- year-over-year headcount change
- monthly hiring rate
- monthly attrition rate
- monthly promotion rate
- rolling-12 hiring rate
- rolling-12 attrition rate
- rolling-12 promotion rate
- overtime share
- tenure distribution mix
- average years at company
- average years since last promotion

These metrics now show up in:
- `/api/stats`
- home-screen KPI tiles
- proactive insight tiles
- trend reports
- configured Excel exports
- visualization prompts and selected chart cards

### 3.3 Period-based reporting

Reports can now preserve reporting windows instead of flattening everything into a single snapshot mindset.

Supported trend report types:
- `workforce_trend`
- `headcount_trend`
- `attrition_trend`
- `promotion_trend`
- `tenure_distribution_trend`

Supported behavior:
- report requests can carry `period_months`
- configured Excel exports preserve that period selection
- quick Excel exports preserve the same reporting window
- downstream artifact builders read the same reporting context

### 3.4 Trend labeling and governance

The system is now explicit about the provenance of trend answers.

Required behavior now implemented:
- trend outputs should be labeled as simulated when sourced from the monthly history layer
- the data contract distinguishes the current snapshot from the simulated trend layer
- MoM and YoY values on the UI only render when the backend actually provides those fields

## 4. Reporting, Export, and Artifact Workflow

### 4.1 Configurable Excel builder

The product now exposes a governed Excel builder instead of only one-click report export.

Supported controls:
- column selection
- sort column
- sort direction
- filter column
- filter value
- max rows
- include summary sheet
- period selection for trend reports

Behavior details:
- the server route `/api/reports/export/excel-config` generates `.xlsx` output
- the builder can export the latest governed table or regenerate a standard report
- if the backend route is unavailable in a stale local runtime, the frontend now falls back to a local workbook build from the visible governed table context

### 4.2 Quick Excel export

The original report download path still exists and is still appropriate for standard roster-style reporting.

Current positioning:
- standard reports favor Excel, not charts
- period-based trend reports also support quick Excel export while preserving their time window

### 4.3 One-page PDF brief

The platform now supports one-page insight briefs.

Important workflow rule:
- the PDF one-pager is intended for insight surfaces, not generic report tables
- it should be used when the platform has already generated a meaningful insight story, chart, or analysis summary

Implementation summary:
- server endpoint: `/api/reports/export/pdf`
- shared artifact builder: `utils/report_artifacts.py`
- output style: compact executive brief with key metrics, insights, actions, and embedded chart storytelling

### 4.4 PowerPoint export

The platform also supports PowerPoint export for chart and insight surfaces.

Important workflow rule:
- the UI no longer frames this as `BCG PPT`
- PowerPoint should appear on chart-driven or selected-visual surfaces, not on plain table/report workflows

Implementation summary:
- server endpoint: `/api/reports/export/ppt`
- artifact builder composes styled story slides rather than dumping raw tables

## 5. Visualization Upgrade

The visualization flow has been expanded from a simple chart helper into a more deliberate recommendation engine.

New visual forms now supported in the stack:
- lollipop
- treemap
- bubble
- indicator

What changed:
- recommendation logic now favors more presentation-ready visual forms when the question and data structure support them
- chart storytelling metadata is richer
- selected chart cards can now expose PowerPoint export where appropriate

Why this matters:
- bar and pie charts are not sufficient for all workforce storytelling
- the platform now does a better job of matching visual form to business question

## 6. Trend-First Agent Routing and Accuracy Fixes

Several fixes were required so trend questions behave like trend questions instead of falling into generic report workflows.

### 6.1 Direct trend-chart routing

Simple asks such as:
- `show me a mom trend of attrition`
- `give me a yoy headcount trend`

should now:
- route directly to a chart-first trend path
- skip unnecessary report-builder clarification
- use the simulated trend series when appropriate

### 6.2 Better time-period parsing

The orchestrator now understands:
- `3 year`
- `3 years`
- `36 month`
- `36 months`

and maps them correctly into `period_months`.

### 6.3 Better metric alias handling

The orchestrator now normalizes metric shorthand such as:
- `promo`
- `promos`
- `promote`
- `promoted`
- `hc`

so the request resolves to the intended analytical measure.

### 6.4 Better entity alias handling

The trend flow now maps shorthand role phrases such as:
- `lab tech`
- `lab technician`

to the governed role name:
- `Laboratory Technician`

This allows filtered trend charts to reflect the actual requested slice.

### 6.5 Filtered trend rows from employee history

For filtered trend asks, the system can now build series from the employee-level monthly history and monthly event tables rather than only using the aggregate summary table.

That matters for requests such as:
- `show this 3 year promo trend for only lab tech`

which should now resolve to:
- promotion trend
- filtered to `Laboratory Technician`
- 36 months

## 7. Memory and Recall Changes

The context layer now treats trend work as a distinct category of saved work.

What changed:
- trend-like requests are now tagged into the derived `Workforce trends` topic family
- saved chat recall continues to use cached summaries, but those summaries now better reflect trend-oriented asks
- proactive tiles can use past trend-chat behavior to influence what surfaces next

Why this matters:
- trends should feel like a first-class analytical lane, not just another generic report
- memory-driven personalization is more useful when trend requests are separated from static snapshot requests

## 8. API and Backend Contract Changes

Important runtime changes:
- `/api/stats` now returns a trend-aware contract including `trend_summary`, `trend_series`, and derived MoM/YoY values
- `/api/reports/export/excel-config` now supports governed workbook building
- `/api/reports/export/pdf` now supports one-page insight briefs
- `/api/reports/export/ppt` now supports PowerPoint export for chart and insight surfaces

Important operational note:
- because the backend is a live in-memory FastAPI process, stale local servers can continue serving old routes and stale stats payloads until restarted
- several local issues observed during this release were caused by the browser picking up new assets before the backend process had been restarted

## 9. Frontend and UX Integration Notes

Important browser-side additions:
- customizable workspace modal
- pin/hide tile preferences
- thumbtack icon pin control
- dismissible `While You Chat` strip
- `Show insight tiles` restore control
- Excel builder modal
- chart-surface PowerPoint export controls
- trend-aware KPI and insight copy

Important browser-side safeguards:
- trend values no longer render as fake `0.0%` placeholders when the backend has not provided trend data
- Excel builder includes a local fallback when a stale backend returns `404` for the configured export route

## 10. Documentation and Repo Artifacts Added

New or newly important files in this release wave:
- `database/workforce_history.py`
- `utils/build_workforce_history.py`
- `utils/report_artifacts.py`
- `tests/test_report_artifacts.py`
- `tests/test_trend_integration.py`
- `tests/test_workforce_history.py`
- `docs/HR_Insights_Platform_Overview_Deck.pptx`
- `docs/HR_Insights_Platform_Deck_Speaker_Notes.md`

Updated core docs:
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_DICTIONARY.md`
- `docs/IMPLEMENTATION_GUIDE.md`
- `docs/RUNBOOK.md`
- `docs/CODE_LOG.md`
- `docs/PLATFORM_SPEC_2026-04-03.md`

## 11. Validation and Regression Coverage

The following regression areas were exercised during this release wave:
- trend integration
- trend routing and filtered role parsing
- visualization recommendations
- report artifact builders
- memory and personalization behavior
- workforce history generation

Representative commands used during development:

```bash
python -m unittest tests.test_chat_context tests.test_trend_integration
python -m unittest tests.test_history_personalization tests.test_report_artifacts tests.test_trend_integration tests.test_visualizations tests.test_workforce_history
python -m py_compile agent\orchestrator.py database\access_control.py tests\test_chat_context.py
```

## 12. Known Constraints And Next Steps

Important remaining constraints:
- the monthly trend layer is simulated, not sourced from a real HRIS event stream
- auth sessions and agent sessions are still in-memory
- SQLite remains the active persistence layer
- some browser-only interactions were smoke-tested through targeted fixes rather than a full end-to-end UI automation suite

Recommended next steps:
- move from simulated trends to a governed real historical workforce feed when available
- add stable artifact and table-context identifiers for richer downstream export provenance
- add end-to-end browser tests for export, trend, and personalization workflows
- move persistent UI preferences server-side if cross-device continuity becomes a requirement
