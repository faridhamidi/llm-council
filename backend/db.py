"""SQLite helper for LLM Council persistence."""

from __future__ import annotations

import json
import os
import sqlite3
import hashlib
import hmac
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

DB_PATH = os.getenv("COUNCIL_DB_PATH", os.path.join("data", "council.db"))
_DB_INITIALIZED = False


def _ensure_db_dir() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


def _ensure_stages_column(conn: sqlite3.Connection) -> None:
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(messages)").fetchall()]
    if "stages_json" not in columns:
        conn.execute("ALTER TABLE messages ADD COLUMN stages_json TEXT")


def _ensure_multiturn_columns(conn: sqlite3.Connection) -> None:
    """Ensure columns for multi-turn conversation support exist."""
    # Check conversations table for settings_snapshot + mode
    conv_columns = [row["name"] for row in conn.execute("PRAGMA table_info(conversations)").fetchall()]
    if "settings_snapshot" not in conv_columns:
        conn.execute("ALTER TABLE conversations ADD COLUMN settings_snapshot TEXT")
    if "mode" not in conv_columns:
        conn.execute("ALTER TABLE conversations ADD COLUMN mode TEXT DEFAULT 'council'")
    conn.execute("UPDATE conversations SET mode = 'council' WHERE mode IS NULL OR mode = ''")
    
    # Check messages table for message_type, token_count, speaker_response
    msg_columns = [row["name"] for row in conn.execute("PRAGMA table_info(messages)").fetchall()]
    if "message_type" not in msg_columns:
        conn.execute("ALTER TABLE messages ADD COLUMN message_type TEXT DEFAULT 'council'")
    if "token_count" not in msg_columns:
        conn.execute("ALTER TABLE messages ADD COLUMN token_count INTEGER")
    if "speaker_response" not in msg_columns:
        conn.execute("ALTER TABLE messages ADD COLUMN speaker_response TEXT")


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _parse_iso(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts.replace("Z", ""))
    except Exception:
        return datetime.utcnow()


def get_auth_policy() -> str | None:
    with with_connection() as conn:
        return _meta_get(conn, "auth_pin_policy")


def set_auth_policy(policy: str) -> None:
    with with_connection() as conn:
        _meta_set(conn, "auth_pin_policy", policy)


