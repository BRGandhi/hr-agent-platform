"""
Agentic HR Intelligence Platform — Streamlit UI

Run with:
    streamlit run app.py
"""

import json
import os
import streamlit as st
import plotly.io as pio
from pathlib import Path

# ── Page config (must be first Streamlit call) ─────────────────────────────
st.set_page_config(
    page_title="HR Intelligence Platform",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Lazy imports that require installed packages ───────────────────────────
def check_db_exists() -> bool:
    db_path = Path(__file__).parent / "hr_data.db"
    return db_path.exists()


# ── Custom CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Chat bubbles */
    .user-bubble {
        background: #E3F2FD;
        border-radius: 12px 12px 2px 12px;
        padding: 12px 16px;
        margin: 8px 0;
        max-width: 80%;
        margin-left: auto;
        color: #1a1a1a;
    }
    .assistant-bubble {
        background: #F8F9FA;
        border-left: 4px solid #4CAF50;
        border-radius: 0 12px 12px 12px;
        padding: 12px 16px;
        margin: 8px 0;
        max-width: 90%;
        color: #1a1a1a;
    }
    /* Tool call badge */
    .tool-badge {
        display: inline-block;
        background: #FFF3E0;
        border: 1px solid #FF9800;
        border-radius: 6px;
        padding: 2px 8px;
        font-size: 12px;
        font-family: monospace;
        color: #E65100;
        margin-right: 6px;
    }
    /* Section headers */
    .section-header {
        font-size: 13px;
        font-weight: 600;
        color: #666;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-top: 16px;
        margin-bottom: 4px;
    }
    /* Sidebar example button styling */
    .stButton > button {
        width: 100%;
        text-align: left;
        padding: 8px 12px;
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)


# ── Session state initialization ───────────────────────────────────────────
def init_session_state():
    defaults = {
        "messages": [],          # list of {role, content, tool_calls, charts}
        "agent": None,           # HRAgent instance
        "api_key": "",
        "db_ready": False,
        "show_tool_calls": True,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_session_state()


# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🧠 HR Intelligence")
    st.caption("Agentic Platform · Claude Opus 4.6")
    st.divider()

    # API Key
    st.markdown("### API Key")
    api_key_input = st.text_input(
        "Anthropic API Key",
        type="password",
        value=st.session_state.api_key or os.getenv("ANTHROPIC_API_KEY", ""),
        placeholder="sk-ant-...",
        help="Get your key at console.anthropic.com",
    )
    if api_key_input != st.session_state.api_key:
        st.session_state.api_key = api_key_input
        st.session_state.agent = None  # reset agent when key changes

    st.divider()

    # DB Status
    st.markdown("### Database")
    if check_db_exists():
        st.success("hr_data.db ready", icon="✅")
        st.session_state.db_ready = True
    else:
        st.error("hr_data.db not found", icon="❌")
        st.code("python setup_db.py", language="bash")
        st.caption("Run setup_db.py first to load the HR data.")
        st.session_state.db_ready = False

    st.divider()

    # Settings
    st.markdown("### Settings")
    st.session_state.show_tool_calls = st.toggle(
        "Show tool calls", value=st.session_state.show_tool_calls,
        help="Display SQL queries and tool activity"
    )

    st.divider()

    # Example questions
    st.markdown("### Example Questions")

    example_questions = [
        "How many employees left the company?",
        "What's the attrition rate by department?",
        "Show attrition by job role as a bar chart",
        "Which factors most contribute to attrition?",
        "Compare average salary across departments",
        "Who are the highest risk employees?",
        "Show age distribution of employees who left",
        "How does overtime affect attrition?",
        "What's the average tenure by department?",
        "Show satisfaction scores for employees who left vs stayed",
    ]

    for q in example_questions:
        if st.button(q, key=f"ex_{q[:20]}", use_container_width=True):
            st.session_state["pending_question"] = q
            st.rerun()

    st.divider()

    # New conversation
    if st.button("🗑️ New Conversation", use_container_width=True):
        st.session_state.messages = []
        if st.session_state.agent:
            st.session_state.agent.reset()
        st.rerun()


# ── Main area ──────────────────────────────────────────────────────────────
st.title("HR Intelligence Platform")
st.caption("Ask anything about your workforce · Powered by Claude Opus 4.6 + SQLite")

# Warnings if not ready
if not st.session_state.api_key:
    st.warning("Enter your Anthropic API key in the sidebar to get started.")

if not st.session_state.db_ready:
    st.error("Database not found. Run `python setup_db.py` in the hr_agent_platform folder.")
    st.stop()


# ── Agent initialization ───────────────────────────────────────────────────
def get_agent():
    """Lazy-initialize the HRAgent (imports are deferred to avoid errors at startup)."""
    if st.session_state.agent is None and st.session_state.api_key:
        from database.connector import HRDatabase
        from agent.orchestrator import HRAgent
        db = HRDatabase()
        st.session_state.agent = HRAgent(
            api_key=st.session_state.api_key,
            db=db,
        )
    return st.session_state.agent


# ── Render chat history ────────────────────────────────────────────────────
def render_message(msg: dict):
    role = msg["role"]

    if role == "user":
        st.markdown(
            f'<div class="user-bubble">👤 {msg["content"]}</div>',
            unsafe_allow_html=True,
        )
    else:
        with st.container():
            # Tool calls (collapsible)
            if st.session_state.show_tool_calls and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    with st.expander(
                        f"🔧 Tool: **{tc['name']}**" + (f" — {tc['explanation'][:60]}" if tc.get("explanation") else ""),
                        expanded=False,
                    ):
                        if tc.get("sql"):
                            st.markdown("**SQL Query:**")
                            st.code(tc["sql"], language="sql")
                        elif tc.get("inputs"):
                            st.json(tc["inputs"])

            # Charts
            for chart in msg.get("charts", []):
                try:
                    fig = pio.from_json(chart["chart_json"])
                    st.plotly_chart(fig, use_container_width=True)
                except Exception as e:
                    st.warning(f"Could not render chart: {e}")

            # Table results (if content is JSON rows)
            if msg.get("table_data"):
                import pandas as pd
                df = pd.DataFrame(msg["table_data"])
                st.table(df)

            # Final text response
            if msg.get("content"):
                st.markdown(
                    f'<div class="assistant-bubble">🤖 {msg["content"]}</div>',
                    unsafe_allow_html=True,
                )


for msg in st.session_state.messages:
    render_message(msg)


# ── Handle incoming question ───────────────────────────────────────────────
def handle_question(user_input: str):
    if not user_input.strip():
        return

    if not st.session_state.api_key:
        st.error("Please enter your Anthropic API key in the sidebar first.")
        return

    agent = get_agent()
    if agent is None:
        st.error("Could not initialize agent. Check your API key.")
        return

    # Add user message to history
    st.session_state.messages.append({"role": "user", "content": user_input})

    # Placeholders for live streaming in the UI
    tool_calls_collected = []
    charts_collected = []
    table_data = None

    with st.spinner("Thinking..."):
        status_placeholder = st.empty()
        final_text = ""

        for event in agent.chat(user_input):
            etype = event.get("type")

            if etype == "tool_call":
                tool_calls_collected.append({
                    "name": event["name"],
                    "explanation": event.get("explanation", ""),
                    "sql": event.get("sql", ""),
                    "inputs": event.get("inputs", {}),
                })
                if st.session_state.show_tool_calls:
                    status_placeholder.info(
                        f"🔧 Calling **{event['name']}**"
                        + (f": {event['explanation'][:80]}" if event.get("explanation") else "")
                    )

            elif etype == "tool_result":
                # Try to parse result as a table for display
                try:
                    parsed = json.loads(event["result"])
                    if isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], dict):
                        table_data = parsed
                except (json.JSONDecodeError, TypeError):
                    pass

            elif etype == "chart":
                charts_collected.append({
                    "chart_json": event["chart_json"],
                    "title": event.get("title", "Chart"),
                })

            elif etype == "final_text":
                final_text = event["text"]
                status_placeholder.empty()

            elif etype == "error":
                status_placeholder.empty()
                st.error(event["message"])
                # Still save partial results
                break

    # Save assistant message to history
    st.session_state.messages.append({
        "role": "assistant",
        "content": final_text,
        "tool_calls": tool_calls_collected,
        "charts": charts_collected,
        "table_data": table_data,
    })

    st.rerun()


# ── Chat input at the bottom ───────────────────────────────────────────────
# Handle pending question from sidebar buttons
if "pending_question" in st.session_state:
    pending = st.session_state.pop("pending_question")
    handle_question(pending)

# Text input
user_input = st.chat_input(
    "Ask about your workforce... (e.g. 'Show attrition rate by department as a bar chart')"
)
if user_input:
    handle_question(user_input)
