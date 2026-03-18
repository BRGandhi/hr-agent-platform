# HR Intelligence Platform

An agentic AI assistant for HR analytics with an LLM-agnostic orchestration layer. Ask questions about your workforce in plain English and the agent will write SQL, query the database, calculate metrics, generate Plotly charts, and stream results to the UI.

It now supports:
- Anthropic models
- OpenAI-compatible APIs
- local models such as Llama through Ollama / vLLM
- hosted OpenAI-compatible providers, including Kimi-compatible endpoints
- an SSO-style sign-in layer in front of the web app

Two frontends, one backend:
- FastAPI + vanilla JS frontend
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
  -> ToolExecutor
      -> query_hr_database
      -> calculate_metrics
      -> create_visualization
      -> get_attrition_insights
        |
        v
SQLite HR database
```

The agent loop is provider-agnostic:
1. The selected model receives the conversation history plus tool schemas.
2. The model either requests tools or returns a final answer.
3. Tool results are appended to normalized conversation history and the loop repeats.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DEFAULT_LLM_PROVIDER` | `anthropic` | `anthropic` or `openai-compatible` |
| `DEFAULT_LLM_MODEL` | `claude-opus-4-6` | Default Anthropic model |
| `ANTHROPIC_API_KEY` | — | Anthropic credential |
| `OPENAI_API_KEY` | — | Credential for OpenAI-compatible providers |
| `DEFAULT_OPENAI_COMPAT_MODEL` | `llama3.1:8b` | Default OpenAI-compatible model |
| `DEFAULT_OPENAI_COMPAT_BASE_URL` | `http://localhost:11434/v1` | Default OpenAI-compatible endpoint |
| `MAX_AGENT_ITERATIONS` | `10` | Max tool call loop depth |
| `SESSION_TTL_MINUTES` | `120` | Idle-session cleanup timeout |
| `AUTH_REQUIRED` | `true` | Require sign-in before loading the app |
| `DEV_SSO_ENABLED` | `true` | Enables local demo SSO session flow |
| `SSO_PROVIDERS` | `Microsoft,Google,Okta` | Sign-in buttons shown on the auth page |
| `PORT` | `8000` | FastAPI server port |
| `APP_PASSWORD` | — | Optional Streamlit password gate |

## Security Notes

- SQL is validated as read-only before execution.
- API keys are never committed.
- The JS frontend no longer stores API keys in `localStorage`.
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
