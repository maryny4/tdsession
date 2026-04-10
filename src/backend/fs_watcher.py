"""Filesystem watcher — monitors sessions directory, pushes SSE updates."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import AsyncGenerator

from watchfiles import awatch

logger = logging.getLogger(__name__)


async def watch_sessions(
    sessions_dir: Path,
    scan_tree_fn,
) -> AsyncGenerator[str, None]:
    """Async generator yielding SSE-formatted tree updates.

    Args:
        sessions_dir: Path to sessions directory
        scan_tree_fn: Callable(directory, base) -> list[dict] that builds the tree
    """
    # Send initial tree
    tree = scan_tree_fn(sessions_dir, sessions_dir) if sessions_dir.exists() else []
    yield f"event: tree_update\ndata: {json.dumps({'tree': tree})}\n\n"

    if not sessions_dir.exists():
        return

    async for changes in awatch(sessions_dir, recursive=True):
        # Filter: only care about .session files
        session_changed = any(
            path.endswith(".session")
            for change_type, path in changes
        )
        if session_changed:
            tree = scan_tree_fn(sessions_dir, sessions_dir)
            yield f"event: tree_update\ndata: {json.dumps({'tree': tree})}\n\n"
