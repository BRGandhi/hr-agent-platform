# Implementation Guide

This guide is for someone who is new to the repository and wants to clone it, run it locally, and then move it onto a server for internal use.

Latest release context:
- this guide includes the simulated trend layer, configurable export workbench, proactive workspace tiles, and insight artifact flows added in the April 16, 2026 release wave documented in [RELEASE_NOTES_2026-04-16.md](RELEASE_NOTES_2026-04-16.md)

The intended audience includes:
- engineers onboarding to the project
- platform teams deploying internal tools
- architects reviewing the repo for enterprise adoption
- developers extending the HR analytics experience

## 1. What You Are Deploying

When you run this repo, you are standing up:
- a web UI for HR-only analytics
- a FastAPI backend that streams results over SSE
- a governed tool-using agent
- an approved HR analytics dataset
- a simulated 36-month workforce history layer for trend analysis
- an access-control store linked to the authenticated user email
- a memory/context store for prior questions and policy documents
- a governed artifact layer for configured Excel workbooks, one-page PDF briefs, and PowerPoint export on chart or insight surfaces

Important: this repo already contains production-oriented patterns, but it still includes demo-grade defaults. Treat it as a strong internal prototype or reference implementation, not a completed bank-hardened product.

## 2. Repository Contents

At a minimum, understand these files before modifying the platform:

### Top-level
- [README.md](README.md): overview and repo map
- [server.py](server.py): main backend entry point
- [setup_db.py](setup_db.py): optional helper to rebuild `hr_data.db`
- [config.py](config.py): environment-driven runtime configuration

### Agent
- [agent/llm_client.py](agent/llm_client.py)
- [agent/orchestrator.py](agent/orchestrator.py)
- [agent/prompts.py](agent/prompts.py)
- [agent/tool_executor.py](agent/tool_executor.py)
- [agent/tools.py](agent/tools.py)

### Data and policy
- [database/connector.py](database/connector.py)
- [database/access_control.py](database/access_control.py)
- [database/context_store.py](database/context_store.py)
- [database/schema.py](database/schema.py)
- [database/workforce_history.py](database/workforce_history.py)

### Frontend
- [static/index.html](static/index.html)
- [static/app.js](static/app.js)
- [static/style.css](static/style.css)

### Utilities
- [utils/build_workforce_history.py](utils/build_workforce_history.py)
- [utils/report_artifacts.py](utils/report_artifacts.py)

## 3. System Requirements

| Component | Minimum | Recommended |
|---|---|---|
| Python | 3.10 | 3.12 |
| RAM | 1 GB | 4 GB |
| Disk | 500 MB | 2 GB |
| Network | outbound access to chosen LLM endpoint | internal reverse proxy + managed egress |

Python dependencies are declared in [requirements.txt](requirements.txt):
- `fastapi`
- `uvicorn`
- `anthropic`
- `openai`
- `pandas`
- `plotly`
- `python-dotenv`
- `Pillow`
- `python-pptx`
- `XlsxWriter`

## 4. Clone And Install

### 4.1 Clone

```bash
git clone https://github.com/BRGandhi/hr-agent-platform.git
cd hr-agent-platform
```

### 4.2 Create a virtual environment

```bash
python -m venv .venv
```

Activate:
- Windows PowerShell:
  ```powershell
  .venv\Scripts\Activate.ps1
  ```
- macOS/Linux:
  ```bash
  source .venv/bin/activate
  ```

### 4.3 Install dependencies

```bash
pip install -r requirements.txt
```

## 5. Configure The Environment

Copy the example file:

```bash
copy .env.example .env
```

The current configurable items are defined in [config.py](config.py).

### Recommended development configuration

```env
DEFAULT_LLM_PROVIDER=openai-compatible
DEFAULT_OPENAI_COMPAT_MODEL=gpt-5.2
DEFAULT_OPENAI_COMPAT_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=sk-...
SESSION_TTL_MINUTES=120
AUTH_REQUIRED=true
DEV_SSO_ENABLED=true
SSO_PROVIDERS=Microsoft,Google,Okta
```

### Anthropic configuration

```env
DEFAULT_LLM_PROVIDER=anthropic
DEFAULT_LLM_MODEL=claude-opus-4-6
ANTHROPIC_API_KEY=sk-ant-...
AUTH_REQUIRED=true
DEV_SSO_ENABLED=true
```

