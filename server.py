"""
HR Intelligence Platform - FastAPI backend

Security hardening:
- CORS restricted to configurable origins
- Secure cookie defaults
- Security headers (CSP, X-Frame-Options, etc.)
- Request logging with request IDs
- Rate limiting per IP
- Startup validation of databases and credentials
- Graceful shutdown cleanup
 - API keys can come from environment variables or the browser request
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape as xml_escape
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from agent.llm_client import LLMConfig, OPENAI_COMPAT_PROVIDER
from agent.orchestrator import HRAgent
from agent.tool_executor import ToolExecutor
from config import (
    ANTHROPIC_API_KEY,
    AUTH_REQUIRED,
    CORS_ALLOWED_ORIGINS,
    DEFAULT_MODEL,
    DEFAULT_OPENAI_COMPAT_BASE_URL,
    DEFAULT_OPENAI_COMPAT_MODEL,
    DEFAULT_PROVIDER,
    DEV_SSO_ENABLED,
    OPENAI_API_KEY,
    RATE_LIMIT_MAX_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
    SECURE_COOKIES,
    SESSION_TTL_MINUTES,
    SSO_PROVIDERS,
)
from database.access_control import AccessControlStore, AccessDeniedError
from database.connector import HRDatabase
from database.context_store import ContextStore

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("hr_platform")


# ---------------------------------------------------------------------------
# Security middleware
# ---------------------------------------------------------------------------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject standard security headers into every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.plot.ly; "
            "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'"
        )
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with a unique request ID."""

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        start = time.monotonic()
        response = await call_next(request)
        elapsed_ms = round((time.monotonic() - start) * 1000)
        logger.info(
            "%s %s %s %dms [%s]",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            request_id,
        )
        response.headers["X-Request-ID"] = request_id
        return response


