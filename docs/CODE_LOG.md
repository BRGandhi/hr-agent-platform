# Code Log — HR Intelligence Platform

Chronological record of all significant changes, architectural decisions, and design rationale. Useful for onboarding, audits, and understanding "why it was built this way."

---

## v1.3 — JS/HTML Frontend + FastAPI Backend
**Summary:** Replaced Streamlit server with FastAPI + vanilla JS frontend. Streamlit UI preserved as a legacy option.

### New files
| File | Purpose |
|---|---|
| `server.py` | FastAPI app: SSE streaming, static file serving, session management |
| `static/index.html` | App shell — sidebar, KPI strip, message thread, input bar |
| `static/style.css` | Full design system (CSS custom properties, indigo theme, dark sidebar) |
| `static/app.js` | All client logic: SSE parsing, Plotly rendering, session persistence |

### Changed files
| File | Change |
|---|---|
| `requirements.txt` | Added `fastapi>=0.115.0`, `uvicorn>=0.32.0`, `python-multipart>=0.0.12` |
| `run.bat` | Default now launches FastAPI; `run.bat streamlit` for legacy |
| `setup_and_run.bat` | Removed hardcoded personal system path |
| `.gitignore` | Added `hr_data.db` and `*.csv` exclusions |

### Architecture decisions

**Why SSE instead of WebSockets?**
SSE (Server-Sent Events) is one-directional (server → client) which matches the agent's streaming pattern exactly. It works over standard HTTP/1.1, requires no upgrade handshake, and is auto-reconnecting in browsers. WebSockets add bidirectional complexity that isn't needed here.

**Why vanilla JS instead of React?**
The v1 platform is a prototype/demo tool. React adds a build step, node_modules, and tooling overhead that slows adoption. Vanilla JS loads instantly, has zero dependencies beyond Plotly.js (from CDN), and can be dropped into any environment. The v2 upgrade path (React) is available for teams that need the full-featured version.

**Why in-memory sessions?**
Simple and sufficient for single-user or small-team use. Each `session_id` maps to an `HRAgent` instance in a Python dict. For multi-user production, replace with Redis (see RUNBOOK §7).

**Why keep the Streamlit frontend?**
Some users prefer Streamlit's interactive dataframe/table rendering and quick prototyping ergonomics. Both frontends call the same Python agent — no duplication.

---

## v1.2 — Visual Polish (Streamlit)
**Summary:** Modernized the Streamlit UI with a professional design system.

### Changed files
| File | Change |
|---|---|
| `app.py` | Replaced HTML chat bubble divs with `st.chat_message()`; added KPI strip; new CSS |
| `.streamlit/config.toml` | New file — indigo primary color, Inter font, light theme |
| `agent/tool_executor.py` | New 8-color palette; donut pie charts; professional Plotly layout overrides |

### Design decisions

**Why `st.chat_message()` over custom HTML divs?**
Streamlit's native chat component handles accessibility, avatar rendering, and streaming more robustly than injected HTML. The original HTML bubble approach was fragile with Streamlit version updates.

**Chart color palette:**
```python
["#6366F1", "#10B981", "#F59E0B", "#EF4444", "#3B82F6", "#8B5CF6", "#EC4899", "#14B8A6"]
```
Chosen for: (1) high contrast on white backgrounds, (2) colorblind-safe (avoid red/green pairing for significance), (3) consistent with Tailwind/Radix color tokens used in v2.

**KPI strip data source:**
`HRDatabase.get_table_stats()` runs 3 lightweight SQLite queries at app startup (total count, attrition count, column list). Cached in `st.session_state` to avoid re-running on every rerender.

---

## v1.1 — Bug Fixes
**Summary:** Addressed compatibility issues found during ARM64 Windows testing.

### Changes
| File | Change | Reason |
|---|---|---|
| `app.py` | Replaced `st.dataframe()` → `st.table()` → back to `st.dataframe()` | pyarrow dependency conflict on ARM64; `st.dataframe()` with `hide_index=True` works on newer Streamlit |
| `Dockerfile` | Added `--prefer-binary` flag to pip install | Prevents C extension compilation on ARM64 |
| `render.yaml` | Added health check path | Render deployment was timing out |
| `app.py` | Added `APP_PASSWORD` environment variable gate | Basic access control for shared deployments |

### Known limitations at this version
- No conversation persistence (memory lost on server restart)
- Streamlit re-renders entire page on each message (not true streaming)
- Single-user: no concurrent session isolation in Streamlit

---

## v1.0 — Initial Release
**Summary:** Core agentic HR analytics platform.

### Architecture established

**Agent pattern: Think → Act → Observe loop**
```
while iterations < MAX:
    response = claude(conversation_history + tools)
    if stop_reason == "end_turn":  yield final_text; return
    if stop_reason == "tool_use":
        for each tool_use block:
            yield tool_call event
            result = executor.execute(tool, inputs)
            yield tool_result event
        append results to history
```
This is the simplest correct implementation of a tool-use agent. No framework (no LangChain, no LlamaIndex) — just the Anthropic SDK's `messages.create()` API called in a loop.

