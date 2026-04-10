"""tdata conversion — convert .session files to TDesktop tdata format."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import types
from pathlib import Path

logger = logging.getLogger(__name__)

# Block opentele.tl before any opentele import.
# opentele.tl uses @extend_class which crashes on Python 3.13+.
for _mod in (
    "opentele.tl",
    "opentele.tl.shared",
    "opentele.tl.telethon",
    "opentele.tl.configs",
):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))

TDATA_CACHE = Path(os.environ.get("TDATA_CACHE", "/app/data/tdata_cache"))

# TelegramDesktop official API credentials (public, same for all TDesktop clients)
_TD_API_ID = 611335
_TD_API_HASH = "d524b414d21f4d37f08684c1df41ac9c"


def needs_user_id_fetch(session_type: str, user_id: int | None) -> bool:
    """Check if we need to fetch user_id from Telegram (Telethon sessions only)."""
    return session_type == "telethon" and user_id is None


async def fetch_telethon_user_id(session_path: str) -> int:
    """Connect briefly with Telethon to fetch user_id via get_me()."""
    from telethon import TelegramClient

    client = TelegramClient(session_path, api_id=_TD_API_ID, api_hash=_TD_API_HASH)
    try:
        await asyncio.wait_for(client.connect(), timeout=10)
        me = await asyncio.wait_for(client.get_me(), timeout=10)
        if me is None:
            raise ValueError("Telethon session is not authorized")
        return me.id
    finally:
        await client.disconnect()


async def convert_to_tdata(
    dc_id: int,
    auth_key: bytes,
    user_id: int | None,
    session_name: str,
    src_mtime: float = 0.0,
) -> Path:
    """Convert auth data to tdata/ directory. Returns work_dir path.

    Uses cache — only reconverts if source file is newer than cached tdata.
    """
    TDATA_CACHE.mkdir(parents=True, exist_ok=True)
    work_dir = TDATA_CACHE / session_name
    tdata_dir = work_dir / "tdata"

    need_convert = not tdata_dir.exists()
    if not need_convert and src_mtime:
        need_convert = src_mtime > tdata_dir.stat().st_mtime

    if need_convert:
        if work_dir.exists():
            shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True)
        # opentele is CPU-bound sync code — run in executor to not block event loop
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _write_tdata, dc_id, auth_key, user_id, str(work_dir))

    return work_dir


def _write_tdata(
    dc_id: int, auth_key: bytes, user_id: int | None, output_dir: str,
) -> None:
    """Write tdata/ via opentele."""
    from opentele.td import TDesktop, Account, AuthKey, AuthKeyType
    from opentele.td.account import DcId
    from opentele.api import API

    dc = DcId(dc_id)
    key = AuthKey(auth_key, AuthKeyType.ReadFromFile, dc)

    client = TDesktop()
    client._TDesktop__generateLocalKey()
    account = Account(owner=client, api=API.TelegramDesktop)
    account._setMtpAuthorizationCustom(dc, user_id or 0, [key])
    client._addSingleAccount(account)
    client.SaveTData(str(Path(output_dir) / "tdata"))
