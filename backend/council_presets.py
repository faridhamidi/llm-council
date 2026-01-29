"""Council settings presets persisted in SQLite."""

from __future__ import annotations

import json
import uuid
import datetime as dt
from typing import Dict, Any, List

from .db import with_connection
from .council_settings import get_settings, MAX_COUNCIL_MEMBERS

PRESETS_VERSION = 1


def _now_iso() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _normalize_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    normalized = json.loads(json.dumps(settings))
    normalized.setdefault("max_members", MAX_COUNCIL_MEMBERS)
    normalized.setdefault("chairman_label", "Chairman")
    normalized.setdefault("title_model_id", "")
    normalized.setdefault("use_system_prompt_stage2", True)
    normalized.setdefault("use_system_prompt_stage3", True)
    members = normalized.get("members", [])
    for member in members:
        member.setdefault("system_prompt", "")
        member.setdefault("alias", "")
        member.setdefault("model_id", "")
        member.setdefault("id", str(uuid.uuid4()))
    return normalized


def _default_four_member_preset() -> Dict[str, Any]:
    member_model = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    chairman_model = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    title_model = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    members: List[Dict[str, Any]] = []
    for idx in range(4):
        model_id = chairman_model if idx == 0 else member_model
        members.append(
            {
                "id": f"default-4-{idx + 1}",
                "alias": f"Member {idx + 1}",
                "model_id": model_id,
                "system_prompt": "",
            }
        )
    settings = {
        "version": PRESETS_VERSION,
        "max_members": MAX_COUNCIL_MEMBERS,
        "members": members,
        "chairman_id": members[0]["id"],
        "chairman_label": "Chairman",
        "title_model_id": title_model,
        "use_system_prompt_stage2": True,
        "use_system_prompt_stage3": True,
    }
    return _normalize_settings(settings)


def _ensure_defaults() -> None:
    with with_connection() as conn:
        row = conn.execute("SELECT COUNT(*) as count FROM council_presets").fetchone()
        if row and row["count"] > 0:
            return

        hats_settings = _normalize_settings(get_settings())
        presets = [
            {
                "id": str(uuid.uuid4()),
                "name": "Six Thinking Hats",
                "created_at": _now_iso(),
                "settings": hats_settings,
            },
            {
                "id": str(uuid.uuid4()),
                "name": "Default 4 Members",
                "created_at": _now_iso(),
                "settings": _default_four_member_preset(),
            },
        ]

        for preset in presets:
            conn.execute(
                """
                INSERT INTO council_presets (id, name, created_at, settings_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    preset["id"],
                    preset["name"],
                    preset["created_at"],
                    json.dumps(preset["settings"]),
                ),
            )
        conn.commit()


def list_presets() -> List[Dict[str, Any]]:
    _ensure_defaults()
    with with_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at FROM council_presets ORDER BY created_at DESC"
        ).fetchall()

    return [
        {"id": row["id"], "name": row["name"], "created_at": row["created_at"]}
        for row in rows
    ]


def _find_preset_by_name(name: str) -> Dict[str, Any] | None:
    _ensure_defaults()
    normalized = name.strip().lower()
    with with_connection() as conn:
        row = conn.execute(
            "SELECT id, name, created_at, updated_at, settings_json FROM council_presets WHERE lower(name) = ?",
            (normalized,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "settings": json.loads(row["settings_json"]),
    }


def create_preset(name: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_defaults()
    existing = _find_preset_by_name(name)
    normalized_settings = _normalize_settings(settings)
    now = _now_iso()

    with with_connection() as conn:
        if existing:
            conn.execute(
                """
                UPDATE council_presets
                SET settings_json = ?, name = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(normalized_settings), name.strip(), now, existing["id"]),
            )
            conn.commit()
            existing.update({
                "name": name.strip(),
                "updated_at": now,
                "settings": normalized_settings,
            })
            return existing

        preset = {
            "id": str(uuid.uuid4()),
            "name": name.strip(),
            "created_at": now,
            "settings": normalized_settings,
        }
        conn.execute(
            """
            INSERT INTO council_presets (id, name, created_at, settings_json)
            VALUES (?, ?, ?, ?)
            """,
            (preset["id"], preset["name"], preset["created_at"], json.dumps(normalized_settings)),
        )
        conn.commit()
        return preset


def find_preset(preset_id: str) -> Dict[str, Any] | None:
    _ensure_defaults()
    with with_connection() as conn:
        row = conn.execute(
            "SELECT id, name, created_at, updated_at, settings_json FROM council_presets WHERE id = ?",
            (preset_id,),
        ).fetchone()

    if not row:
        return None

    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "settings": json.loads(row["settings_json"]),
    }


def delete_preset(preset_id: str) -> bool:
    _ensure_defaults()
    with with_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM council_presets WHERE id = ?",
            (preset_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