**Why no streaming from Claude?**
The `messages.create()` call (not `stream()`) was used initially for simplicity. Tool-use results need to be gathered before feeding back to Claude anyway, so true token-level streaming only applies to the final `end_turn` response. The UI simulates streaming by updating the DOM as each event is yielded from the generator.

**Why adaptive thinking?**
`thinking={"type": "adaptive"}` lets Claude decide when extended reasoning is worth the token cost. For simple queries ("how many employees?") it uses zero thinking tokens. For multi-factor analysis it may use 1,000-5,000 tokens. This balances cost and quality automatically.

**Tool design decisions**

`query_hr_database` — Why let Claude write raw SQL?
Claude Opus 4.6 is highly capable at SQL generation. Rather than building a query builder or NL→SQL intermediate layer, we give Claude the schema (in the system prompt via `database/schema.py`) and let it generate the query directly. The `utils/safety.py` validator ensures only SELECT statements execute.

`calculate_metrics` — Why a separate metrics tool?
SQL aggregations cover 80% of metric needs, but some operations (correlation, distribution percentiles) are awkward in SQLite. This tool accepts JSON data (output from `query_hr_database`) and runs pandas operations. It keeps SQL complexity in check.

`create_visualization` — Why Plotly JSON, not images?
Returning Plotly's JSON figure spec (via `fig.to_json()`) means the frontend can render interactive charts. The chart is the full Plotly figure object — users can hover, zoom, and download. Image-based charts (PNG/SVG) would lose interactivity.

`get_attrition_insights` — Why pre-built queries?
The six `focus_area` queries are carefully crafted SQL that cover the most common HR analysis patterns. They run faster and more reliably than ad-hoc SQL generated for the same question. Claude calls this tool first for attrition questions, then follows up with `query_hr_database` for specifics.

**SQL safety design**
`utils/safety.py` implements a two-layer defense:
1. **Keyword blocklist:** `DROP`, `DELETE`, `UPDATE`, `INSERT`, `CREATE`, `ALTER`, `TRUNCATE`, `--`, `;` — rejects any query containing these
2. **Auto-LIMIT:** Appends `LIMIT 500` if no LIMIT clause present — prevents full-table scans returning 1M+ rows to the agent context

The `execute_query()` method in `database/connector.py` also checks that the query starts with `SELECT` as a final backstop.

### Files created at v1.0

| File | Lines | Purpose |
|---|---|---|
| `app.py` | 380 | Streamlit UI |
| `config.py` | 15 | Configuration constants |
| `setup_db.py` | ~50 | CSV → SQLite loader |
| `agent/orchestrator.py` | 160 | HRAgent class |
| `agent/tool_executor.py` | 350 | 4 tool implementations |
| `agent/tools.py` | ~80 | Tool JSON schemas |
| `agent/prompts.py` | 40 | System prompt |
| `database/connector.py` | 55 | SQLite wrapper |
| `database/schema.py` | ~60 | Column descriptions |
| `utils/safety.py` | ~40 | SQL validator |
| `Dockerfile` | 20 | Container build |
| `render.yaml` | 15 | Render.com deploy config |

---

## Known Technical Debt

| Item | Impact | Suggested Fix |
|---|---|---|
| In-memory sessions | Lost on restart, single-server only | Redis-backed session store |
| No token counting | Unexpectedly high costs on long sessions | Count tokens, warn user at threshold |
| Plotly CDN dependency | Breaks in air-gapped environments | Bundle Plotly.js in `static/` |
| No request timeout | Long-running queries block indefinitely | Add `asyncio.wait_for()` timeout in `server.py` |
| No auth | Anyone with network access can use the key | Add API key validation header or session token |
| `calculate_metrics` limited patterns | Only handles specific `operation` strings | Use Claude to generate pandas code dynamically |
| `MAX_AGENT_ITERATIONS` not per-user | Global limit, not per-conversation | Pass limit through to `HRAgent` constructor |

---

## Dependency Decisions

| Package | Why chosen | Alternative considered |
|---|---|---|
| `anthropic` | Official SDK, tool_use support, streaming | `openai` (different models) |
| `plotly` | Interactive JSON charts, Python + JS ecosystem | `matplotlib` (static images only) |
| `pandas` | Standard data manipulation, excellent SQLite/CSV integration | `polars` (faster but less mature ecosystem) |
| `fastapi` | Async, SSE streaming, auto docs, Pydantic | `flask` (sync only, no SSE), `django` (too heavy) |
| `uvicorn` | Standard ASGI server for FastAPI | `gunicorn` (WSGI, not async) |
| `streamlit` | Fastest way to build data UI in Python | `dash` (more complex), `gradio` (ML-focused) |
| `python-dotenv` | Standard `.env` file handling | Manual `os.environ` (no file support) |
