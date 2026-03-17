"""
HR Intelligence Platform — FastAPI backend
Replaces Streamlit. Serves the vanilla JS frontend and exposes:
  GET  /api/stats          → DB stats JSON
  POST /api/chat           → SSE stream of agent events
  POST /api/reset          → Clear session conversation history
  GET  /                   → Serves static/index.html
"""

import json
import os
import uuid
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database.connector import HRDatabase
from agent.orchestrator import HRAgent

# ── App setup ────────────────────────────────────────────────────────────────
app = FastAPI(title="HR Intelligence Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"

# ── In-memory session store: session_id → HRAgent instance ───────────────────
_sessions: dict[str, HRAgent] = {}

DB = HRDatabase()


def _get_or_create_session(session_id: str, api_key: str) -> HRAgent:
    if session_id not in _sessions or _sessions[session_id].client.api_key != api_key:
        _sessions[session_id] = HRAgent(api_key=api_key, db=DB)
    return _sessions[session_id]


# ── Request models ────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    api_key: str
    session_id: str = ""


class ResetRequest(BaseModel):
    session_id: str


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/api/stats")
def get_stats():
    try:
        stats = DB.get_table_stats()
        return JSONResponse(stats)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/reset")
def reset_session(req: ResetRequest):
    if req.session_id in _sessions:
        _sessions[req.session_id].reset()
    return {"ok": True}


@app.post("/api/chat")
async def chat_sse(req: ChatRequest):
    if not req.api_key:
        raise HTTPException(status_code=400, detail="API key required")
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Empty message")

    session_id = req.session_id or str(uuid.uuid4())

    async def event_stream() -> AsyncGenerator[str, None]:
        # Send session_id first so client can store it
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"

        try:
            agent = _get_or_create_session(session_id, req.api_key)
            for event in agent.chat(req.message):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Static files (frontend) ───────────────────────────────────────────────────
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def serve_index():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse({"error": "Frontend not found. Run the server from hr_agent_platform/"})


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print(f"\n🧠  HR Intelligence Platform")
    print(f"    Open http://localhost:{port} in your browser\n")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
