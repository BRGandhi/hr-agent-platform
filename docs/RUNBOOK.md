# Runbook

This runbook covers day-2 operations for the HR Insights Platform: how to start it, validate it, troubleshoot it, and operate it safely as an internal service.

## 1. Operational Model

The current platform consists of:
- a FastAPI application process
- static frontend assets served by FastAPI
- one or more upstream LLM providers
- three local SQLite stores

Those stores are:
- `hr_data.db`
- `access_control.db`
- `context_store.db`

The platform is stateful at runtime because it keeps:
- in-memory chat sessions
- in-memory auth sessions

That means a restart does not corrupt the system, but it does clear active sessions.

## 2. Start Procedures

### 2.1 Local or foreground start

```bash
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

### 2.2 Server start through systemd

```bash
sudo systemctl start hr-insights
sudo systemctl status hr-insights
```

## 3. Stop Procedures

### Foreground process
- `Ctrl+C`

### systemd

```bash
sudo systemctl stop hr-insights
```

## 4. Health Checks

### 4.1 Basic import check

```bash
python - <<'PY'
import server
print("server_ok")
PY
```

### 4.2 Frontend reachability

```bash
curl -I http://127.0.0.1:8000/
```

Expected:
- HTTP 200

### 4.3 Health endpoint

```bash
curl http://127.0.0.1:8000/healthz
```

Expected:
- `{"ok": true, "database": "connected"}`

### 4.4 Auth config reachability

```bash
curl http://127.0.0.1:8000/api/auth/config
```

Expected:
- JSON payload describing auth requirements and supported providers

### 4.5 Manual smoke test
1. Open the UI
2. Sign in with a demo provider
3. Confirm the KPI strip loads
4. Ask an HR question aligned to the signed-in user's access
5. Generate a standard report and confirm the table shows `Download Excel`
6. Generate a small aggregate table and confirm `Visual options` appears only there
7. Ask an out-of-scope question and confirm refusal

## 5. Files That Must Exist

Minimum required for the primary app flow:
- `.env`
- `hr_data.db`
- Python virtual environment or equivalent runtime

Created automatically at runtime if missing:
- `access_control.db`
- `context_store.db`

If `hr_data.db` is missing, rebuild it with:

```bash
python setup_db.py
```

Deployment note:
- Docker deployments are expected to ship with a bundled `hr_data.db`
- if a containerized deployment fails with `HR database not available`, verify `hr_data.db` is committed into the repo and present in the image build context
- the Dockerfile now validates the database during image build so missing-data failures surface earlier

## 6. Logging

### 6.1 Application logs
If started via `uvicorn`, logs go to stdout/stderr unless redirected.

Example:

```bash
python -m uvicorn server:app --host 0.0.0.0 --port 8000 >> app.log 2>&1
```

### 6.2 What to look for

Useful log patterns:
- `401 Authentication required`: missing or invalid auth session
- `400 Empty message`: malformed chat request
- `Anthropic API error` or `OpenAI-compatible provider error`: upstream model problem
- `Tool execution error`: problem in tool code or query path
- `Could not prepare the Excel export`: failure in report export regeneration

### 6.3 Recommended future logging posture
For a bank-internal deployment, ship logs to a centralized platform and include:
- authenticated user identifier
- resolved access scope
- tool name executed
- report type generated
- error category

Avoid logging:
- raw secrets
- unnecessary personal data from report outputs

## 7. Common Operational Checks

### Check repo status

```bash
git status --short
```

### Confirm databases exist

```bash
ls *.db
```

### Verify the HR data table

```bash
python - <<'PY'
import sqlite3
conn = sqlite3.connect("hr_data.db")
print(conn.execute("select count(*) from employees").fetchone())
conn.close()
PY
```

### Verify access-control data

```bash
python - <<'PY'
from database.access_control import AccessControlStore
store = AccessControlStore()
print(store.get_profile("demo.google@hr-intelligence.local"))
PY
```

### Verify context store

```bash
python - <<'PY'
from database.context_store import ContextStore
store = ContextStore()
print(store.list_documents())
PY
```

## 8. Frequent Failure Modes

### 8.1 `hr_data.db` missing
Symptoms:
- KPI board fails to load
- queries do not work

Fix:

```bash
python setup_db.py
```

### 8.2 No model configured
Symptoms:
- chat request returns `Model is required`

Fix:
- set `DEFAULT_LLM_PROVIDER` and the corresponding model env variables
- or choose a provider/model through the UI

### 8.3 Anthropic key missing
Symptoms:
- `Anthropic API key required`

Fix:
- set `ANTHROPIC_API_KEY`
- or switch to an OpenAI-compatible model path

### 8.4 Upstream model endpoint unavailable
Symptoms:
- provider error
- timeout
- connection failures

Fix:
- validate outbound network access
- validate provider credentials
- validate local Ollama or compatible service is running

### 8.5 Out-of-scope answer when the user expected data
Symptoms:
- the platform refuses the question

Likely causes:
- the prompt is not HR-related enough
- the user asked for a metric outside the access profile
- the user asked for a non-HR task

Fix:
- verify the user profile in `access_control.db`
- rephrase the question in explicit HR terms

### 8.6 Sidebar history is empty unexpectedly
Possible causes:
- the user has not asked a question yet
- the app is using a different identity than expected
- `context_store.db` was recreated

Fix:
- check the auth session user
- inspect `conversation_memory` in `context_store.db`

## 9. Backup And Restore

### 9.1 What to back up
- `hr_data.db`
- `access_control.db`
- `context_store.db`
- `.env`

### 9.2 Simple file backup

```bash
cp hr_data.db hr_data.db.bak
cp access_control.db access_control.db.bak
cp context_store.db context_store.db.bak
cp .env .env.bak
```

### 9.3 Restore

```bash
cp hr_data.db.bak hr_data.db
cp access_control.db.bak access_control.db
cp context_store.db.bak context_store.db
cp .env.bak .env
```

After restore, restart the app.

## 10. Release And Upgrade Procedure

### 10.1 Pull latest code

```bash
git pull origin master
```

### 10.2 Refresh dependencies

```bash
pip install -r requirements.txt
```

### 10.3 Re-run safety checks

```bash
python -m compileall .
python - <<'PY'
import server
print("server_ok")
PY
```

### 10.4 Check whether data stores need migration
This repo currently uses lightweight SQLite initialization logic rather than a migration framework. After upgrades:
- confirm `access_control.db` still loads
- confirm `context_store.db` still loads
- rebuild `hr_data.db` if the source schema changed

## 11. Security Operations Guidance

This section is especially relevant for internal bank use.

### Current repo defaults that must be reviewed
- `CORS_ALLOWED_ORIGINS` may still be set for localhost
- auth cookies default to local-development settings unless `SECURE_COOKIES=true`
- auth sessions are in-memory
- dev SSO is not real enterprise SSO

### Minimum production actions
1. Put the app behind TLS.
2. Restrict network access to internal users and trusted services.
3. Replace dev SSO with corporate identity.
4. Move session state to a shared service.
5. Review retention policy for `context_store.db`.
6. Decide whether conversation history should be considered regulated user activity data.

## 12. Incident Response Checklist

### Scenario: UI loads but chat fails
1. Confirm LLM provider config in `.env`
2. Confirm network access to upstream model
3. Inspect logs for provider-specific errors
4. Test with a simple HR question

### Scenario: users see wrong data scope
1. Inspect the user email resolved by auth
2. Inspect `access_control.db`
3. Verify department scoping behavior in [database/connector.py](database/connector.py)
4. Verify metric restrictions in [database/access_control.py](database/access_control.py)

### Scenario: out-of-scope filtering is too aggressive
1. Review keyword-based scope logic in [database/access_control.py](database/access_control.py)
2. Review prompt instructions in [agent/prompts.py](agent/prompts.py)
3. Test with a clearer HR-specific prompt

### Scenario: memory quality is poor
1. Inspect documents in `context_store.db`
2. Add or update context docs through `/api/context/documents`
3. Review retrieval behavior in [database/context_store.py](database/context_store.py)

## 13. Recommended Production Hardening Backlog

For internal-bank readiness, the next runbook-worthy improvements should be:
1. Real SSO integration
2. Redis or equivalent shared session store
3. stronger secret handling
4. centralized structured logging
5. shared rate limiting for multi-instance deployments
6. automated smoke tests
7. role and report audit trails
