"""Multi-session manager — tracks multiple Telegram Desktop instances."""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from backend.session_loader import detect_type, extract_auth_data
from backend.tdesktop import (
    convert_to_tdata,
    fetch_telethon_user_id,
    needs_user_id_fetch,
)

logger = logging.getLogger(__name__)

SESSIONS_DIR = Path(os.environ.get("SESSIONS_DIR", "/app/sessions"))

# X display and VNC port pool — configurable via MAX_SESSIONS env var
MAX_SESSIONS = int(os.environ.get("MAX_SESSIONS", "10"))
VNC_RESOLUTION = os.environ.get("VNC_RESOLUTION", "1920x1080")
DISPLAY_MIN = 100
DISPLAY_MAX = DISPLAY_MIN + MAX_SESSIONS - 1
PORT_MIN = 6170
PORT_MAX = PORT_MIN + MAX_SESSIONS - 1


@dataclass
class SessionInstance:
    session_id: str
    source_path: str
    session_type: str
    display_num: int
    vnc_port: int
    tdesktop_proc: asyncio.subprocess.Process | None = None
    status: str = "starting"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SessionManager:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionInstance] = {}
        self._display_pool: set[int] = set(range(DISPLAY_MIN, DISPLAY_MAX + 1))
        self._port_pool: set[int] = set(range(PORT_MIN, PORT_MAX + 1))

    def _allocate(self) -> tuple[int, int]:
        """Allocate a display number and VNC port. Raises RuntimeError if exhausted."""
        if not self._display_pool or not self._port_pool:
            raise RuntimeError("No available display/port slots")
        display = min(self._display_pool)
        port = PORT_MIN + (display - DISPLAY_MIN)
        self._display_pool.discard(display)
        self._port_pool.discard(port)
        return display, port

    def _release(self, display: int, port: int) -> None:
        """Return display and port to the pools."""
        self._display_pool.add(display)
        self._port_pool.add(port)

    def _find_by_source(self, source_path: str) -> SessionInstance | None:
        """Find a running session by its source .session file path."""
        for s in self.sessions.values():
            if s.source_path == source_path:
                return s
        return None

    def get_all_status(self) -> list[dict]:
        """Return status of all sessions."""
        return [
            {
                "session_id": s.session_id,
                "source_path": s.source_path,
                "session_type": s.session_type,
                "status": s.status,
                "started_at": s.started_at.isoformat(),
                "vnc_port": s.vnc_port,
            }
            for s in self.sessions.values()
        ]

    def get_session_status(self, session_id: str) -> dict | None:
        """Return status of a specific session, or None if not found."""
        s = self.sessions.get(session_id)
        if not s:
            return None
        return {
            "session_id": s.session_id,
            "source_path": s.source_path,
            "session_type": s.session_type,
            "status": s.status,
            "started_at": s.started_at.isoformat(),
            "vnc_port": s.vnc_port,
        }

    async def launch(self, path: str) -> dict:
        """Launch a Telegram Desktop session. Returns session info dict."""
        # Check duplicate
        existing = self._find_by_source(path)
        if existing and existing.status in ("starting", "running"):
            return {
                "session_id": existing.session_id,
                "status": "already_running",
                "source_path": path,
                "session_type": existing.session_type,
            }

        full_path = SESSIONS_DIR / path
        loop = asyncio.get_running_loop()
        session_type = await loop.run_in_executor(None, detect_type, str(full_path))
        if session_type is None:
            raise ValueError(f"Unknown session format: {path}")

        dc_id, auth_key, user_id = await loop.run_in_executor(None, extract_auth_data, str(full_path))

        # Telethon: fetch user_id if missing
        if needs_user_id_fetch(session_type, user_id):
            user_id = await fetch_telethon_user_id(str(full_path))

        display, port = self._allocate()
        session_id = "sess_" + secrets.token_hex(4)

        instance = SessionInstance(
            session_id=session_id,
            source_path=path,
            session_type=session_type,
            display_num=display,
            vnc_port=port,
        )
        self.sessions[session_id] = instance

        # Start processes in background — return immediately so UI isn't blocked
        asyncio.create_task(self._launch_background(
            instance, dc_id, auth_key, user_id, display, port, session_id,
        ))

        return {
            "session_id": session_id,
            "status": "starting",
            "source_path": path,
            "session_type": session_type,
        }

    async def _launch_background(
        self, instance, dc_id, auth_key, user_id, display, port, session_id,
    ) -> None:
        """Start processes in background. Updates instance.status on completion."""
        try:
            await self._start_processes(instance, dc_id, auth_key, user_id)
            instance.status = "running"
        except Exception as e:
            logger.error("Launch failed for %s: %s", session_id, e)
            instance.status = "crashed"
            kill = await asyncio.create_subprocess_exec(
                "vncserver", "-kill", f":{display}",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await kill.communicate()
            self._release(display, port)
            self.sessions.pop(session_id, None)

    async def _start_processes(
        self, instance: SessionInstance, dc_id: int, auth_key: bytes, user_id: int | None,
    ) -> None:
        """Start VNC server + Telegram Desktop for a session."""
        session_name = Path(instance.source_path).stem
        src_mtime = (SESSIONS_DIR / instance.source_path).stat().st_mtime

        work_dir = await convert_to_tdata(
            dc_id, auth_key, user_id, session_name, src_mtime=src_mtime,
        )

        # Write per-session VNC config (websocket_port must be in YAML —
        # vncserver wrapper doesn't reliably pass CLI flags to Xvnc)
        vnc_yaml = Path.home() / ".vnc" / "kasmvnc.yaml"
        vnc_yaml.write_text(
            f"desktop:\n"
            f"  resolution:\n"
            f"    width: {VNC_RESOLUTION.split('x')[0]}\n"
            f"    height: {VNC_RESOLUTION.split('x')[1]}\n"
            f"  allow_resize: true\n"
            f"  pixel_depth: 24\n"
            f"\n"
            f"network:\n"
            f"  protocol: http\n"
            f"  interface: 127.0.0.1\n"
            f"  websocket_port: {instance.vnc_port}\n"
            f"  use_ipv4: true\n"
            f"  use_ipv6: false\n"
            f"  ssl:\n"
            f"    require_ssl: false\n"
            f"    pem_certificate:\n"
            f"    pem_key:\n"
            f"\n"
            f"data_loss_prevention:\n"
            f"  clipboard:\n"
            f"    delay_between_operations: none\n"
            f"    server_to_client:\n"
            f"      enabled: true\n"
            f"      size: unlimited\n"
            f"    client_to_server:\n"
            f"      enabled: true\n"
            f"      size: unlimited\n"
            f"\n"
            f"runtime_configuration:\n"
            f"  allow_client_to_override_kasm_server_settings: true\n"
            f"\n"
            f"command_line:\n"
            f"  prompt: false\n"
        )

        # Start VNC server — use DEVNULL to avoid pipe inheritance.
        # Xvnc inherits fds from vncserver via fork; Python pipes would
        # cause SIGPIPE when communicate() closes them.
        vnc = await asyncio.create_subprocess_exec(
            "vncserver", f":{instance.display_num}",
            "-SecurityTypes", "None",
            "-disableBasicAuth",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await vnc.wait()
        if vnc.returncode != 0:
            raise RuntimeError(f"vncserver exited with code {vnc.returncode}")

        # Wait for X display to become available (poll instead of fixed sleep)
        x_socket = Path(f"/tmp/.X11-unix/X{instance.display_num}")
        for _ in range(20):  # up to 4 seconds
            if x_socket.exists():
                break
            await asyncio.sleep(0.2)

        if not x_socket.exists():
            log_files = glob.glob(str(Path.home() / ".vnc" / f"*:{instance.display_num}.log"))
            log_content = ""
            for lf in log_files:
                log_content += Path(lf).read_text()[-2000:]
            raise RuntimeError(
                f"X display :{instance.display_num} not available. VNC log:\n{log_content}"
            )

        logger.info("VNC started on :%d port %d", instance.display_num, instance.vnc_port, extra={"session_id": instance.session_id})

        # Start Telegram Desktop
        env = os.environ.copy()
        env.update({
            "DISPLAY": f":{instance.display_num}",
            "QT_QPA_PLATFORM": "xcb",
            "XDG_RUNTIME_DIR": "/tmp/runtime-root",
            "LIBGL_ALWAYS_SOFTWARE": "1",
            "QT_OPENGL": "software",
            "QTWEBENGINE_DISABLE_GPU": "1",
            "MESA_GL_VERSION_OVERRIDE": "3.3",
            "GTK_THEME": "Adwaita:dark",
            "QT_LOGGING_RULES": "qt.qpa.theme.dbus=false",
        })

        instance.tdesktop_proc = await asyncio.create_subprocess_exec(
            "dbus-run-session", "--", "telegram-desktop", "-workdir", str(work_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        logger.debug("TDesktop pid=%d", instance.tdesktop_proc.pid, extra={"session_id": instance.session_id})

        # Monitor in background
        asyncio.create_task(self._monitor(instance))

    async def _monitor(self, instance: SessionInstance) -> None:
        """Watch TDesktop process until it exits. Update status on crash."""
        if not instance.tdesktop_proc:
            return
        returncode = await instance.tdesktop_proc.wait()
        if instance.tdesktop_proc.stdout:
            stdout = await instance.tdesktop_proc.stdout.read()
            if stdout:
                logger.debug("TDesktop stdout: %s", stdout.decode(errors="replace")[:500], extra={"session_id": instance.session_id})
        if instance.tdesktop_proc.stderr:
            stderr = await instance.tdesktop_proc.stderr.read()
            if stderr:
                logger.debug("TDesktop stderr: %s", stderr.decode(errors="replace")[:500], extra={"session_id": instance.session_id})
        if returncode != 0 and instance.status != "stopping":
            logger.warning("TDesktop crashed (code=%d)", returncode, extra={"session_id": instance.session_id})
            instance.status = "crashed"
        else:
            logger.info("TDesktop exited (code=%d)", returncode, extra={"session_id": instance.session_id})

    async def stop(self, session_id: str) -> dict:
        """Stop a specific session. Returns status dict."""
        instance = self.sessions.get(session_id)
        if not instance:
            raise ValueError(f"Session not found: {session_id}")

        instance.status = "stopping"

        # Kill Telegram Desktop
        if instance.tdesktop_proc and instance.tdesktop_proc.returncode is None:
            instance.tdesktop_proc.terminate()
            try:
                await asyncio.wait_for(instance.tdesktop_proc.wait(), timeout=3)
            except TimeoutError:
                instance.tdesktop_proc.kill()
                await instance.tdesktop_proc.wait()

        # Kill VNC server
        kill = await asyncio.create_subprocess_exec(
            "vncserver", "-kill", f":{instance.display_num}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await kill.communicate()

        self._release(instance.display_num, instance.vnc_port)
        del self.sessions[session_id]

        return {"status": "stopped", "session_id": session_id}

    async def stop_all(self) -> dict:
        """Stop all sessions."""
        ids = list(self.sessions.keys())
        for sid in ids:
            try:
                await self.stop(sid)
            except Exception as e:
                logger.error("Error stopping session %s: %s", sid, e)
        return {"status": "stopped", "count": len(ids)}
