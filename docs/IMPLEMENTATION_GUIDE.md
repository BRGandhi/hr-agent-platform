# Implementation Guide

This guide is for someone who is new to the repository and wants to clone it, run it locally, and then move it onto a server for internal use.

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
- a scoped HR dataset
- an access-control store linked to the authenticated user email
- a memory/context store for prior questions and policy documents

Important: this repo already contains production-oriented patterns, but it still includes demo-grade defaults. Treat it as a strong internal prototype or reference implementation, not a completed bank-hardened product.

## 2. Repository Contents

At a minimum, understand these files before modifying the platform:

### Top-level
- [README.md](README.md): overview and repo map
- [server.py](server.py): main backend entry point
- [setup_db.py](setup_db.py): builds `hr_data.db`
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

### Frontend
- [static/index.html](static/index.html)
- [static/app.js](static/app.js)
- [static/style.css](static/style.css)

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

## 6. Prepare The HR Dataset

The repo expects the IBM HR CSV used by [setup_db.py](setup_db.py).

By default, [config.py](config.py) expects the CSV one directory above the repo:

```python
CSV_PATH = str(Path(__file__).parent.parent / "WA_Fn-UseC_-HR-Employee-Attrition.csv")
```

### Steps
1. Download the CSV.
2. Place it at the configured path.
3. Run:

```bash
python setup_db.py
```

This creates:
- `hr_data.db`
- `employees` table with the HR analytics dataset

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

### 8.3 Access-scoped UI
- top KPI cards reflect the signed-in scope
- example prompts change based on access
- topic chips under the welcome state expand into related sample questions when clicked
- previous questions appear in the sidebar after asking a question

### 8.4 Response and memory UX
- assistant answers show `Yes` / `No` helpfulness controls
- a table response can still be turned into a chart with a follow-up such as `make this a visualization`
- asking a similar question later can surface a previously upvoted answer as a helpful example
- standard reports should show a `Download Excel` action
- `Visual options` should only appear on smaller aggregate tables, not on employee-level roster outputs

### 8.5 Chat safety behavior
Try these prompts:
- `What is the attrition rate for my scope?`
- `Generate an active headcount report for my scope`
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

Place the CSV and run:

```bash
source .venv/bin/activate
python setup_db.py
```

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
2. Sign in with each demo provider and observe the scoped differences.
3. Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
4. Read [database/access_control.py](database/access_control.py) and [database/context_store.py](database/context_store.py).
5. Trace a single request through [server.py](server.py), [agent/orchestrator.py](agent/orchestrator.py), and [agent/tool_executor.py](agent/tool_executor.py).
6. Review [docs/RUNBOOK.md](docs/RUNBOOK.md) to understand operational expectations.
