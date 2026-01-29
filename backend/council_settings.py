"""Runtime-configurable council settings with file persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Any, List

from .config import (
    DATA_DIR,
    COUNCIL_MODELS,
    COUNCIL_ALIASES,
    CHAIRMAN_MODEL,
    CHAIRMAN_ALIAS,
    TITLE_MODEL,
    resolve_model_for_region,
)

MAX_COUNCIL_MEMBERS = 7
SETTINGS_FILENAME = "council_settings.json"

_SETTINGS: Dict[str, Any] | None = None


def _settings_path() -> str:
    data_root = Path(DATA_DIR).parent
    return os.path.join(data_root, SETTINGS_FILENAME)


def _ensure_settings_dir() -> None:
    Path(_settings_path()).parent.mkdir(parents=True, exist_ok=True)


def _default_settings() -> Dict[str, Any]:
    members: List[Dict[str, Any]] = []
    for index, model_id in enumerate(COUNCIL_MODELS):
        alias = COUNCIL_ALIASES[index] if index < len(COUNCIL_ALIASES) else f"Member {index + 1}"
        members.append(
            {
                "id": f"member-{index + 1}",
                "alias": alias,
                "model_id": model_id,
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
    }


def load_settings() -> Dict[str, Any]:
    """Load settings from disk or create defaults."""
    _ensure_settings_dir()
    path = _settings_path()
    if not os.path.exists(path):
        settings = _default_settings()
        save_settings(settings)
        return settings

    with open(path, "r") as file:
        return json.load(file)


def save_settings(settings: Dict[str, Any]) -> None:
    """Persist settings to disk."""
    _ensure_settings_dir()
    path = _settings_path()
    with open(path, "w") as file:
        json.dump(settings, file, indent=2)


def get_settings() -> Dict[str, Any]:
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = load_settings()
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
