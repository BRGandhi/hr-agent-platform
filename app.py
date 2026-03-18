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

from agent.llm_client import LLMConfig, OPENAI_COMPAT_PROVIDER
from config import (
    ANTHROPIC_API_KEY,
    DEFAULT_MODEL,
    DEFAULT_OPENAI_COMPAT_BASE_URL,
    DEFAULT_OPENAI_COMPAT_MODEL,
    DEFAULT_PROVIDER,
    OPENAI_API_KEY,
)

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
    /* ── Google Font: Inter ── */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* ── Hide Streamlit chrome ── */
    #MainMenu, footer { visibility: hidden; }
    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }

    /* ── App header ── */
    .app-header {
        display: flex;
        align-items: center;
        gap: 14px;
        padding: 0 0 4px 0;
        border-bottom: 2px solid #6366F1;
        margin-bottom: 1.5rem;
    }
    .app-header-icon {
        font-size: 2rem;
        line-height: 1;
    }
    .app-header-title {
        font-size: 1.45rem;
        font-weight: 700;
        color: #1E293B;
        margin: 0;
        letter-spacing: -0.3px;
    }
    .app-header-sub {
        font-size: 0.78rem;
        color: #64748B;
        margin: 0;
        font-weight: 500;
    }

    /* ── KPI metric strip ── */
    .kpi-strip {
        display: flex;
        gap: 12px;
        margin-bottom: 1.25rem;
        flex-wrap: wrap;
    }
    .kpi-card {
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 10px 18px;
        min-width: 120px;
        flex: 1;
    }
    .kpi-label {
        font-size: 0.7rem;
        font-weight: 600;
        color: #64748B;
        text-transform: uppercase;
        letter-spacing: 0.6px;
    }
    .kpi-value {
        font-size: 1.35rem;
        font-weight: 700;
        color: #1E293B;
        margin-top: 2px;
    }
    .kpi-value.danger { color: #EF4444; }
    .kpi-value.success { color: #10B981; }
    .kpi-value.accent { color: #6366F1; }

    /* ── Chat messages ── */
    .stChatMessage {
        border-radius: 12px !important;
        margin-bottom: 4px;
    }

    /* ── Tool call expander ── */
    .tool-expander-header {
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .tool-badge {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        background: #EEF2FF;
        border: 1px solid #C7D2FE;
        border-radius: 20px;
        padding: 3px 10px;
        font-size: 11.5px;
        font-weight: 600;
        color: #4338CA;
        font-family: 'Inter', sans-serif;
        letter-spacing: 0.1px;
    }
    .tool-badge.result {
        background: #F0FDF4;
        border-color: #BBF7D0;
        color: #15803D;
    }

    /* ── Sidebar styling ── */
    [data-testid="stSidebar"] {
        background: #0F172A;
    }
    [data-testid="stSidebar"] * {
        color: #E2E8F0 !important;
    }
    [data-testid="stSidebar"] .stTextInput input {
        background: #1E293B !important;
        border: 1px solid #334155 !important;
        color: #F1F5F9 !important;
        border-radius: 8px !important;
    }
    [data-testid="stSidebar"] .stTextInput input::placeholder {
        color: #64748B !important;
    }
    [data-testid="stSidebar"] .stButton > button {
        background: #1E293B !important;
        border: 1px solid #334155 !important;
        color: #CBD5E1 !important;
        border-radius: 8px !important;
        width: 100%;
        text-align: left;
        padding: 8px 12px;
        font-size: 13px;
        transition: all 0.15s ease;
    }
    [data-testid="stSidebar"] .stButton > button:hover {
        background: #334155 !important;
        border-color: #6366F1 !important;
        color: #F1F5F9 !important;
    }
    [data-testid="stSidebar"] .stToggle label {
        color: #CBD5E1 !important;
    }
    [data-testid="stSidebar"] hr {
        border-color: #1E293B !important;
    }
    [data-testid="stSidebar"] .sidebar-section-label {
        font-size: 10.5px;
        font-weight: 700;
        color: #475569 !important;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin: 16px 0 8px 0;
        display: block;
    }
    .sidebar-logo {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 4px 0 12px 0;
    }
    .sidebar-logo-icon {
        font-size: 1.6rem;
        line-height: 1;
    }
    .sidebar-logo-text {
        font-size: 1rem;
        font-weight: 700;
        color: #F1F5F9 !important;
        letter-spacing: -0.2px;
    }
    .sidebar-logo-sub {
        font-size: 0.68rem;
        color: #64748B !important;
        font-weight: 500;
    }

    /* ── Status pill ── */
    .status-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        border-radius: 20px;
        padding: 4px 12px;
        font-size: 12px;
        font-weight: 600;
    }
    .status-pill.ok {
        background: #052E16;
        border: 1px solid #166534;
        color: #4ADE80 !important;
    }
    .status-pill.error {
        background: #450A0A;
        border: 1px solid #7F1D1D;
        color: #FCA5A5 !important;
    }

    /* ── Dataframe ── */
    .stDataFrame { border-radius: 10px; overflow: hidden; }

    /* ── Chat input ── */
    .stChatInputContainer {
        border-top: 1px solid #E2E8F0;
        padding-top: 12px;
    }

    /* ── New conversation button (main sidebar) ── */
    .new-convo-btn > button {
        background: linear-gradient(135deg, #6366F1, #8B5CF6) !important;
        border: none !important;
        color: #FFFFFF !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
    }
    .new-convo-btn > button:hover {
        opacity: 0.9 !important;
    }
</style>
""", unsafe_allow_html=True)


# ── Session state initialization ───────────────────────────────────────────
def init_session_state():
    defaults = {
        "messages": [],
        "agent": None,
        "api_key": "",
        "provider": DEFAULT_PROVIDER,
        "model": DEFAULT_MODEL if DEFAULT_PROVIDER == "anthropic" else DEFAULT_OPENAI_COMPAT_MODEL,
        "base_url": "" if DEFAULT_PROVIDER == "anthropic" else DEFAULT_OPENAI_COMPAT_BASE_URL,
        "db_ready": False,
        "show_tool_calls": True,
        "db_stats": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_session_state()


# ── Password gate ──────────────────────────────────────────────────────────
def _get_app_password() -> str:
    try:
        return st.secrets.get("APP_PASSWORD", "")
    except Exception:
        return os.getenv("APP_PASSWORD", "")


def check_password() -> bool:
    expected = _get_app_password()
    if not expected:
        return True
    if st.session_state.get("authenticated"):
        return True

    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown("## 🧠 HR Intelligence Platform")
        st.markdown("Enter the access password to continue.")
        with st.form("login"):
            pwd = st.text_input("Password", type="password", placeholder="••••••••")
            if st.form_submit_button("Login", use_container_width=True):
                if pwd == expected:
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Incorrect password.")
    st.stop()
    return False


if not check_password():
    st.stop()


# ── DB Stats (cached) ───────────────────────────────────────────────────────
def get_db_stats():
    if st.session_state.db_stats is None and check_db_exists():
        try:
            from database.connector import HRDatabase
            db = HRDatabase()
            st.session_state.db_stats = db.get_table_stats()
        except Exception:
            pass
    return st.session_state.db_stats


# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div class="sidebar-logo">
        <span class="sidebar-logo-icon">🧠</span>
        <div>
            <div class="sidebar-logo-text">HR Intelligence</div>
            <div class="sidebar-logo-sub">LLM Agnostic · Agentic</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.divider()

    # Model configuration
    st.markdown('<span class="sidebar-section-label">Model</span>', unsafe_allow_html=True)
    selected_provider = st.selectbox(
        "Provider",
        options=["anthropic", OPENAI_COMPAT_PROVIDER],
        index=0 if st.session_state.provider == "anthropic" else 1,
        format_func=lambda value: "Anthropic" if value == "anthropic" else "OpenAI-compatible",
        label_visibility="collapsed",
    )
    if selected_provider != st.session_state.provider:
        st.session_state.provider = selected_provider
        st.session_state.model = DEFAULT_MODEL if selected_provider == "anthropic" else DEFAULT_OPENAI_COMPAT_MODEL
        st.session_state.base_url = "" if selected_provider == "anthropic" else DEFAULT_OPENAI_COMPAT_BASE_URL
        st.session_state.agent = None

    model_input = st.text_input(
        "Model Name",
        value=st.session_state.model,
        placeholder=DEFAULT_MODEL if st.session_state.provider == "anthropic" else DEFAULT_OPENAI_COMPAT_MODEL,
        help="Enter any provider-specific model id",
    )
    if model_input != st.session_state.model:
        st.session_state.model = model_input
        st.session_state.agent = None

    if st.session_state.provider == OPENAI_COMPAT_PROVIDER:
        base_url_input = st.text_input(
            "Base URL",
            value=st.session_state.base_url,
            placeholder=DEFAULT_OPENAI_COMPAT_BASE_URL,
            help="Examples: local Ollama, OpenRouter, Moonshot, Groq, Together, vLLM",
        )
        if base_url_input != st.session_state.base_url:
            st.session_state.base_url = base_url_input
            st.session_state.agent = None

    st.divider()

    # API Key
    st.markdown('<span class="sidebar-section-label">Credentials</span>', unsafe_allow_html=True)
    api_key_input = st.text_input(
        "API Key",
        type="password",
        value=st.session_state.api_key or (ANTHROPIC_API_KEY if st.session_state.provider == "anthropic" else OPENAI_API_KEY),
        placeholder="Optional for local OpenAI-compatible endpoints",
        help="Leave blank to use environment variables when available.",
        label_visibility="collapsed",
    )
    if api_key_input != st.session_state.api_key:
        st.session_state.api_key = api_key_input
        st.session_state.agent = None

    st.divider()

    # DB Status
    st.markdown('<span class="sidebar-section-label">Database</span>', unsafe_allow_html=True)
    if check_db_exists():
        st.markdown('<div class="status-pill ok">● hr_data.db connected</div>', unsafe_allow_html=True)
        st.session_state.db_ready = True
        stats = get_db_stats()
        if stats:
            st.caption(f"{stats['total_employees']:,} employees · {stats['attrition_rate_pct']}% attrition")
    else:
        st.markdown('<div class="status-pill error">✕ hr_data.db not found</div>', unsafe_allow_html=True)
        st.code("python setup_db.py", language="bash")
        st.session_state.db_ready = False

    st.divider()

    # Settings
    st.markdown('<span class="sidebar-section-label">Settings</span>', unsafe_allow_html=True)
    st.session_state.show_tool_calls = st.toggle(
        "Show tool calls",
        value=st.session_state.show_tool_calls,
        help="Display SQL queries and tool activity inline",
    )

    st.divider()

    # Example questions
    st.markdown('<span class="sidebar-section-label">Example Questions</span>', unsafe_allow_html=True)

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
        "Show satisfaction scores for leavers vs stayers",
    ]

    for q in example_questions:
        if st.button(q, key=f"ex_{q[:20]}", use_container_width=True):
            st.session_state["pending_question"] = q
            st.rerun()

    st.divider()

    st.markdown('<div class="new-convo-btn">', unsafe_allow_html=True)
    if st.button("+ New Conversation", use_container_width=True):
        st.session_state.messages = []
        if st.session_state.agent:
            st.session_state.agent.reset()
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)


# ── Main area ──────────────────────────────────────────────────────────────
st.markdown("""
<div class="app-header">
    <span class="app-header-icon">🧠</span>
    <div>
        <p class="app-header-title">HR Intelligence Platform</p>
        <p class="app-header-sub">Ask anything about your workforce · Provider-agnostic agent + SQLite</p>
    </div>
</div>
""", unsafe_allow_html=True)

# KPI strip
stats = get_db_stats()
if stats:
    attrition_color = "danger" if stats["attrition_rate_pct"] > 15 else "accent"
    st.markdown(f"""
    <div class="kpi-strip">
        <div class="kpi-card">
            <div class="kpi-label">Total Employees</div>
            <div class="kpi-value accent">{stats["total_employees"]:,}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Attrited</div>
            <div class="kpi-value danger">{stats["attrited_employees"]:,}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Active</div>
            <div class="kpi-value success">{stats["active_employees"]:,}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Attrition Rate</div>
            <div class="kpi-value {attrition_color}">{stats["attrition_rate_pct"]}%</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Data Columns</div>
            <div class="kpi-value">{len(stats.get("columns", []))}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# Warnings if not ready
if st.session_state.provider == "anthropic" and not (st.session_state.api_key or ANTHROPIC_API_KEY):
    st.info("Enter an Anthropic API key in the sidebar or set ANTHROPIC_API_KEY.", icon="🔑")

if not st.session_state.db_ready:
    st.error("Database not found. Run `python setup_db.py` in the hr_agent_platform folder.")
    st.stop()


# ── Agent initialization ───────────────────────────────────────────────────
def get_agent():
    llm_config = LLMConfig(
        provider=st.session_state.provider,
        model=st.session_state.model,
        api_key=st.session_state.api_key or (ANTHROPIC_API_KEY if st.session_state.provider == "anthropic" else OPENAI_API_KEY),
        base_url=st.session_state.base_url,
    )

    if st.session_state.agent is None:
        from database.connector import HRDatabase
        from agent.orchestrator import HRAgent
        db = HRDatabase()
        st.session_state.agent = HRAgent(llm_config=llm_config, db=db)
    else:
        st.session_state.agent.update_llm_config(llm_config)

    return st.session_state.agent


# ── Render chat history ────────────────────────────────────────────────────
def render_message(msg: dict):
    role = msg["role"]

    if role == "user":
        with st.chat_message("user"):
            st.markdown(msg["content"])
    else:
        with st.chat_message("assistant"):
            # Tool calls (collapsible)
            if st.session_state.show_tool_calls and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    label = f"⚡ **{tc['name']}**"
                    if tc.get("explanation"):
                        label += f" — {tc['explanation'][:70]}"
                    with st.expander(label, expanded=False):
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

            # Table results
            if msg.get("table_data"):
                import pandas as pd
                df = pd.DataFrame(msg["table_data"])
                st.dataframe(df, use_container_width=True, hide_index=True)

            # Final text response
            if msg.get("content"):
                st.markdown(msg["content"])


for msg in st.session_state.messages:
    render_message(msg)


# ── Handle incoming question ───────────────────────────────────────────────
def handle_question(user_input: str):
    if not user_input.strip():
        return

    if st.session_state.provider == "anthropic" and not (st.session_state.api_key or ANTHROPIC_API_KEY):
        st.error("Please enter an Anthropic API key in the sidebar first.")
        return

    agent = get_agent()
    if agent is None:
        st.error("Could not initialize agent. Check your provider settings.")
        return

    st.session_state.messages.append({"role": "user", "content": user_input})

    tool_calls_collected = []
    charts_collected = []
    table_data = None

    with st.chat_message("assistant"):
        status_placeholder = st.empty()
        final_text = ""

        with st.spinner("Thinking..."):
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
                        status_placeholder.markdown(
                            f'<span class="tool-badge">⚡ {event["name"]}'
                            + (f' — {event["explanation"][:80]}' if event.get("explanation") else "")
                            + "</span>",
                            unsafe_allow_html=True,
                        )

                elif etype == "tool_result":
                    if event.get("table_data"):
                        table_data = event["table_data"]

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
                    break

        # Render results inline (before rerun)
        if st.session_state.show_tool_calls and tool_calls_collected:
            for tc in tool_calls_collected:
                label = f"⚡ **{tc['name']}**"
                if tc.get("explanation"):
                    label += f" — {tc['explanation'][:70]}"
                with st.expander(label, expanded=False):
                    if tc.get("sql"):
                        st.markdown("**SQL Query:**")
                        st.code(tc["sql"], language="sql")
                    elif tc.get("inputs"):
                        st.json(tc["inputs"])

        for chart in charts_collected:
            try:
                fig = pio.from_json(chart["chart_json"])
                st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.warning(f"Could not render chart: {e}")

        if table_data:
            import pandas as pd
            df = pd.DataFrame(table_data)
            st.dataframe(df, use_container_width=True, hide_index=True)

        if final_text:
            st.markdown(final_text)

    st.session_state.messages.append({
        "role": "assistant",
        "content": final_text,
        "tool_calls": tool_calls_collected,
        "charts": charts_collected,
        "table_data": table_data,
    })

    st.rerun()


# ── Chat input ─────────────────────────────────────────────────────────────
if "pending_question" in st.session_state:
    pending = st.session_state.pop("pending_question")
    handle_question(pending)

user_input = st.chat_input(
    "Ask about your workforce... (e.g. 'Show attrition by department as a bar chart')"
)
if user_input:
    handle_question(user_input)
