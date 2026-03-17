# HR Intelligence Platform

An agentic AI assistant for HR analytics powered by **Claude Opus 4.6**. Ask questions about your workforce in plain English — the agent writes SQL, queries the database, calculates metrics, generates Plotly charts, and streams results to a clean web UI.

> **Two frontends, one backend:** a modern HTML/CSS/JS interface (FastAPI) and a legacy Streamlit version both connect to the same Python agent.

---

## Screenshots

```
Sidebar: API key · DB status · example questions
KPI strip: 1,470 employees · 237 attrited · 16.1% rate
Chat: "Show attrition by department as a bar chart"
  → tool call: query_hr_database (SQL shown, collapsible)
  → inline Plotly bar chart
  → narrative summary
```

---

## Quick Start (5 minutes)

### Prerequisites
- Python 3.10+ ([download](https://www.python.org/downloads/))
- Anthropic API key ([console.anthropic.com](https://console.anthropic.com))
- IBM HR Attrition dataset CSV ([Kaggle link](https://www.kaggle.com/datasets/pavansubhasht/ibm-hr-analytics-attrition-dataset))

### Steps

```bash
# 1. Clone
git clone https://github.com/BRGandhi/hr-agent-platform.git
cd hr-agent-platform

# 2. Install dependencies
pip install -r requirements.txt

# 3. Add your API key
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...

# 4. Place the IBM CSV in the parent folder, then build the database
#    Expected: ../WA_Fn-UseC_-HR-Employee-Attrition.csv
python setup_db.py

# 5a. Launch JS/HTML frontend (recommended)
python server.py
# Open http://localhost:8000

# 5b. OR launch legacy Streamlit frontend
python -m streamlit run app.py
# Open http://localhost:8501
```

### Windows one-click setup
```bat
setup_and_run.bat   # installs Python deps + launches Streamlit
run.bat             # FastAPI + JS frontend (default)
run.bat streamlit   # Streamlit frontend
```

---

## Architecture

```
Browser (HTML/CSS/JS + Plotly.js)
        │  HTTP SSE  POST /api/chat
        ▼
FastAPI  server.py
        │  Python generator
        ▼
HRAgent  (orchestrator.py)
  ├─ Think  →  claude-opus-4-6 (adaptive thinking)
  ├─ Act    →  ToolExecutor
  │             ├─ query_hr_database   → SQLite
  │             ├─ calculate_metrics   → pandas
  │             ├─ create_visualization → plotly → JSON
  │             └─ get_attrition_insights → pre-built SQL
  └─ Observe →  tool results → next iteration
        │
        ▼
Streaming events: tool_call · chart · final_text · error
```

### Agent Loop (Think → Act → Observe)

1. **Think** — Claude receives the conversation history + 4 tool schemas. Returns either `tool_use` or `end_turn`.
2. **Act** — `ToolExecutor` runs the requested tool (SQL query, metric calc, chart build).
3. **Observe** — Tool result appended to history; loop repeats up to `MAX_AGENT_ITERATIONS=10`.

### Streaming (SSE)

`POST /api/chat` returns `text/event-stream`. Each event is a JSON object:

| `type`       | Payload fields                          |
|--------------|-----------------------------------------|
| `session`    | `session_id`                            |
| `tool_call`  | `name`, `explanation`, `sql`, `inputs`  |
| `chart`      | `chart_json` (Plotly JSON), `title`     |
| `final_text` | `text`                                  |
| `error`      | `message`                               |
| `done`       | —                                       |

---

## Project Structure

```
hr-agent-platform/
├── server.py               # FastAPI backend (replaces Streamlit server role)
├── app.py                  # Legacy Streamlit UI
├── config.py               # DB path, model name, iteration limit
├── setup_db.py             # One-time SQLite database builder
├── requirements.txt        # Python dependencies
├── run.bat                 # Windows launcher (JS frontend)
├── setup_and_run.bat       # Windows full setup + Streamlit launcher
│
├── agent/
│   ├── orchestrator.py     # HRAgent class — agentic loop
│   ├── tool_executor.py    # ToolExecutor — 4 tool implementations
│   ├── tools.py            # Tool JSON schemas (Anthropic format)
│   └── prompts.py          # System prompt with schema context
│
├── database/
│   ├── connector.py        # HRDatabase — SQLite queries
│   └── schema.py           # Column descriptions for prompt injection
│
├── utils/
│   └── safety.py           # SQL validator (SELECT-only, auto-LIMIT 500)
│
└── static/                 # Vanilla JS/HTML/CSS frontend
    ├── index.html
    ├── style.css
    └── app.js
```

---

## Tools Reference

| Tool | Description | Key Params |
|---|---|---|
| `query_hr_database` | Execute SELECT SQL against employees table | `sql_query`, `explanation` |
| `calculate_metrics` | Statistical operations on query results | `data` (JSON), `operation` |
| `create_visualization` | Generate Plotly chart JSON | `chart_type`, `data`, `x_column`, `y_column`, `title` |
| `get_attrition_insights` | Pre-built attrition analysis queries | `focus_area` |

### `get_attrition_insights` focus areas
- `overall_summary` — total employees, attrition rate, avg income/tenure
- `by_department` — attrition rate per department
- `by_job_role` — attrition + satisfaction per role
- `by_demographics` — gender × marital status breakdown
- `by_satisfaction` — job / environment / work-life satisfaction matrix
- `by_compensation` — attrition by income band
- `top_risk_factors` — ranked list: overtime, marital status, satisfaction scores

---

## Dataset

**IBM HR Analytics Employee Attrition & Performance**
- 1,470 employees × 35 columns
- Key fields: `Age`, `Attrition`, `Department`, `JobRole`, `MonthlyIncome`, `OverTime`, `YearsAtCompany`, `JobSatisfaction`, `EnvironmentSatisfaction`, `WorkLifeBalance`, `BusinessTravel`, `MaritalStatus`
- Download: [Kaggle](https://www.kaggle.com/datasets/pavansubhasht/ibm-hr-analytics-attrition-dataset)

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Required.** Set in `.env` or sidebar |
| `DEFAULT_MODEL` | `claude-opus-4-6` | Anthropic model |
| `MAX_AGENT_ITERATIONS` | `10` | Max tool call loop depth |
| `PORT` | `8000` | FastAPI server port |
| `APP_PASSWORD` | — | Optional: password-gates the Streamlit UI |

---

## Deployment

### Docker
```bash
docker build -t hr-intelligence .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-ant-... hr-intelligence
```

### Render.com
See `render.yaml` — deploys as a web service on the free tier.

### Railway / Fly.io / any PaaS
Set `ANTHROPIC_API_KEY` as an environment variable and run:
```bash
python server.py   # binds to $PORT automatically
```

---

## Security

- **SQL safety:** `utils/safety.py` validates all queries — SELECT-only, blocks `DROP`/`INSERT`/`UPDATE`/`DELETE`/`--`, appends `LIMIT 500` if missing.
- **API key:** Never committed. Passed via `.env`, environment variable, or runtime sidebar input.
- **Sessions:** In-memory only — no persistence to disk.

---

## Extending

### Add a new tool
1. Define the JSON schema in `agent/tools.py` (Anthropic `tools` format)
2. Add a handler method in `agent/tool_executor.py`
3. Dispatch it in `ToolExecutor.execute()`

### Swap the data source
Replace `database/connector.py` with a PostgreSQL, BigQuery, or Snowflake connector that exposes the same `execute_query()` and `get_table_stats()` interface.

### Point at a different dataset
Update `database/schema.py` with the new column descriptions and re-run `setup_db.py`.

---

## License
MIT
