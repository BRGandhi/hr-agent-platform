"""
HR Intelligence Platform - FastAPI backend
"""

from __future__ import annotations

import json
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.llm_client import LLMConfig, OPENAI_COMPAT_PROVIDER
from agent.orchestrator import HRAgent
from config import (
    ANTHROPIC_API_KEY,
    AUTH_REQUIRED,
    DEFAULT_MODEL,
    DEFAULT_OPENAI_COMPAT_BASE_URL,
    DEFAULT_OPENAI_COMPAT_MODEL,
    DEFAULT_PROVIDER,
    DEV_SSO_ENABLED,
    OPENAI_API_KEY,
    SESSION_TTL_MINUTES,
    SSO_PROVIDERS,
)
from database.connector import HRDatabase

app = FastAPI(title="HR Intelligence Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
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
DB = HRDatabase()


class ChatRequest(BaseModel):
    message: str
    api_key: str = ""
    provider: str = ""
    model: str = ""
    base_url: str = ""
    session_id: str = ""


class ResetRequest(BaseModel):
    session_id: str


class LoginRequest(BaseModel):
    provider: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cleanup_expired_items():
    cutoff = _now() - timedelta(minutes=SESSION_TTL_MINUTES)

    expired_agent_sessions = [
        session_id for session_id, session in _sessions.items() if session.last_accessed < cutoff
    ]
    for session_id in expired_agent_sessions:
        _sessions.pop(session_id, None)

    expired_auth_sessions = [
        session_id for session_id, session in _auth_sessions.items() if session.last_accessed < cutoff
    ]
    for session_id in expired_auth_sessions:
        _auth_sessions.pop(session_id, None)


def _build_llm_config(req: ChatRequest) -> LLMConfig:
    provider = (req.provider or DEFAULT_PROVIDER).strip().lower()
    if provider == OPENAI_COMPAT_PROVIDER:
        model = (req.model or DEFAULT_OPENAI_COMPAT_MODEL or DEFAULT_MODEL).strip()
        base_url = (req.base_url or DEFAULT_OPENAI_COMPAT_BASE_URL).strip()
        api_key = (req.api_key or OPENAI_API_KEY).strip()
    else:
        provider = "anthropic"
        model = (req.model or DEFAULT_MODEL).strip()
        base_url = ""
        api_key = (req.api_key or ANTHROPIC_API_KEY).strip()

    return LLMConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )


def _get_or_create_session(session_id: str, llm_config: LLMConfig) -> HRAgent:
    _cleanup_expired_items()
    session = _sessions.get(session_id)

    if session is None:
        session = SessionState(agent=HRAgent(llm_config=llm_config, db=DB), last_accessed=_now())
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
        "role": "HR Business Partner",
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
    if auth_session is None:
        return None

    auth_session.last_accessed = _now()
    return auth_session.user


def _require_auth(request: Request) -> dict:
    user = _get_auth_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


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
                "api_key_placeholder": "Provider API key (or leave blank for local)",
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
    configured_providers = {provider_name.lower() for provider_name in SSO_PROVIDERS}

    if provider not in configured_providers:
        raise HTTPException(status_code=400, detail="Unsupported identity provider")

    if not DEV_SSO_ENABLED:
        raise HTTPException(
            status_code=501,
            detail="Real SSO is not configured yet. Enable DEV_SSO_ENABLED or add an OIDC provider.",
        )

    auth_token = secrets.token_urlsafe(32)
    _auth_sessions[auth_token] = AuthState(
        user=_create_demo_user(provider),
        last_accessed=_now(),
    )

    response.set_cookie(
        AUTH_COOKIE_NAME,
        auth_token,
        httponly=True,
        samesite="lax",
        secure=False,
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


@app.get("/api/stats")
def get_stats(request: Request):
    _require_auth(request)
    try:
        stats = DB.get_table_stats()
        return JSONResponse(stats)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/reset")
def reset_session(req: ResetRequest, request: Request):
    _require_auth(request)
    _sessions.pop(req.session_id, None)
    return {"ok": True}


@app.post("/api/chat")
async def chat_sse(req: ChatRequest, request: Request):
    _require_auth(request)

    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Empty message")

    llm_config = _build_llm_config(req)
    if not llm_config.model:
        raise HTTPException(status_code=400, detail="Model is required")
    if llm_config.provider == "anthropic" and not llm_config.api_key:
        raise HTTPException(status_code=400, detail="Anthropic API key required")

    session_id = req.session_id or str(uuid.uuid4())

    async def event_stream() -> AsyncGenerator[str, None]:
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"

        try:
            agent = _get_or_create_session(session_id, llm_config)
            for event in agent.chat(req.message):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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