# ---------------------------------------------------------------------------
# Rate limiter (in-memory, per-IP)
# ---------------------------------------------------------------------------
class _RateLimiter:
    """Simple sliding-window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        window_start = now - self.window_seconds
        hits = self._hits[key]
        # Prune old entries
        self._hits[key] = [t for t in hits if t > window_start]
        if len(self._hits[key]) >= self.max_requests:
            return False
        self._hits[key].append(now)
        return True


_rate_limiter = _RateLimiter(
    max_requests=RATE_LIMIT_MAX_REQUESTS,
    window_seconds=RATE_LIMIT_WINDOW_SECONDS,
)


def _check_rate_limit(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if not _rate_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please try again shortly.")


# ---------------------------------------------------------------------------
# Lifespan: startup validation + graceful shutdown
# ---------------------------------------------------------------------------
DB = HRDatabase()
ACCESS_STORE = AccessControlStore()
CONTEXT_STORE = ContextStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup validation ---
    if not DB.is_connected():
        logger.error("HR database not found or empty. Run: python setup_db.py")
        raise RuntimeError("HR database not available")

    if DEFAULT_PROVIDER == "anthropic" and not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY is not set. Anthropic provider will fail at runtime.")

    logger.info("Startup checks passed. Provider=%s Model=%s", DEFAULT_PROVIDER, DEFAULT_MODEL)
    yield
    # --- Shutdown cleanup ---
    _sessions.clear()
    _auth_sessions.clear()
    logger.info("Graceful shutdown complete — sessions cleared.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="HR Intelligence Platform", lifespan=lifespan)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    allow_credentials=True,
)

STATIC_DIR = Path(__file__).parent / "static"
AUTH_COOKIE_NAME = "hr_auth_session"


@dataclass
class SessionState:
    agent: HRAgent
    last_accessed: datetime


@dataclass
class AuthState:
    user: dict
    last_accessed: datetime


_sessions: dict[str, SessionState] = {}
_auth_sessions: dict[str, AuthState] = {}


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    api_key: str = ""
    provider: str = ""
    model: str = ""
    base_url: str = ""
    session_id: str = ""
    table_context_title: str = ""
    table_context_rows: list[dict] = Field(default_factory=list)


class ResetRequest(BaseModel):
    session_id: str


class LoginRequest(BaseModel):
    provider: str


class ContextDocumentRequest(BaseModel):
    title: str
    content: str
    tags: list[str]


class FeedbackRequest(BaseModel):
    memory_id: int
    vote: str


class ReportExportRequest(BaseModel):
    report_type: str
    title: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cleanup_expired_items():
    cutoff = _now() - timedelta(minutes=SESSION_TTL_MINUTES)
    for session_id in [key for key, session in _sessions.items() if session.last_accessed < cutoff]:
        _sessions.pop(session_id, None)
    for session_id in [key for key, session in _auth_sessions.items() if session.last_accessed < cutoff]:
        _auth_sessions.pop(session_id, None)


def _build_llm_config(req: ChatRequest) -> LLMConfig:
    browser_api_key = req.api_key.strip()
    provider = (req.provider or DEFAULT_PROVIDER).strip().lower()
    if provider == OPENAI_COMPAT_PROVIDER:
        model = (req.model or DEFAULT_OPENAI_COMPAT_MODEL or DEFAULT_MODEL).strip()
        base_url = (req.base_url or DEFAULT_OPENAI_COMPAT_BASE_URL).strip()
        api_key = browser_api_key or OPENAI_API_KEY
    else:
        provider = "anthropic"
        model = (req.model or DEFAULT_MODEL).strip()
        base_url = ""
        api_key = browser_api_key or ANTHROPIC_API_KEY

    return LLMConfig(provider=provider, model=model, api_key=api_key, base_url=base_url)


def _get_or_create_session(session_id: str, llm_config: LLMConfig) -> HRAgent:
    _cleanup_expired_items()
    session = _sessions.get(session_id)
    if session is None:
        session = SessionState(
            agent=HRAgent(llm_config=llm_config, db=DB, context_store=CONTEXT_STORE),
            last_accessed=_now(),
        )
        _sessions[session_id] = session
    else:
        session.agent.update_llm_config(llm_config)
        session.last_accessed = _now()
    return session.agent


def _create_demo_user(provider: str) -> dict:
    normalized = provider.strip().title()
    return {
        "name": f"{normalized} Demo User",
        "email": f"demo.{normalized.lower()}@hr-intelligence.local",
        "provider": normalized,
        "role": "Assigned via access database",
    }


def _get_auth_user(request: Request) -> dict | None:
    if not AUTH_REQUIRED:
        return {
            "name": "Local User",
            "email": "local@hr-intelligence.local",
            "provider": "Local",
            "role": "HR Admin",
        }

    _cleanup_expired_items()
    auth_token = request.cookies.get(AUTH_COOKIE_NAME)
    if not auth_token:
        return None
    auth_session = _auth_sessions.get(auth_token)
    if not auth_session:
        return None
    auth_session.last_accessed = _now()
    return auth_session.user


def _require_auth(request: Request) -> dict:
    user = _get_auth_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _current_access_profile(request: Request):
    user = _require_auth(request)
    try:
        return ACCESS_STORE.get_profile(user["email"])
    except AccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _filter_documents_for_profile(documents: list[dict], access_profile) -> list[dict]:
    allowed_tags = set(access_profile.allowed_doc_tags)
    if "all" in allowed_tags:
        return documents
    return [
        document
        for document in documents
        if allowed_tags.intersection(set(document.get("tags", [])))
    ]


def _ensure_document_tags_allowed(tags: list[str], access_profile) -> None:
    allowed_tags = set(access_profile.allowed_doc_tags)
    if "all" in allowed_tags:
        return
    requested_tags = {tag.strip() for tag in tags if tag.strip()}
    disallowed = sorted(tag for tag in requested_tags if tag not in allowed_tags)
    if disallowed:
        raise HTTPException(
            status_code=403,
            detail=(
                "You cannot manage context documents with these tags: "
                + ", ".join(disallowed)
            ),
        )


def _excel_sheet_name(title: str) -> str:
    cleaned = "".join("_" if char in '[]:*?/\\' else char for char in (title or "Report")).strip()
    return (cleaned or "Report")[:31]


def _excel_file_name(title: str) -> str:
    base = "".join(char if char.isalnum() else "_" for char in (title or "report")).strip("_").lower()
    return f"{base or 'report'}.xls"


def _excel_cell(value) -> tuple[str, str]:
    if value is None:
        return "String", ""
    if isinstance(value, bool):
        return "String", "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "Number", str(value)
    if isinstance(value, datetime):
        return "DateTime", value.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    return "String", xml_escape(str(value))


def _build_excel_xml(title: str, rows: list[dict]) -> str:
    worksheet_name = xml_escape(_excel_sheet_name(title))
    columns = list(rows[0].keys()) if rows else ["Message"]

    header_cells = "".join(
        f'<Cell ss:StyleID="header"><Data ss:Type="String">{xml_escape(str(column))}</Data></Cell>'
        for column in columns
    )
    row_xml: list[str] = [f"<Row>{header_cells}</Row>"]

    if rows:
        for row in rows:
            cells = []
            for column in columns:
                cell_type, cell_value = _excel_cell(row.get(column))
                cells.append(f'<Cell><Data ss:Type="{cell_type}">{cell_value}</Data></Cell>')
            row_xml.append(f"<Row>{''.join(cells)}</Row>")
    else:
        row_xml.append('<Row><Cell><Data ss:Type="String">No rows returned</Data></Cell></Row>')

    return f"""<?xml version="1.0"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:x="urn:schemas-microsoft-com:office:excel"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
  <Styles>
    <Style ss:ID="header">
      <Font ss:Bold="1"/>
      <Interior ss:Color="#EEF5FB" ss:Pattern="Solid"/>
    </Style>
  </Styles>
  <Worksheet ss:Name="{worksheet_name}">
    <Table>
      {''.join(row_xml)}
    </Table>
    <WorksheetOptions xmlns="urn:schemas-microsoft-com:office:excel">
      <ProtectObjects>False</ProtectObjects>
      <ProtectScenarios>False</ProtectScenarios>
    </WorksheetOptions>
  </Worksheet>
