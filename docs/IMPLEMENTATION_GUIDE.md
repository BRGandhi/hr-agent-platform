# Implementation Guide

> For teams picking up this project and deploying it to their environment.

---

## Table of Contents
1. [System Requirements](#1-system-requirements)
2. [Repository Setup](#2-repository-setup)
3. [Data Preparation](#3-data-preparation)
4. [Backend Configuration](#4-backend-configuration)
5. [Running Locally](#5-running-locally)
6. [Frontend Overview](#6-frontend-overview)
7. [Replacing the Dataset](#7-replacing-the-dataset)
8. [Customizing the Agent](#8-customizing-the-agent)
9. [Production Deployment](#9-production-deployment)
10. [Upgrading to v2](#10-upgrading-to-v2)

---

## 1. System Requirements

| Requirement | Minimum | Recommended |
|---|---|---|
| Python | 3.10 | 3.12 |
| RAM | 512 MB | 2 GB |
| Disk | 100 MB | 500 MB |
| OS | Windows 10, macOS 12, Ubuntu 20.04 | Any |
| Network | Outbound HTTPS to `api.anthropic.com` | — |

**Python packages installed by `requirements.txt`:**
```
anthropic>=0.40.0       # Anthropic SDK (Claude API)
streamlit>=1.32.0       # Legacy Streamlit UI (optional)
pandas>=2.0.0           # Data manipulation for metrics
plotly>=5.18.0          # Chart generation
python-dotenv>=1.0.0    # .env file loading
fastapi>=0.115.0        # Modern REST/SSE backend
uvicorn>=0.32.0         # ASGI server
python-multipart>=0.0.12 # Multipart form parsing
```

> **ARM64 Windows note:** If you're on Windows ARM (Surface Pro X, Snapdragon laptops), install pandas with `--only-binary=:all:` and uvicorn without `[standard]` (no httptools). `setup_and_run.bat` handles this automatically.

---

## 2. Repository Setup

```bash
git clone https://github.com/BRGandhi/hr-agent-platform.git
cd hr-agent-platform

# Create a virtual environment (recommended)
python -m venv .venv

# Activate
# Windows:   .venv\Scripts\activate
# Mac/Linux: source .venv/bin/activate

pip install -r requirements.txt
```

### Environment file
```bash
cp .env.example .env
```
Edit `.env`:
```
ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE
```

Your API key is loaded by `config.py` via `python-dotenv`. Alternatively, enter it in the app sidebar at runtime — it is never stored to disk.

---

## 3. Data Preparation

The platform ships without the dataset. Download the IBM HR Attrition CSV:

**Source:** [Kaggle — IBM HR Analytics](https://www.kaggle.com/datasets/pavansubhasht/ibm-hr-analytics-attrition-dataset)
**File:** `WA_Fn-UseC_-HR-Employee-Attrition.csv` (1,470 rows × 35 columns, ~300 KB)

Place the CSV **one folder above** `hr-agent-platform/`:
```
parent-folder/
  WA_Fn-UseC_-HR-Employee-Attrition.csv   ← here
  hr-agent-platform/
    setup_db.py
    ...
```

Then build the SQLite database:
```bash
python setup_db.py
# Creates: hr_data.db (~1.5 MB)
```

`setup_db.py` reads the CSV via pandas, normalizes column names, and loads into a single `employees` table. The `config.py` variable `CSV_PATH` controls where the CSV is expected — update it if your folder layout differs:

```python
# config.py
CSV_PATH = str(Path(__file__).parent.parent / "WA_Fn-UseC_-HR-Employee-Attrition.csv")
```

---

## 4. Backend Configuration

All configuration lives in `config.py`:

```python
DB_PATH      = str(BASE_DIR / "hr_data.db")          # SQLite location
CSV_PATH     = ...                                    # CSV location for setup_db.py
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")   # From .env
DEFAULT_MODEL     = "claude-opus-4-6"                 # Model used by agent
MAX_AGENT_ITERATIONS = 10                             # Max loop depth
```

**Environment variables (`.env` file):**

| Variable | Required | Default | Notes |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | — | Get from console.anthropic.com |
| `APP_PASSWORD` | No | — | Streamlit UI password gate |
| `PORT` | No | `8000` | FastAPI server port |

---

## 5. Running Locally

### FastAPI backend + HTML/JS frontend (recommended)

```bash
python server.py
```
Open **http://localhost:8000**. The server:
- Serves `static/index.html` at `/`
- Streams agent events via SSE at `POST /api/chat`
- Returns DB stats at `GET /api/stats`
- Resets conversation at `POST /api/reset`

### Streamlit frontend (legacy)

```bash
python -m streamlit run app.py
```
Open **http://localhost:8501**. Enter your API key in the sidebar.

### Windows launchers

| Command | What it does |
|---|---|
| `run.bat` | Finds Python, checks DB, launches FastAPI |
| `run.bat streamlit` | Same but launches Streamlit |
| `setup_and_run.bat` | Full setup: installs deps + builds DB + launches Streamlit |

---

## 6. Frontend Overview

The `static/` folder contains three files — no build step, no npm.

### `index.html`
- App shell: sidebar + topbar + KPI strip + messages area + input bar
- Loads Plotly.js from CDN for chart rendering
- No framework — pure HTML with semantic class names

### `style.css`
CSS custom properties drive the entire design system:
```css
--indigo: #6366F1        /* primary brand color */
--sidebar-w: 260px       /* sidebar width */
--topbar-h: 60px         /* header height */
```
Key component classes: `.kpi-card`, `.bubble-user`, `.bubble-ai`, `.tool-card`, `.chart-card`, `.msg-row`.

### `app.js`
Single-file vanilla JS, no dependencies beyond Plotly (loaded from CDN).

Key functions:
| Function | Purpose |
|---|---|
| `init()` | Wires DOM events, restores API key, loads stats |
| `handleSend()` | Validates input, calls `streamChat()` |
| `streamChat()` | Reads SSE stream, dispatches events to renderers |
| `buildToolCard(event)` | Collapsible tool-call HTML card |
| `buildChartCard(event)` | Plotly chart rendered into a card div |
| `newConversation()` | Resets server session + clears DOM |

**Session persistence:** `session_id` is stored in `localStorage` so page refreshes reconnect to the same in-memory conversation on the server (until the server restarts).

---

## 7. Replacing the Dataset

To point the platform at your own HR data:

### Option A — Different CSV
1. Put your CSV in the expected location (or update `CSV_PATH` in `config.py`)
2. Edit `setup_db.py` — update the column mapping to match your schema
3. Edit `database/schema.py` — update `HR_SCHEMA` with your column descriptions
4. Edit `agent/prompts.py` if the employee count or key fields differ
5. Re-run `python setup_db.py`

### Option B — Existing database (PostgreSQL, MySQL, etc.)
Replace `database/connector.py`. The agent only calls two methods:
```python
db.execute_query(sql: str) -> list[dict]
db.get_table_stats() -> dict   # keys: total_employees, attrited_employees, active_employees, attrition_rate_pct, columns
```
Implement these two methods for your database and nothing else needs to change.

### Option C — No attrition data at all
Remove `get_attrition_insights` from `agent/tools.py` and `ToolExecutor`. Update the system prompt in `agent/prompts.py`.

---

## 8. Customizing the Agent

### System prompt (`agent/prompts.py`)
Controls agent persona, tone, and rules. Key sections:
- **Capabilities** — what the agent can do
- **Database Schema** — injected from `database/schema.py` at import time
- **How to Respond** — when to use each tool
- **Rules** — SQL safety, citation, chart behavior
- **Tone & Format** — conciseness, bullet points, key metrics bold

### Adding a new tool

**Step 1 — Define schema** in `agent/tools.py`:
```python
{
    "name": "my_new_tool",
    "description": "What this tool does",
    "input_schema": {
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "..."}
        },
        "required": ["param1"]
    }
}
```

**Step 2 — Implement handler** in `agent/tool_executor.py`:
```python
elif tool_name == "my_new_tool":
    return self._my_new_tool(tool_input)
```
```python
def _my_new_tool(self, inputs: dict) -> str:
    # ... your logic ...
    return json.dumps(result)
```

**Step 3 — Tell the agent** — add a line to the "How to Respond" section in `agent/prompts.py` describing when to use the new tool.

### Changing the model
Update `DEFAULT_MODEL` in `config.py`. Available options:
- `claude-opus-4-6` — most capable, best for complex analysis (current default)
- `claude-sonnet-4-5` — faster, lower cost, good for simpler queries

### Adjusting thinking
The agent uses `thinking={"type": "adaptive"}` in `orchestrator.py`. Change to `{"type": "disabled"}` to skip thinking tokens (faster/cheaper) or `{"type": "enabled", "budget_tokens": 2000}` for fixed thinking.

---

## 9. Production Deployment

### Environment variables to set in production

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your production key |
| `PORT` | Port for your platform (e.g., 8080) |
| `APP_PASSWORD` | Optional: gates Streamlit UI access |

### Docker

```dockerfile
# Already provided in Dockerfile
docker build -t hr-intelligence .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-ant-... hr-intelligence
```

The Dockerfile:
1. Uses `python:3.12-slim`
2. Installs requirements
3. Copies source (excludes `.env`, `hr_data.db`)
4. Runs `python server.py`

**Important:** The database must be built before the image or mounted as a volume:
```bash
# Option 1: build DB into image
COPY WA_Fn-UseC_-HR-Employee-Attrition.csv /data/
RUN python setup_db.py

# Option 2: mount existing DB
docker run -p 8000:8000 -v /path/to/hr_data.db:/app/hr_data.db ...
```

### Render.com (free tier)
`render.yaml` is pre-configured. Connect the GitHub repo in the Render dashboard, set `ANTHROPIC_API_KEY` in the Environment tab, and deploy.

### Persistent sessions in production
The current in-memory session store (`_sessions` dict in `server.py`) does **not** survive server restarts. For production, replace it with Redis:
```python
# server.py — swap _sessions dict for Redis-backed store
import redis, pickle
r = redis.from_url(os.getenv("REDIS_URL"))

def _get_session(session_id):
    data = r.get(f"session:{session_id}")
    return pickle.loads(data) if data else None
```

---

## 10. Upgrading to v2

The `hr_intelligence_v2/` directory (included in this repo) is a full production-grade rewrite:

| | v1 (this) | v2 |
|---|---|---|
| Frontend | Vanilla JS / Streamlit | React 19 + TypeScript + Tailwind |
| Backend | FastAPI + SQLite | FastAPI + PostgreSQL + pgvector |
| Auth | None / password gate | Auth0 SSO + RBAC (6 roles) |
| Agent | Single agent | Orchestrator + 5 specialist agents |
| Reports | None | Deterministic report engine + PDF export |
| Connectors | CSV only | CSV + extensible HRIS connectors |
| Deployment | Single process | Docker Compose multi-container |

See [hr_intelligence_v2/README.md](../hr_intelligence_v2/README.md) and [docs/V2_ARCHITECTURE.md](V2_ARCHITECTURE.md) for the v2 implementation guide.