def _migrate_conversations(conn: sqlite3.Connection) -> None:
    data_dir = Path("data") / "conversations"
    if not data_dir.exists():
        return

    row = conn.execute("SELECT COUNT(*) as count FROM conversations").fetchone()
    if row and row["count"] > 0:
        return

    for path in sorted(data_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except Exception:
            continue

        conv_id = payload.get("id")
        if not conv_id:
            continue

        created_at = payload.get("created_at") or _now_iso()
        title = payload.get("title") or "New Conversation"
        messages = payload.get("messages") or []

        conn.execute(
            "INSERT OR IGNORE INTO conversations (id, created_at, title, deleted_at) VALUES (?, ?, ?, NULL)",
            (conv_id, created_at, title),
        )

        base_time = _parse_iso(created_at)
        for index, message in enumerate(messages):
            role = message.get("role")
            msg_time = (base_time + timedelta(seconds=index)).isoformat()
            if role == "user":
                conn.execute(
                    """
                    INSERT INTO messages (conversation_id, role, content, created_at)
                    VALUES (?, 'user', ?, ?)
                    """,
                    (conv_id, message.get("content", ""), msg_time),
                )
            elif role == "assistant":
                stages = []
                if message.get("stage1") is not None:
                    stages.append({
                        "id": "stage-1",
                        "name": "Individual Responses",
                        "prompt": "",
                        "execution_mode": "parallel",
                        "kind": "responses",
                        "results": message.get("stage1"),
                    })
                if message.get("stage2") is not None:
                    stages.append({
                        "id": "stage-2",
                        "name": "Peer Rankings",
                        "prompt": "",
                        "execution_mode": "parallel",
                        "kind": "rankings",
                        "results": message.get("stage2"),
                    })
                if message.get("stage3") is not None:
                    stages.append({
                        "id": "stage-3",
                        "name": "Final Synthesis",
                        "prompt": "",
                        "execution_mode": "sequential",
                        "kind": "synthesis",
                        "results": message.get("stage3"),
                    })
                conn.execute(
                    """
                    INSERT INTO messages (conversation_id, role, stages_json, created_at)
                    VALUES (?, 'assistant', ?, ?)
                    """,
                    (
                        conv_id,
                        json.dumps(stages) if stages else None,
                        msg_time,
                    ),
                )

    trash_dir = data_dir / ".trash"
    if not trash_dir.exists():
        return

    for path in sorted(trash_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except Exception:
            continue

        conv_id = payload.get("id")
        if not conv_id:
            continue

        created_at = payload.get("created_at") or _now_iso()
        title = payload.get("title") or "New Conversation"
        messages = payload.get("messages") or []

        conn.execute(
            "INSERT OR IGNORE INTO conversations (id, created_at, title, deleted_at) VALUES (?, ?, ?, ?)",
            (conv_id, created_at, title, _now_iso()),
        )

        base_time = _parse_iso(created_at)
        for index, message in enumerate(messages):
            role = message.get("role")
            msg_time = (base_time + timedelta(seconds=index)).isoformat()
            if role == "user":
                conn.execute(
                    """
                    INSERT INTO messages (conversation_id, role, content, created_at)
                    VALUES (?, 'user', ?, ?)
                    """,
                    (conv_id, message.get("content", ""), msg_time),
                )
            elif role == "assistant":
                stages = []
                if message.get("stage1") is not None:
                    stages.append({
                        "id": "stage-1",
                        "name": "Individual Responses",
                        "prompt": "",
                        "execution_mode": "parallel",
                        "kind": "responses",
                        "results": message.get("stage1"),
                    })
                if message.get("stage2") is not None:
                    stages.append({
                        "id": "stage-2",
                        "name": "Peer Rankings",
                        "prompt": "",
                        "execution_mode": "parallel",
                        "kind": "rankings",
                        "results": message.get("stage2"),
                    })
                if message.get("stage3") is not None:
                    stages.append({
                        "id": "stage-3",
                        "name": "Final Synthesis",
                        "prompt": "",
                        "execution_mode": "sequential",
                        "kind": "synthesis",
                        "results": message.get("stage3"),
                    })
                conn.execute(
                    """
                    INSERT INTO messages (conversation_id, role, stages_json, created_at)
                    VALUES (?, 'assistant', ?, ?)
                    """,
                    (
                        conv_id,
                        json.dumps(stages) if stages else None,
                        msg_time,
                    ),
                )


def _migrate_presets(conn: sqlite3.Connection) -> None:
    presets_path = Path("data") / "council_presets.json"
    if not presets_path.exists():
        return

    row = conn.execute("SELECT COUNT(*) as count FROM council_presets").fetchone()
    if row and row["count"] > 0:
        return

    try:
        payload = json.loads(presets_path.read_text())
    except Exception:
        return

    presets = payload.get("presets", [])
    for preset in presets:
        preset_id = preset.get("id")
        name = preset.get("name")
        created_at = preset.get("created_at") or _now_iso()
        settings = preset.get("settings", {})
        if not preset_id or not name:
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO council_presets (id, name, created_at, updated_at, settings_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                preset_id,
                name,
                created_at,
                preset.get("updated_at"),
                json.dumps(settings),
            ),
        )


def _migrate_settings(conn: sqlite3.Connection) -> None:
    settings_path = Path("data") / "council_settings.json"
    if not settings_path.exists():
        return

    row = conn.execute("SELECT COUNT(*) as count FROM council_settings").fetchone()
    if row and row["count"] > 0:
        return

    try:
        payload = json.loads(settings_path.read_text())
    except Exception:
        return

    conn.execute(
        "INSERT INTO council_settings (id, settings_json, updated_at) VALUES (1, ?, ?)",
        (json.dumps(payload), _now_iso()),
    )


def _migrate_from_json(conn: sqlite3.Connection) -> None:
    if _meta_get(conn, "json_migrated"):
        return

    _migrate_conversations(conn)
    _migrate_presets(conn)
    _migrate_settings(conn)

    _meta_set(conn, "json_migrated", _now_iso())


def _backfill_stages_json(conn: sqlite3.Connection) -> None:
    if _meta_get(conn, "stages_backfilled"):
        return
    rows = conn.execute(
        """
        SELECT id, stage1_json, stage2_json, stage3_json, stages_json
        FROM messages
        WHERE stages_json IS NULL
          AND (stage1_json IS NOT NULL OR stage2_json IS NOT NULL OR stage3_json IS NOT NULL)
        """
    ).fetchall()
    for row in rows:
        stages = []
        try:
            stage1 = json.loads(row["stage1_json"]) if row["stage1_json"] else None
            stage2 = json.loads(row["stage2_json"]) if row["stage2_json"] else None
            stage3 = json.loads(row["stage3_json"]) if row["stage3_json"] else None
        except Exception:
            continue
        if stage1 is not None:
            stages.append({
                "id": "stage-1",
                "name": "Individual Responses",
                "prompt": "",
                "execution_mode": "parallel",
                "kind": "responses",
                "results": stage1,
            })
        if stage2 is not None:
            stages.append({
                "id": "stage-2",
                "name": "Peer Rankings",
                "prompt": "",
                "execution_mode": "parallel",
                "kind": "rankings",
                "results": stage2,
            })
        if stage3 is not None:
            stages.append({
                "id": "stage-3",
                "name": "Final Synthesis",
                "prompt": "",
                "execution_mode": "sequential",
                "kind": "synthesis",
                "results": stage3,
            })
        if stages:
            conn.execute(
                "UPDATE messages SET stages_json = ? WHERE id = ?",
                (json.dumps(stages), row["id"]),
            )
    _meta_set(conn, "stages_backfilled", _now_iso())


def init_db() -> None:
    global _DB_INITIALIZED
    if _DB_INITIALIZED:
        return

    _ensure_db_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
              key TEXT PRIMARY KEY,
              value TEXT
            );

            CREATE TABLE IF NOT EXISTS conversations (
              id TEXT PRIMARY KEY,
              created_at TEXT NOT NULL,
              title TEXT NOT NULL,
              deleted_at TEXT,
              mode TEXT NOT NULL DEFAULT 'council'
            );

            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              conversation_id TEXT NOT NULL,
              role TEXT NOT NULL,
              content TEXT,
              stage1_json TEXT,
              stage2_json TEXT,
              stage3_json TEXT,
              stages_json TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_conversation
              ON messages(conversation_id);

            CREATE INDEX IF NOT EXISTS idx_conversations_deleted
              ON conversations(deleted_at);

            CREATE TABLE IF NOT EXISTS council_presets (
              id TEXT PRIMARY KEY,
              name TEXT UNIQUE NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT,
              settings_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS council_settings (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              settings_json TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        _migrate_from_json(conn)
        _ensure_stages_column(conn)
        _ensure_multiturn_columns(conn)
        _backfill_stages_json(conn)
        conn.commit()
    finally:
        conn.close()
    _DB_INITIALIZED = True


def connect() -> sqlite3.Connection:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def with_connection() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def check_db() -> None:
    with with_connection() as conn:
        conn.execute("SELECT 1").fetchone()


def has_auth_pin() -> bool:
    with with_connection() as conn:
        return _meta_get(conn, "auth_pin") is not None


def set_auth_pin(pin: str) -> None:
    salt = secrets.token_bytes(16)
    iterations = 120_000
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, iterations)
    stored = f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"
    with with_connection() as conn:
        _meta_set(conn, "auth_pin", stored)
        conn.commit()


def verify_auth_pin(pin: str) -> bool:
    with with_connection() as conn:
        stored = _meta_get(conn, "auth_pin")
        if not stored:
            return False

    try:
        scheme, iterations_str, salt_hex, digest_hex = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except Exception:
        return False

    computed = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(expected, computed)