### Notes
- `DEV_SSO_ENABLED=true` enables the demo sign-in flow.
- `AUTH_REQUIRED=false` bypasses the auth shell and resolves the user as local admin.
- `DEFAULT_OPENAI_COMPAT_BASE_URL` points at the OpenAI API by default, but it can still be changed to Ollama or another OpenAI-compatible server.
- `SECURE_COOKIES=false` is the right local default for `http://127.0.0.1:8000`; set it to `true` only behind HTTPS.
- `CORS_ALLOWED_ORIGINS` should list only your trusted frontend origins outside local development.
- API keys can be entered either in `.env` or in the Connect LLM modal.
- Generated aggregate tables can be turned into visuals either by asking the agent in a follow-up prompt or by using the table-level `Visual options` action in the UI.
- Standard reports now prefer a `Download Excel` action instead of offering a visualization CTA.
- The one-page PDF brief is meant for insight surfaces, not plain report tables.
- PowerPoint export is meant for chart and selected-visual surfaces, not plain report tables.

## 6. Prepare The HR Dataset

The repo includes a bundled `hr_data.db`, so a fresh clone can run immediately without rebuilding the demo database.

Only rebuild the dataset if you want to refresh or replace the demo data source:

```bash
python setup_db.py
```

That rebuilds:
- `hr_data.db`
- the `employees` table with the HR analytics dataset
- the simulated monthly trend layer through [database/workforce_history.py](database/workforce_history.py)

If you only want to refresh the simulated monthly history without rebuilding the base snapshot:

```bash
python utils/build_workforce_history.py
```

The first application run will also create:
- `access_control.db`
- `context_store.db`

## 7. Start The Application Locally

### Recommended path: FastAPI + web UI

```bash
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Open:
- `http://127.0.0.1:8000`

## 8. Validate A Fresh Local Install

After starting the server, validate the following:

### 8.1 Authentication shell
- the sign-in screen appears
- Microsoft, Google, and Okta buttons render

### 8.2 Scoped login flow
- logging in as Microsoft resolves to a Technology manager
- logging in as Google resolves to an HR Business Partner

### 8.3 Role-filtered UI
- top KPI cards reflect the signed-in business coverage
- proactive insight tiles reflect the signed-in role, saved history, and latest scoped trend data
- example prompts change based on access
- topic chips under the welcome state expand into related sample questions when clicked
- previous questions appear in the sidebar after asking a question
- the `While You Chat` strip can be dismissed and restored
- the workspace tile customizer allows pinning and hiding KPI and insight tiles

### 8.4 Response and memory UX
- assistant answers show `Yes` / `No` helpfulness controls
- a table response can still be turned into a chart with a follow-up such as `make this a visualization`
- asking a similar question later can surface a previously upvoted answer as a helpful example
- standard reports should show a `Download Excel` action
- `Visual options` should only appear on smaller aggregate tables, not on employee-level roster outputs
- chart or selected-visual surfaces can show `PowerPoint`
- insight-driven surfaces can show a one-page PDF brief
- `Configure Excel` should allow column, sort, filter, row-limit, summary-sheet, and period-based selections when appropriate

### 8.5 Trend validation
Try these prompts:
- `Show me a mom trend of attrition`
- `Generate a promotion trend report for Business Units for the last 12 months`
- `Show this 3 year promo trend for only lab tech`

Expected behavior:
- the first prompt should route directly to a chart rather than a report-builder clarification
- the second prompt should preserve a time window into report export actions
- the third prompt should resolve to `Laboratory Technician` and a 36-month promotion trend rather than falling back to a headcount chart

### 8.6 Chat safety behavior
Try these prompts:
- `What is the attrition rate for Business Units?`
- `Generate an active headcount report for Business Units`
- `Write me a poem about Mars`

Expected behavior:
- the first two work if they match the user's access
- the third is rejected as out of scope

## 9. How The SSO + Access Model Works Today

Current behavior:
- the web UI uses a demo SSO experience
- `POST /api/auth/login` creates a local cookie-backed session
- the authenticated user email is looked up in `access_control.db`

This means the repo already has the integration seam for enterprise identity:
- user identity comes from auth
- authorization comes from a separate data store

For a real bank deployment, replace the demo sign-in with:
- OIDC via Entra ID, Okta, Ping, or another enterprise IdP
- a real user profile source
- an authoritative role/scope mapping source

## 10. Running It On Your Own Server

This section is written for an engineer standing up the application on an internal Linux server.

### 10.1 Create the runtime environment

```bash
sudo mkdir -p /opt/hr-insights
sudo chown $USER:$USER /opt/hr-insights
cd /opt/hr-insights
git clone https://github.com/BRGandhi/hr-agent-platform.git app
cd app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 10.2 Create `.env`

```env
DEFAULT_LLM_PROVIDER=anthropic
DEFAULT_LLM_MODEL=claude-opus-4-6
ANTHROPIC_API_KEY=your-key
SESSION_TTL_MINUTES=120
AUTH_REQUIRED=true
DEV_SSO_ENABLED=false
SSO_PROVIDERS=Microsoft,Google,Okta
```

Important:
- if `DEV_SSO_ENABLED=false`, the repo currently does not yet complete a real SSO redirect flow
- you must implement your real IdP integration before using this as a true internal production service

### 10.3 Prepare the database

The repo should already contain the bundled `hr_data.db`.

Only rebuild it if you are intentionally replacing the demo dataset:

```bash
source .venv/bin/activate
python setup_db.py
```

If a code pull updates only the simulated trend logic and not the base snapshot itself:

```bash
source .venv/bin/activate
python utils/build_workforce_history.py
```

After any upgrade that changes backend routes, restart the running `uvicorn` process before validating the UI. Several local issues during this release wave were caused by the browser loading new assets while an old backend process was still serving stale routes and stale `/api/stats` payloads.

### 10.4 Start with Uvicorn

```bash
source .venv/bin/activate
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

