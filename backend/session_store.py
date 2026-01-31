"""In-memory session store for per-session Bedrock keys."""

from __future__ import annotations

import secrets
import time
from typing import Dict, Tuple, Any

SESSION_COOKIE_NAME = "llm_council_session"
SESSION_TTL_SECONDS = 12 * 60 * 60

_SESSIONS: Dict[str, Dict[str, Any]] = {}


def _now() -> float:
    return time.time()


def _is_expired(session: Dict[str, Any], now: float) -> bool:
    return now - session.get("last_seen", now) > SESSION_TTL_SECONDS


def _touch(session: Dict[str, Any], now: float) -> None:
    session["last_seen"] = now


def ensure_session(session_id: str | None) -> Tuple[str, bool]:
    """Return a valid session id and whether it is newly created."""
    now = _now()
    if session_id:
        session = _SESSIONS.get(session_id)
        if session and not _is_expired(session, now):
            _touch(session, now)
            return session_id, False

    new_id = secrets.token_urlsafe(24)
    _SESSIONS[new_id] = {"last_seen": now, "bedrock_key": None}
    return new_id, True


def get_bedrock_key(session_id: str | None) -> str | None:
    if not session_id:
        return None
    session = _SESSIONS.get(session_id)
    if not session:
        return None
    if _is_expired(session, _now()):
        _SESSIONS.pop(session_id, None)
        return None
    _touch(session, _now())
    return session.get("bedrock_key")


def set_bedrock_key(session_id: str, key: str) -> None:
    session = _SESSIONS.get(session_id)
    if not session:
        session_id, _ = ensure_session(session_id)
        session = _SESSIONS[session_id]
    session["bedrock_key"] = key
    _touch(session, _now())
