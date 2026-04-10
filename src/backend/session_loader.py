"""Universal Telegram session reader.

Extracts auth_key + dc_id from any .session file (Telethon/Pyrogram/Kurigram).
No normalization needed — TGConvertor accepts raw auth data directly.
"""

import sqlite3


def detect_type(path: str) -> str | None:
    """Detect session library type from SQLite schema.

    Returns 'telethon', 'pyrogram', 'kurigram', or None.
    """
    try:
        conn = sqlite3.connect(path, timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        if "sessions" not in tables:
            conn.close()
            return None
        cur.execute("PRAGMA table_info(sessions)")
        cols = {r[1] for r in cur.fetchall()}
        conn.close()
        if "server_address" in cols and "api_id" in cols:
            return "kurigram"
        if "server_address" in cols:
            return "telethon"
        if "test_mode" in cols and "user_id" in cols:
            return "pyrogram"
    except Exception:
        pass
    return None


def extract_auth_data(path: str) -> tuple[int, bytes, int | None]:
    """Extract (dc_id, auth_key, user_id) from any .session file.

    Raises ValueError if file is not a valid session.
    """
    session_type = detect_type(path)
    if session_type is None:
        raise ValueError(f"Unknown session format: {path}")

    conn = sqlite3.connect(path, timeout=5)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(sessions)")
    cols = {r[1] for r in cur.fetchall()}

    select = ["dc_id", "auth_key"]
    if "user_id" in cols:
        select.append("user_id")

    cur.execute(f"SELECT {', '.join(select)} FROM sessions LIMIT 1")
    row = dict(zip(select, cur.fetchone()))
    conn.close()

    return row["dc_id"], row["auth_key"], row.get("user_id")
