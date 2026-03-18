# HR Intelligence Platform

An agentic AI assistant for HR analytics with an LLM-agnostic orchestration layer. Ask questions about your workforce in plain English and the agent will write SQL, query the database, calculate metrics, generate Plotly charts, and stream results to the UI.

The platform is now governed by default:
- it only responds to HR insights, workforce analytics, HR policy, and people-data questions
- out-of-scope prompts are refused before model execution
- SSO-linked users are mapped to role-based department and metric access
- retrieved policy/schema context plus user conversation memory are added to each turn
- top-level portal metrics are scoped to the signed-in user's access

It now supports:
- Anthropic models
- OpenAI-compatible APIs
- local models such as Llama through Ollama or vLLM
- hosted OpenAI-compatible providers, including Kimi-compatible endpoints
- an SSO-style sign-in layer in front of the web app
- role-based access from a dedicated access-control database
- a context and memory layer backed by SQLite

Two frontends, one backend:
- FastAPI plus vanilla JS frontend
- legacy Streamlit frontend

## Quick Start

### Prerequisites
- Python 3.10+
- One model endpoint:
  - Anthropic API key, or
  - any OpenAI-compatible API, or
  - a local OpenAI-compatible server such as Ollama
- IBM HR Attrition dataset CSV:
  https://www.kaggle.com/datasets/pavansubhasht/ibm-hr-analytics-attrition-dataset

### Setup

```bash
git clone https://github.com/BRGandhi/hr-agent-platform.git
cd hr-agent-platform
pip install -r requirements.txt
cp .env.example .env
python setup_db.py
python server.py
```

Open `http://localhost:8000`.

### Example `.env` setups

Anthropic:
```env
DEFAULT_LLM_PROVIDER=anthropic
DEFAULT_LLM_MODEL=claude-opus-4-6
ANTHROPIC_API_KEY=sk-ant-...
```

Local Llama via Ollama:
```env
DEFAULT_LLM_PROVIDER=openai-compatible
DEFAULT_OPENAI_COMPAT_MODEL=llama3.1:8b
DEFAULT_OPENAI_COMPAT_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=
```

Hosted OpenAI-compatible provider:
```env
DEFAULT_LLM_PROVIDER=openai-compatible
DEFAULT_OPENAI_COMPAT_MODEL=your-provider-model-id
DEFAULT_OPENAI_COMPAT_BASE_URL=https://your-provider.example/v1
OPENAI_API_KEY=...
```

## Architecture

```text
Browser / Streamlit
        |
        v
FastAPI server.py
        |
        v
HRAgent orchestrator.py
  -> provider adapter (Anthropic or OpenAI-compatible)
  -> access control enforcement
  -> context and memory retrieval
  -> ToolExecutor
      -> query_hr_database
      -> calculate_metrics
      -> create_visualization
      -> get_attrition_insights
        |
        v
SQLite HR database
SQLite access-control database
SQLite context and memory database
```

The agent loop is provider-agnostic:
1. The selected model receives the conversation history plus tool schemas.
2. Access controls check that the question and any generated SQL stay within the signed-in user's scope.
3. Retrieved HR policies, schema notes, and prior-user memory are injected into the system context.
4. The model either requests tools or returns a final answer.
5. Tool results are appended to normalized conversation history and the loop repeats.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DEFAULT_LLM_PROVIDER` | `anthropic` | `anthropic` or `openai-compatible` |
| `DEFAULT_LLM_MODEL` | `claude-opus-4-6` | Default Anthropic model |
| `ANTHROPIC_API_KEY` | empty | Anthropic credential |
| `OPENAI_API_KEY` | empty | Credential for OpenAI-compatible providers |
| `DEFAULT_OPENAI_COMPAT_MODEL` | `llama3.1:8b` | Default OpenAI-compatible model |
| `DEFAULT_OPENAI_COMPAT_BASE_URL` | `http://localhost:11434/v1` | Default OpenAI-compatible endpoint |
| `SESSION_TTL_MINUTES` | `120` | Idle-session cleanup timeout |
| `AUTH_REQUIRED` | `true` | Require sign-in before loading the app |
| `DEV_SSO_ENABLED` | `true` | Enables local demo SSO session flow |
| `SSO_PROVIDERS` | `Microsoft,Google,Okta` | Sign-in buttons shown on the auth page |
| `PORT` | `8000` | FastAPI server port |
| `APP_PASSWORD` | empty | Optional Streamlit password gate |

Runtime-created stores:
- `access_control.db`: maps SSO-linked emails to role, department scope, allowed metrics, and document tags
- `context_store.db`: stores recent user memory and HR policy/schema documents used for retrieval

## Security Notes

- SQL is validated as read-only before execution.
- SQL is also checked against role-based metric access and department scope.
- API keys are never committed.
- The JS frontend does not store API keys in `localStorage`.
- Sessions are still in-memory, but idle sessions are cleaned up automatically.

## Project Structure

```text
server.py
app.py
config.py
requirements.txt
.env.example
agent/
database/
static/
utils/
docs/
```

## Extending

To add a new tool:
1. Define the schema in `agent/tools.py`
2. Implement the handler in `agent/tool_executor.py`
3. The provider adapters will automatically expose it to supported models
