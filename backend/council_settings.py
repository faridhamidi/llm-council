"""Runtime-configurable council settings with SQLite persistence."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, Any, List

from .config import (
    COUNCIL_MODELS,
    COUNCIL_ALIASES,
    CHAIRMAN_MODEL,
    CHAIRMAN_ALIAS,
    TITLE_MODEL,
    resolve_model_for_region,
)
from .db import with_connection

MAX_COUNCIL_MEMBERS = 7

_SETTINGS: Dict[str, Any] | None = None


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _default_settings() -> Dict[str, Any]:
    members: List[Dict[str, Any]] = []
    for index, model_id in enumerate(COUNCIL_MODELS):
        alias = COUNCIL_ALIASES[index] if index < len(COUNCIL_ALIASES) else f"Member {index + 1}"
        members.append(
            {
                "id": f"member-{index + 1}",
                "alias": alias,
                "model_id": model_id,
                "system_prompt": "",
            }
        )

    chairman_id = next(
        (member["id"] for member in members if member["model_id"] == CHAIRMAN_MODEL),
        members[0]["id"] if members else None,
    )

    return {
        "version": 1,
        "max_members": MAX_COUNCIL_MEMBERS,
        "members": members,
        "chairman_id": chairman_id,
        "chairman_label": CHAIRMAN_ALIAS,
        "title_model_id": TITLE_MODEL,
        "use_system_prompt_stage2": True,
        "use_system_prompt_stage3": True,
    }


def _upgrade_settings(settings: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
    """Ensure new fields exist for older settings payloads."""
    changed = False
    members = settings.get("members", [])
    for member in members:
        if "system_prompt" not in member:
            member["system_prompt"] = ""
            changed = True
    if "use_system_prompt_stage2" not in settings:
        settings["use_system_prompt_stage2"] = True
        changed = True
    if "use_system_prompt_stage3" not in settings:
        settings["use_system_prompt_stage3"] = True
        changed = True
    return settings, changed


def _load_settings_from_db() -> Dict[str, Any]:
    with with_connection() as conn:
        row = conn.execute(
            "SELECT settings_json FROM council_settings WHERE id = 1"
        ).fetchone()

    if row:
        settings = json.loads(row["settings_json"])
        settings, changed = _upgrade_settings(settings)
        if changed:
            save_settings(settings)
        return settings

    settings = _default_settings()
    save_settings(settings)
    return settings


def save_settings(settings: Dict[str, Any]) -> None:
    with with_connection() as conn:
        conn.execute(
            """
            INSERT INTO council_settings (id, settings_json, updated_at)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET settings_json = excluded.settings_json, updated_at = excluded.updated_at
            """,
            (json.dumps(settings), _now_iso()),
        )
        conn.commit()


def get_settings() -> Dict[str, Any]:
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = _load_settings_from_db()
    return _SETTINGS


def update_settings(settings: Dict[str, Any]) -> None:
    global _SETTINGS
    _SETTINGS = settings
    save_settings(settings)


def normalize_settings_for_region(settings: Dict[str, Any], region: str) -> Dict[str, Any]:
    """Return a copy of settings with model ids mapped to the region scope when possible."""
    next_settings = json.loads(json.dumps(settings))
    members = next_settings.get("members", [])
    for member in members:
        member["model_id"] = resolve_model_for_region(member.get("model_id", ""), region)
    if next_settings.get("title_model_id"):
        next_settings["title_model_id"] = resolve_model_for_region(next_settings["title_model_id"], region)
    return next_settings
