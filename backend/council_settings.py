"""Runtime-configurable council settings with SQLite persistence."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Dict, Any, List

from .config import (
    COUNCIL_MODELS,
    COUNCIL_ALIASES,
    CHAIRMAN_MODEL,
    CHAIRMAN_ALIAS,
    TITLE_MODEL,
    resolve_model_for_region,
    DEFAULT_SPEAKER_CONTEXT_LEVEL,
)
from .db import with_connection

MAX_COUNCIL_MEMBERS = 7
MAX_COUNCIL_STAGES = 10
MAX_STAGE_MEMBERS = 5

DEFAULT_STAGE2_PROMPT = """You are evaluating different responses to the following question:

Question: {question}

Here are the responses from different models (anonymized):

{responses}

Your task:
1. First, evaluate each response individually. For each response, explain what it does well and what it does poorly.
2. Then, at the very end of your response, provide a final ranking.

IMPORTANT: You MUST rank all {response_count} responses exactly once.
The responses are: {response_labels}.

IMPORTANT: Your final ranking MUST be formatted EXACTLY as follows:
- Start with the line "FINAL RANKING:" (all caps, with colon)
- Then list the responses from best to worst as a numbered list
- Each line should be: number, period, space, then ONLY the response label (e.g., "1. Response A")
- Do not add any other text or explanations in the ranking section

Example of the correct format for your ENTIRE response:

Response A provides good detail on X but misses Y...
Response B is accurate but lacks depth on Z...
Response C offers the most comprehensive answer...

FINAL RANKING:
1. Response C
2. Response A
3. Response B

Now provide your evaluation and ranking:"""

DEFAULT_STAGE3_PROMPT = """You are the Chairman of an LLM Council. Multiple AI models have provided responses to a user's question, and then ranked each other's responses.

Original Question: {question}

INDIVIDUAL RESPONSES:
{stage1}

PEER RANKINGS:
{stage2}

Your task as Chairman is to synthesize all of this information into a single, comprehensive, accurate answer to the user's original question. Consider:
- The individual responses and their insights
- The peer rankings and what they reveal about response quality
- Any patterns of agreement or disagreement

Provide a clear, well-reasoned final answer that represents the council's collective wisdom:"""