</Workbook>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/healthz")
def healthcheck():
    """Deep health check — verifies DB connectivity."""
    db_ok = DB.is_connected()
    if not db_ok:
        return JSONResponse({"ok": False, "error": "Database not connected"}, status_code=503)
    return {"ok": True, "database": "connected"}


@app.get("/api/config")
def get_runtime_config():
    return {
        "default_provider": DEFAULT_PROVIDER,
        "default_model": DEFAULT_MODEL,
        "default_openai_compat_model": DEFAULT_OPENAI_COMPAT_MODEL,
        "default_openai_compat_base_url": DEFAULT_OPENAI_COMPAT_BASE_URL,
        "provider_options": [
            {
                "id": "anthropic",
                "label": "Anthropic",
                "model_placeholder": DEFAULT_MODEL,
                "base_url_placeholder": "",
                "api_key_placeholder": "Anthropic API key",
            },
            {
                "id": OPENAI_COMPAT_PROVIDER,
                "label": "OpenAI-compatible",
                "model_placeholder": DEFAULT_OPENAI_COMPAT_MODEL,
                "base_url_placeholder": DEFAULT_OPENAI_COMPAT_BASE_URL,
                "api_key_placeholder": "Provider API key",
            },
        ],
    }


@app.get("/api/auth/config")
def get_auth_config():
    return {
        "auth_required": AUTH_REQUIRED,
        "dev_sso_enabled": DEV_SSO_ENABLED,
        "providers": [{"id": provider.lower(), "label": provider} for provider in SSO_PROVIDERS],
    }


@app.get("/api/auth/session")
def get_auth_session(request: Request):
    user = _get_auth_user(request)
    return {"authenticated": user is not None, "user": user}


@app.post("/api/auth/login")
def login_with_sso(req: LoginRequest, response: Response):
    provider = req.provider.strip().lower()
    allowed = {provider_name.lower() for provider_name in SSO_PROVIDERS}

    if provider not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported identity provider")
    if not DEV_SSO_ENABLED:
        raise HTTPException(status_code=501, detail="Real OIDC/SAML is not configured yet.")

    auth_token = secrets.token_urlsafe(32)
    _auth_sessions[auth_token] = AuthState(user=_create_demo_user(provider), last_accessed=_now())
    response.set_cookie(
        AUTH_COOKIE_NAME,
        auth_token,
        httponly=True,
        samesite="lax",
        secure=SECURE_COOKIES,
        max_age=SESSION_TTL_MINUTES * 60,
    )
    return {"ok": True, "user": _auth_sessions[auth_token].user}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    auth_token = request.cookies.get(AUTH_COOKIE_NAME)
    if auth_token:
        _auth_sessions.pop(auth_token, None)
    response.delete_cookie(AUTH_COOKIE_NAME)
    return {"ok": True}


