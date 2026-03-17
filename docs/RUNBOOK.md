# Runbook — HR Intelligence Platform (v1)

Operational procedures for running, monitoring, and troubleshooting the platform.

---

## Table of Contents
1. [Starting & Stopping](#1-starting--stopping)
2. [Health Checks](#2-health-checks)
3. [Common Errors & Fixes](#3-common-errors--fixes)
4. [Database Operations](#4-database-operations)
5. [API Key Management](#5-api-key-management)
6. [Logs](#6-logs)
7. [Performance Tuning](#7-performance-tuning)
8. [Upgrade Procedure](#8-upgrade-procedure)
9. [Incident Response](#9-incident-response)

---

## 1. Starting & Stopping

### Start (FastAPI + JS frontend)
```bash
cd hr-agent-platform
python server.py
# Listening on http://0.0.0.0:8000
```

Custom port:
```bash
PORT=9000 python server.py
```

### Start (Streamlit legacy)
```bash
python -m streamlit run app.py --server.port 8501
```

### Stop
`Ctrl+C` in the terminal. The server is stateless — no clean-shutdown steps required.

### Restart (with nohup / background)
```bash
nohup python server.py > hr_platform.log 2>&1 &
echo $! > server.pid
```
To stop:
```bash
kill $(cat server.pid)
```

---

## 2. Health Checks

### FastAPI
```bash
curl http://localhost:8000/api/stats
```
Expected response:
```json
{
  "total_employees": 1470,
  "attrited_employees": 237,
  "active_employees": 1233,
  "attrition_rate_pct": 16.1,
  "columns": ["Age", "Attrition", ...]
}
```

| Status | Meaning |
|---|---|
| `200` with data | Healthy |
| `500` | Database error — see [§4](#4-database-operations) |
| `Connection refused` | Server not running |

### Streamlit
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8501/healthz
# Expected: 200
```

---

## 3. Common Errors & Fixes

### `hr_data.db not found`
```
STATUS: error in sidebar / "Database not found" banner
```
**Fix:**
```bash
# Ensure CSV is present one level above the project folder, then:
python setup_db.py
```

### `Invalid Anthropic API key`
```
EVENT: {"type": "error", "message": "Invalid Anthropic API key..."}
```
**Fix:** Enter a valid `sk-ant-...` key in the sidebar or set `ANTHROPIC_API_KEY` in `.env`.

### `Rate limit reached`
```
EVENT: {"type": "error", "message": "Rate limit reached. Please wait..."}
```
**Fix:** Wait 30-60 seconds and retry. If persistent, check your usage tier at [console.anthropic.com](https://console.anthropic.com).

### `Agent reached max iterations`
```
EVENT: {"type": "error", "message": "Agent reached max iterations (10)..."}
```
**Cause:** Very complex multi-part question caused more than 10 tool calls.
**Fix:** Rephrase as two simpler questions, or increase `MAX_AGENT_ITERATIONS` in `config.py` (watch cost).

### `SQL rejected by safety validator`
```
Tool result: "SQL rejected by safety validator: ..."
```
**Cause:** Claude generated a query containing a blocked keyword (`DROP`, `INSERT`, `DELETE`, `UPDATE`, `--`, `;`).
**Fix:** This is expected safety behavior — the agent will self-correct on its next iteration. If it loops, rephrase the question.

### `httptools` build failure (Windows ARM64)
```
error: Microsoft Visual C++ 14.0 or greater is required...
```
**Fix:**
```bash
pip install fastapi uvicorn python-multipart   # no [standard] suffix
```

### Port already in use
```
ERROR: [Errno 48] Address already in use
```
**Fix:**
```bash
# Find and kill the process
lsof -ti:8000 | xargs kill -9   # Mac/Linux
netstat -ano | findstr :8000    # Windows — note PID, then:
taskkill /PID <PID> /F
```

### Plotly chart not rendering (JS frontend)
**Symptom:** Chart card appears but is empty.
**Cause:** Plotly.js CDN blocked (corporate proxy) or chart JSON parse error.
**Fix:** Check browser console for errors. If Plotly CDN is blocked, download `plotly-2.35.2.min.js` and host it locally:
```html
<!-- index.html — change CDN to local -->
<script src="/static/plotly.min.js" defer></script>
```
Place the file in `static/`.

---

## 4. Database Operations

### Rebuild database from scratch
```bash
rm hr_data.db       # Mac/Linux
del hr_data.db      # Windows
python setup_db.py
```

### Inspect database
```bash
python - <<'EOF'
import sqlite3
conn = sqlite3.connect("hr_data.db")
print(conn.execute("SELECT COUNT(*) FROM employees").fetchone())
print([r[1] for r in conn.execute("PRAGMA table_info(employees)").fetchall()])
conn.close()
EOF
```

### Run a manual query
```bash
python - <<'EOF'
from database.connector import HRDatabase
db = HRDatabase()
rows = db.execute_query("SELECT Department, COUNT(*) as n FROM employees GROUP BY Department")
for r in rows: print(r)
EOF
```

### Backup
```bash
cp hr_data.db hr_data.db.bak
```

---

## 5. API Key Management

### How the key is loaded (priority order)
1. `ANTHROPIC_API_KEY` environment variable
2. `ANTHROPIC_API_KEY` in `.env` file
3. Runtime sidebar input (stored in-memory only, not on disk)

### Rotate the key
1. Generate new key at [console.anthropic.com](https://console.anthropic.com)
2. Update `.env`: `ANTHROPIC_API_KEY=sk-ant-NEWKEY`
3. Restart the server — no database rebuild needed

### Verify the key works
```bash
python - <<'EOF'
import anthropic, os
from dotenv import load_dotenv
load_dotenv()
client = anthropic.Anthropic()
r = client.messages.create(model="claude-opus-4-6", max_tokens=10, messages=[{"role":"user","content":"ping"}])
print("OK:", r.content[0].text)
EOF
```

---

## 6. Logs

### FastAPI (stdout)
All requests and errors print to stdout:
```
INFO:     127.0.0.1:54321 - "POST /api/chat HTTP/1.1" 200 OK
INFO:     127.0.0.1:54321 - "GET /api/stats HTTP/1.1" 200 OK
```

### Redirect to file
```bash
python server.py >> hr_platform.log 2>&1
```

### Streamlit logs
Streamlit writes to `~/.streamlit/logs/`. Access via:
```bash
cat ~/.streamlit/logs/streamlit.log
```

### What to look for
| Log pattern | Meaning |
|---|---|
| `422 Unprocessable Entity` | Bad request body — check JSON format |
| `500 Internal Server Error` | Agent or DB error — check traceback |
| `AuthenticationError` | Invalid API key |
| `RateLimitError` | Slow down — too many concurrent requests |

---

## 7. Performance Tuning

### Model latency
- `claude-opus-4-6` (default): best quality, 3-15s per response
- `claude-sonnet-4-5`: ~2x faster, lower cost — change in `config.py`:
  ```python
  DEFAULT_MODEL = "claude-sonnet-4-5"
  ```

### Disable adaptive thinking
In `agent/orchestrator.py`, change:
```python
thinking={"type": "adaptive"}
# to:
thinking={"type": "disabled"}
```
This reduces latency and cost at the expense of reasoning depth.

### Reduce max iterations
```python
# config.py
MAX_AGENT_ITERATIONS = 5  # default 10
```
Limits tool-call chains — appropriate for simpler single-question use cases.

### SQLite performance
For >50k employees, add an index:
```sql
CREATE INDEX IF NOT EXISTS idx_attrition ON employees(Attrition);
CREATE INDEX IF NOT EXISTS idx_department ON employees(Department);
```
Run via `python -c "from database.connector import HRDatabase; db=HRDatabase(); db._get_connection().execute('CREATE INDEX ...')"`.

---

## 8. Upgrade Procedure

### Pull latest code
```bash
git pull origin main
pip install -r requirements.txt   # picks up new deps
```

### Check for breaking changes
Look at `docs/CODE_LOG.md` for any database schema changes that require a DB rebuild.

### If `requirements.txt` changed significantly
```bash
pip install --upgrade -r requirements.txt
```

### If schema changed
```bash
rm hr_data.db
python setup_db.py
```

---

## 9. Incident Response

### Complete outage (server unreachable)

1. Check if process is running: `ps aux | grep server.py` (Mac/Linux) or Task Manager (Windows)
2. Check port: `curl http://localhost:8000/api/stats`
3. Check `.env` exists and has API key
4. Check `hr_data.db` exists
5. Restart: `python server.py`

### All queries failing with "database error"

1. Test DB directly: `python -c "from database.connector import HRDatabase; print(HRDatabase().is_connected())"`
2. If `False`, rebuild: `python setup_db.py`

### All queries returning "API error"

1. Check API key: see [§5](#5-api-key-management)
2. Check Anthropic status: [status.anthropic.com](https://status.anthropic.com)
3. Check network: `curl https://api.anthropic.com` should return a response

### Chart not rendering but text works

1. Open browser DevTools → Console — look for Plotly errors
2. Try a different chart type: "show as bar chart" vs "show as pie chart"
3. If Plotly CDN unreachable, host locally (see [§3](#3-common-errors--fixes))

### Memory growing over time

The `_sessions` dict in `server.py` grows unbounded. Restart the server or add a TTL-based eviction:
```python
# Add to server.py — prune sessions older than 1 hour
import time
SESSION_TTL = 3600
_session_times = {}

def _get_or_create_session(session_id, api_key):
    now = time.time()
    # Evict stale sessions
    stale = [k for k, t in _session_times.items() if now - t > SESSION_TTL]
    for k in stale:
        _sessions.pop(k, None)
        _session_times.pop(k, None)
    _session_times[session_id] = now
    ...
```
