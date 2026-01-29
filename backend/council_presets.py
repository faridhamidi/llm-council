"""Council settings presets with file persistence."""

from __future__ import annotations

import json
import os
import uuid
import datetime as dt
from pathlib import Path
from typing import Dict, Any, List, Tuple

from .config import DATA_DIR
from .council_settings import get_settings, MAX_COUNCIL_MEMBERS

PRESETS_FILENAME = "council_presets.json"
PRESETS_VERSION = 1

_PRESETS: Dict[str, Any] | None = None


def _presets_path() -> str:
    data_root = Path(DATA_DIR).parent
    return os.path.join(data_root, PRESETS_FILENAME)


def _ensure_presets_dir() -> None:
    Path(_presets_path()).parent.mkdir(parents=True, exist_ok=True)


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
        "version": 1,
        "max_members": MAX_COUNCIL_MEMBERS,
        "members": members,
        "chairman_id": members[0]["id"],
        "chairman_label": "Chairman",
        "title_model_id": title_model,
        "use_system_prompt_stage2": True,
        "use_system_prompt_stage3": True,
    }
    return _normalize_settings(settings)


def _default_presets() -> Dict[str, Any]:
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
    return {"version": PRESETS_VERSION, "presets": presets}


def _upgrade_presets(data: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    changed = False
    if data.get("version") != PRESETS_VERSION:
        data["version"] = PRESETS_VERSION
        changed = True
    presets = data.get("presets", [])
    for preset in presets:
        if "id" not in preset:
            preset["id"] = str(uuid.uuid4())
            changed = True
        if "created_at" not in preset:
            preset["created_at"] = _now_iso()
            changed = True
        if "settings" in preset:
            preset["settings"] = _normalize_settings(preset["settings"])
    return data, changed


def load_presets() -> Dict[str, Any]:
    _ensure_presets_dir()
    path = _presets_path()
    if not os.path.exists(path):
        presets = _default_presets()
        save_presets(presets)
        return presets
    with open(path, "r") as file:
        data = json.load(file)
    data, changed = _upgrade_presets(data)
    if changed:
        save_presets(data)
    return data


def save_presets(data: Dict[str, Any]) -> None:
    _ensure_presets_dir()
    path = _presets_path()
    with open(path, "w") as file:
        json.dump(data, file, indent=2)


def get_presets() -> Dict[str, Any]:
    global _PRESETS
    if _PRESETS is None:
        _PRESETS = load_presets()
    return _PRESETS


def list_presets() -> List[Dict[str, Any]]:
    data = get_presets()
    return [
        {
            "id": preset.get("id"),
            "name": preset.get("name"),
            "created_at": preset.get("created_at"),
        }
        for preset in data.get("presets", [])
    ]


def _find_preset_by_name(name: str, presets: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    normalized = name.strip().lower()
    for preset in presets:
        if preset.get("name", "").strip().lower() == normalized:
            return preset
    return None


def create_preset(name: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    data = get_presets()
    presets = data.get("presets", [])
    existing = _find_preset_by_name(name, presets)
    if existing:
        existing["settings"] = _normalize_settings(settings)
        existing["name"] = name.strip()
        existing["updated_at"] = _now_iso()
        save_presets(data)
        return existing

    preset = {
        "id": str(uuid.uuid4()),
        "name": name.strip(),
        "created_at": _now_iso(),
        "settings": _normalize_settings(settings),
    }
    presets.append(preset)
    data["presets"] = presets
    save_presets(data)
    return preset


def find_preset(preset_id: str) -> Dict[str, Any] | None:
    data = get_presets()
    for preset in data.get("presets", []):
        if preset.get("id") == preset_id:
            return preset
    return None


def delete_preset(preset_id: str) -> bool:
    data = get_presets()
    presets = data.get("presets", [])
    next_presets = [preset for preset in presets if preset.get("id") != preset_id]
    if len(next_presets) == len(presets):
        return False
    data["presets"] = next_presets
    save_presets(data)
    return True