@app.get("/api/me/access")
def get_access_summary(request: Request):
    user = _require_auth(request)
    profile = _current_access_profile(request)
    return {"user": user, "access_profile": profile.summary()}


@app.get("/api/me/history")
def get_recent_history(request: Request):
    user = _require_auth(request)
    return {"questions": CONTEXT_STORE.recent_questions(user["email"])}


@app.post("/api/feedback")
def record_feedback(req: FeedbackRequest, request: Request):
    user = _require_auth(request)

    try:
        feedback = CONTEXT_STORE.record_feedback(user["email"], req.memory_id, req.vote.strip().lower())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if feedback is None:
        raise HTTPException(status_code=404, detail="Response not found for this user.")

    return feedback


@app.post("/api/reports/export/excel")
def export_report_excel(req: ReportExportRequest, request: Request):
    profile = _current_access_profile(request)
    executor = ToolExecutor(DB)
    raw_result = executor.execute(
        "generate_standard_report",
        {"report_type": req.report_type.strip().lower(), "explanation": ""},
        access_profile=profile,
    )

    try:
        payload = json.loads(raw_result)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Could not prepare the Excel export.") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Report export returned an unexpected payload.")
    if payload.get("error"):
        raise HTTPException(status_code=400, detail=str(payload["error"]))

    title = (payload.get("report_name") or req.title or "HR Report").strip()
    rows = payload.get("results") or []
    workbook = _build_excel_xml(title, rows)
    filename = _excel_file_name(title)

    return Response(
        content=workbook.encode("utf-8"),
        media_type="application/vnd.ms-excel",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/context/documents")
def list_context_documents(request: Request):
    profile = _current_access_profile(request)
    return {"documents": _filter_documents_for_profile(CONTEXT_STORE.list_documents(), profile)}


@app.post("/api/context/documents")
def add_context_document(req: ContextDocumentRequest, request: Request):
    profile = _current_access_profile(request)
    _ensure_document_tags_allowed(req.tags, profile)
    return CONTEXT_STORE.add_document(req.title, req.content, req.tags)


@app.get("/api/stats")
def get_stats(request: Request):
    profile = _current_access_profile(request)
    stats = DB.get_table_stats(access_profile=profile)
    stats["access_profile"] = profile.summary()
    return JSONResponse(stats)


@app.post("/api/reset")
def reset_session(req: ResetRequest, request: Request):
    _current_access_profile(request)
    _sessions.pop(req.session_id, None)
    return {"ok": True}


@app.post("/api/chat")
async def chat_sse(req: ChatRequest, request: Request):
    _check_rate_limit(request)
    access_profile = _current_access_profile(request)

    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Empty message")

    llm_config = _build_llm_config(req)
    if not llm_config.model:
        raise HTTPException(status_code=400, detail="Model is required")
    if llm_config.provider == "anthropic" and not llm_config.api_key:
        raise HTTPException(status_code=400, detail="Anthropic API key required")

    session_id = req.session_id or str(uuid.uuid4())
    table_context = None
    if req.table_context_rows:
        table_context = {
            "title": req.table_context_title.strip() or "Latest Table",
            "rows": req.table_context_rows,
        }

    logger.info(
        "Chat request user=%s provider=%s model=%s session=%s",
        access_profile.email,
        llm_config.provider,
        llm_config.model,
        session_id[:8],
    )

    async def event_stream() -> AsyncGenerator[str, None]:
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"

        try:
            agent = _get_or_create_session(session_id, llm_config)
            for event in agent.chat(req.message, access_profile=access_profile, table_context=table_context):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            logger.exception("Chat stream error for session=%s", session_id[:8])
            yield f"data: {json.dumps({'type': 'error', 'message': 'An internal error occurred. Please try again.'})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def serve_index():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse({"error": "Frontend not found. Run the server from hr_agent_platform/"})


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    print("\nHR Intelligence Platform")
    print(f"Open http://localhost:{port} in your browser\n")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
