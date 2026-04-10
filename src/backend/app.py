"""FastAPI backend — multi-session API + VNC proxy + SSE file watcher."""

import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.websockets import WebSocket

from backend.fs_watcher import watch_sessions
from backend.session_manager import SessionManager
from backend.vnc_proxy import proxy_http, proxy_ws

SESSIONS_DIR = Path(os.environ.get("SESSIONS_DIR", "/app/sessions"))
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# ── Middleware ──


class ClipboardHeaderMiddleware(BaseHTTPMiddleware):
    """Add Permissions-Policy header to allow clipboard access in iframes."""
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Permissions-Policy"] = "clipboard-read=*, clipboard-write=*"
        return response


app = FastAPI(title="tdsession")
app.add_middleware(ClipboardHeaderMiddleware)
manager = SessionManager()


class LaunchRequest(BaseModel):
    path: str


def _scan_tree(directory: Path, base: Path) -> list[dict]:
    """Recursively scan directory for .session files. Skip empty dirs."""
    entries: list[dict] = []
    try:
        items = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name))
    except PermissionError:
        return entries

    for item in items:
        rel = str(item.relative_to(base))
        if item.is_dir():
            children = _scan_tree(item, base)
            if children:
                entries.append(
                    {"name": item.name, "path": rel, "type": "dir", "children": children}
                )
        elif item.suffix == ".session":
            entries.append({"name": item.name, "path": rel, "type": "file"})
    return entries


# ── Session API ──


@app.get("/api/sessions")
async def list_sessions():
    if not SESSIONS_DIR.exists():
        return {"tree": []}
    return {"tree": _scan_tree(SESSIONS_DIR, SESSIONS_DIR)}


@app.get("/api/sessions/watch")
async def watch_sessions_sse():
    return StreamingResponse(
        watch_sessions(SESSIONS_DIR, _scan_tree),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/launch")
async def launch(req: LaunchRequest):
    safe = Path(req.path)
    if ".." in safe.parts:
        raise HTTPException(400, "Invalid path")

    full_path = (SESSIONS_DIR / safe).resolve()
    if not full_path.exists() or not full_path.is_relative_to(SESSIONS_DIR.resolve()):
        raise HTTPException(404, f"Session not found: {req.path}")

    try:
        result = await manager.launch(req.path)
        return result
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Launch failed: {e}")


@app.post("/api/stop/{session_id}")
async def stop(session_id: str):
    try:
        return await manager.stop(session_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/stop-all")
async def stop_all():
    return await manager.stop_all()


@app.get("/api/status")
async def status():
    return {"sessions": manager.get_all_status()}


@app.get("/api/status/{session_id}")
async def session_status(session_id: str):
    result = manager.get_session_status(session_id)
    if result is None:
        raise HTTPException(404, f"Session not found: {session_id}")
    return result


# ── VNC reverse proxy (per-session) ──


def _get_vnc_port(session_id: str) -> int:
    """Look up VNC port for a session. Raises HTTPException if not found."""
    instance = manager.sessions.get(session_id)
    if not instance:
        raise HTTPException(404, f"Session not found: {session_id}")
    return instance.vnc_port


@app.websocket("/vnc/{session_id}/websockify")
async def vnc_ws(session_id: str, ws: WebSocket):
    port = _get_vnc_port(session_id)
    await proxy_ws(ws, port)


@app.websocket("/websockify")
async def vnc_ws_root(ws: WebSocket):
    """Fallback: KasmVNC client connects to absolute /websockify.
    Determine session from Referer header."""
    referer = (ws.headers.get("referer") or ws.headers.get("origin") or "")
    m = re.search(r"/vnc/(sess_[a-f0-9]+)", referer)
    if m:
        session_id = m.group(1)
        port = _get_vnc_port(session_id)
        await proxy_ws(ws, port)
    elif len(manager.sessions) == 1:
        # Single session — use it
        instance = next(iter(manager.sessions.values()))
        await proxy_ws(ws, instance.vnc_port)
    else:
        await ws.close(code=4000, reason="Cannot determine session")


@app.api_route("/vnc/{session_id}/{path:path}", methods=["GET", "POST"])
async def vnc_proxy_route(session_id: str, request: Request):
    port = _get_vnc_port(session_id)
    prefix = f"/vnc/{session_id}"
    return await proxy_http(request, port, prefix)


@app.api_route("/vnc/{session_id}", methods=["GET"])
async def vnc_root(session_id: str, request: Request):
    port = _get_vnc_port(session_id)
    prefix = f"/vnc/{session_id}"
    return await proxy_http(request, port, prefix)


# ── Static frontend ──


from fastapi.staticfiles import StaticFiles

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))