### 10.5 Recommended reverse proxy

Put the app behind an internal reverse proxy such as NGINX.

Example `nginx.conf` fragment:

```nginx
server {
    listen 443 ssl http2;
    server_name hr-insights.internal.bank.example;

    ssl_certificate     /etc/ssl/certs/hr-insights.crt;
    ssl_certificate_key /etc/ssl/private/hr-insights.key;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_buffering off;
    }
}
```

### 10.6 Recommended systemd unit

```ini
[Unit]
Description=HR Insights Platform
After=network.target

[Service]
WorkingDirectory=/opt/hr-insights/app
EnvironmentFile=/opt/hr-insights/app/.env
ExecStart=/opt/hr-insights/app/.venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8000
Restart=always
User=hrplatform
Group=hrplatform

[Install]
WantedBy=multi-user.target
```

## 11. What To Replace For A Bank Deployment

This is the most important section for a regulated internal rollout.

### Replace immediately
- demo SSO flow
- deployment-specific `CORS_ALLOWED_ORIGINS`
- in-memory sessions
- local `SECURE_COOKIES=false` with production HTTPS cookie settings
- SQLite-based access-control authority if your bank already has a source of truth

### Strongly consider replacing
- SQLite memory store
- SQLite analytics store if connecting to real HR systems
- the single-node in-memory rate limiter if you deploy multiple app instances

### Add before production
- centralized logging
- audit logs for question, access decision, and report generation
- secrets management
- backup and retention policies
- automated tests
- CI validation for docs, linting, and smoke tests

## 12. How To Change The Data Source

### Option A: keep SQLite, replace the CSV
Update:
- [setup_db.py](setup_db.py)
- [database/schema.py](database/schema.py)
- [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md)

### Option B: replace the connector entirely
Implement the same contract as [database/connector.py](database/connector.py):
- `execute_query(sql, access_profile=None)`
- `get_table_stats(access_profile=None)`

### Option C: externalize access control
Replace [database/access_control.py](database/access_control.py) with a connector into:
- HR entitlement tables
- manager hierarchy systems
- enterprise IAM or governance sources

## 13. How To Extend The Agent

### Add a new tool
1. Add the schema to [agent/tools.py](agent/tools.py)
2. Implement the handler in [agent/tool_executor.py](agent/tool_executor.py)
3. Update [agent/prompts.py](agent/prompts.py)
4. Verify the web UI renders the resulting event type correctly

### Add or change a governed export artifact
1. Update the request model or endpoint behavior in [server.py](server.py)
2. Implement or revise the story-building logic in [utils/report_artifacts.py](utils/report_artifacts.py)
3. Update the relevant client action in [static/app.js](static/app.js)
4. Re-check the workflow policy:
   - Excel for report tables
   - PDF one-pagers for insight surfaces
   - PowerPoint for chart or selected-visual surfaces

### Extend the simulated trend layer
1. Update [database/workforce_history.py](database/workforce_history.py)
2. Refresh the data with [utils/build_workforce_history.py](utils/build_workforce_history.py) or [setup_db.py](setup_db.py)
3. Update [database/connector.py](database/connector.py) and [database/schema.py](database/schema.py)
4. Update [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
5. Run the trend-focused regression tests

### Change prompt behavior
Update [agent/prompts.py](agent/prompts.py).

### Add a new LLM provider
Extend [agent/llm_client.py](agent/llm_client.py) with:
- a new client adapter
- normalized request/response translation
- tool-call conversion logic

## 14. Suggested First Tasks For A New Engineer

If you are coming fresh to the project, do these in order:
1. Clone and run the app locally.
2. Sign in with each demo provider and observe the role-based access differences.
3. Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
4. Read [database/access_control.py](database/access_control.py) and [database/context_store.py](database/context_store.py).
5. Trace a single request through [server.py](server.py), [agent/orchestrator.py](agent/orchestrator.py), and [agent/tool_executor.py](agent/tool_executor.py).
6. Review [docs/RUNBOOK.md](docs/RUNBOOK.md) to understand operational expectations.
7. Read [RELEASE_NOTES_2026-04-16.md](RELEASE_NOTES_2026-04-16.md) before changing trend, export, or personalization behavior.
