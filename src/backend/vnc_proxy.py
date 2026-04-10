"""Reverse proxy for KasmVNC — per-session HTTP + WebSocket routing."""

import asyncio
import logging

import httpx
import websockets
from starlette.requests import Request
from starlette.responses import Response
from starlette.websockets import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

from pathlib import Path

_http = httpx.AsyncClient(verify=False, timeout=10.0)
_LOADING_HTML = (Path(__file__).resolve().parent.parent / "frontend" / "loading.html").read_bytes()


async def proxy_http(request: Request, vnc_port: int, prefix: str) -> Response:
    """Proxy HTTP to a session's KasmVNC. Returns loading page if VNC not ready."""
    path = request.url.path.removeprefix(prefix) or "/"
    url = f"http://127.0.0.1:{vnc_port}{path}"
    if request.url.query:
        url += f"?{request.url.query}"

    try:
        resp = await _http.request(
            method=request.method,
            url=url,
            content=await request.body(),
        )
    except httpx.ConnectError:
        return Response(content=_LOADING_HTML, status_code=200, media_type="text/html")

    skip = {"transfer-encoding", "connection", "keep-alive", "content-security-policy"}
    headers = {k: v for k, v in resp.headers.items() if k.lower() not in skip}

    return Response(content=resp.content, status_code=resp.status_code, headers=headers)


async def proxy_ws(websocket: WebSocket, vnc_port: int) -> None:
    """Proxy WebSocket to a session's KasmVNC."""
    await websocket.accept(subprotocol="binary")

    url = f"ws://127.0.0.1:{vnc_port}/websockify"

    try:
        conn = await websockets.connect(
            url,
            additional_headers={"Origin": f"http://127.0.0.1:{vnc_port}"},
            subprotocols=["binary"],
            open_timeout=10,
            ping_interval=30,
            ping_timeout=60,
        )
        logger.info("WS connected: %s", url)
    except Exception as e:
        logger.exception("WS connection failed %s: %s: %s", url, type(e).__name__, e)
        try:
            await websocket.close()
        except Exception:
            pass
        return

    try:
        async def c2b():
            try:
                while True:
                    msg = await websocket.receive()
                    if msg.get("bytes"):
                        await conn.send(msg["bytes"])
                    elif msg.get("text"):
                        await conn.send(msg["text"])
                    elif msg.get("type") == "websocket.disconnect":
                        break
            except (WebSocketDisconnect, Exception) as e:
                logger.debug("c2b ended: %s: %s", type(e).__name__, e)

        async def b2c():
            try:
                async for msg in conn:
                    if isinstance(msg, bytes):
                        await websocket.send_bytes(msg)
                    else:
                        await websocket.send_text(msg)
            except (WebSocketDisconnect, Exception) as e:
                logger.debug("b2c ended: %s: %s", type(e).__name__, e)

        done, pending = await asyncio.wait(
            [asyncio.create_task(c2b()), asyncio.create_task(b2c())],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
    finally:
        await conn.close()