_SETTINGS: Dict[str, Any] | None = None


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def regenerate_settings_ids(settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Regenerate IDs for members and stages.
    CRITICAL: This creates INDEPENDENT copies of members for each stage.
    If 'Member 1' is used in Stage 1 and Stage 2, it becomes two distinct members
    (e.g., 'Stage 1 Member 1' and 'Stage 2 Member 1') with different IDs.
    """
    new_settings = json.loads(json.dumps(settings)) # Deep copy
    
    # map old_id -> member dict
    source_members = {m.get("id"): m for m in new_settings.get("members", [])}
    
    final_members = []
    new_chairman_id = None
    original_chairman_id = new_settings.get("chairman_id")

    # Iterate through stages and explode members
    if "stages" in new_settings:
        for stage in new_settings["stages"]:
            stage["id"] = str(uuid.uuid4()) # New stage ID
            
            old_member_ids = stage.get("member_ids", [])
            new_stage_member_ids = []
            
            for old_mid in old_member_ids:
                source_member = source_members.get(old_mid)
                if source_member:
                    # Create a fresh copy for this stage
                    new_member = json.loads(json.dumps(source_member))
                    new_mid = str(uuid.uuid4())
                    new_member["id"] = new_mid
                    
                    # Add to final list
                    final_members.append(new_member)
                    new_stage_member_ids.append(new_mid)
                    
                    # Update chairman reference if matches
                    # We pin the chairman ID to the first valid occurrence encountered
                    if old_mid == original_chairman_id and new_chairman_id is None:
                        new_chairman_id = new_mid
                else:
                    # Referenced member doesn't exist? Skip or keep?
                    pass
            
            stage["member_ids"] = new_stage_member_ids

    # If chairman was not found in any stage (unlikely for valid presets), 
    # we must ensure it exists or pick one.
    if original_chairman_id and new_chairman_id is None:
        # Check if original chairman is in source_members
        chairman_source = source_members.get(original_chairman_id)
        if chairman_source:
             new_c = json.loads(json.dumps(chairman_source))
             new_cid = str(uuid.uuid4())
             new_c["id"] = new_cid
             final_members.append(new_c)
             new_chairman_id = new_cid

    new_settings["members"] = final_members
    if new_chairman_id:
        new_settings["chairman_id"] = new_chairman_id
    elif final_members:
        # Fallback: make first member chairman
        new_settings["chairman_id"] = final_members[0]["id"]

    return new_settings


def sanitize_settings_ids(settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert internal UUIDs to clean, deterministic human-readable IDs for export/storage.
    e.g. "member-1", "stage-1".
    This decouples the preset from specific runtime IDs.
    """
    new_settings = json.loads(json.dumps(settings))
    
    # Map old Member UUID -> new "clean" ID (e.g. "member-1")
    member_map = {}
    clean_members = []
    
    for idx, member in enumerate(new_settings.get("members", [])):
        old_id = member.get("id")
        new_id = f"member-{idx + 1}"
        member_map[old_id] = new_id
        member["id"] = new_id
        clean_members.append(member)
    
    new_settings["members"] = clean_members

    # Update Chairman ID
    old_chairman_id = new_settings.get("chairman_id")
    if old_chairman_id in member_map:
        new_settings["chairman_id"] = member_map[old_chairman_id]

    # Map old Stage UUID -> new "clean" ID (e.g. "stage-1")
    clean_stages = []
    for idx, stage in enumerate(new_settings.get("stages", [])):
        stage["id"] = f"stage-{idx + 1}"
        
        # Update Member IDs in Stage
        new_member_ids = []
        for mid in stage.get("member_ids", []):
            if mid in member_map:
                new_member_ids.append(member_map[mid])
        stage["member_ids"] = new_member_ids
        clean_stages.append(stage)

    new_settings["stages"] = clean_stages
    return new_settings


def build_default_stages(members: List[Dict[str, Any]], chairman_id: str | None) -> List[Dict[str, Any]]:
    member_ids = [member.get("id") for member in members if member.get("id")]
    default_chairman = chairman_id if chairman_id in member_ids else (member_ids[0] if member_ids else "")
    stage1 = {
        "id": "stage-1",
        "name": "Individual Responses",
        "prompt": "",
        "execution_mode": "parallel",
        "member_ids": list(member_ids),
    }
    stage2 = {
        "id": "stage-2",
        "name": "Peer Rankings",
        "prompt": DEFAULT_STAGE2_PROMPT,
        "execution_mode": "parallel",
        "member_ids": list(member_ids),
    }
    stage3 = {
        "id": "stage-3",
        "name": "Final Synthesis",
        "prompt": DEFAULT_STAGE3_PROMPT,
        "execution_mode": "sequential",
        "member_ids": [default_chairman] if default_chairman else [],
    }
    return [stage1, stage2, stage3]


def ensure_stage_config(settings: Dict[str, Any]) -> Dict[str, Any]:
    if settings.get("stages"):
        stages = settings.get("stages", [])
        for stage in stages:
            if stage.get("id") == "stage-2" and not stage.get("prompt"):
                stage["prompt"] = DEFAULT_STAGE2_PROMPT
            if stage.get("id") == "stage-3" and not stage.get("prompt"):
                stage["prompt"] = DEFAULT_STAGE3_PROMPT
        return settings
    members = settings.get("members", [])
    chairman_id = settings.get("chairman_id")
    settings["stages"] = build_default_stages(members, chairman_id)
    # DECOUPLE: ensuring default stages don't share member objects
    return regenerate_settings_ids(settings)


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

    settings = {
        "version": 2,
        "max_members": MAX_COUNCIL_MEMBERS,
        "members": members,
        "chairman_id": chairman_id,
        "chairman_label": CHAIRMAN_ALIAS,
        "title_model_id": TITLE_MODEL,
        "use_system_prompt_stage2": True,
        "use_system_prompt_stage3": True,
        # Multi-turn conversation settings (Chairman handles follow-ups)
        "speaker_context_level": DEFAULT_SPEAKER_CONTEXT_LEVEL,
    }
    return ensure_stage_config(settings)


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
    if "stages" not in settings:
        settings = ensure_stage_config(settings)
        changed = True
    # Multi-turn conversation fields (Chairman handles follow-ups)
    if "speaker_context_level" not in settings:
        settings["speaker_context_level"] = DEFAULT_SPEAKER_CONTEXT_LEVEL
        changed = True
    # Remove legacy council_speaker_id if present (now always chairman)
    if "council_speaker_id" in settings:
        del settings["council_speaker_id"]
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
    return ensure_stage_config(next_settings)



