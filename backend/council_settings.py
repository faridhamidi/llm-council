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
    DEFAULT_MEMBER_MAX_OUTPUT_TOKENS,
    MAX_MEMBER_MAX_OUTPUT_TOKENS,
    resolve_model_for_region,
    DEFAULT_SPEAKER_CONTEXT_LEVEL,
)
from .db import with_connection

MAX_COUNCIL_MEMBERS = 64
MAX_COUNCIL_STAGES = 10
MAX_STAGE_MEMBERS = 6

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


def _normalize_member_max_output_tokens(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MEMBER_MAX_OUTPUT_TOKENS
    if parsed < 1:
        return DEFAULT_MEMBER_MAX_OUTPUT_TOKENS
    return min(parsed, MAX_MEMBER_MAX_OUTPUT_TOKENS)


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
    
    # Map old Member UUID -> ordered list of new "clean" IDs (e.g. "member-1")
    # This preserves intent even if duplicate member IDs slipped in.
    member_map: Dict[str, List[str]] = {}
    clean_members = []
    
    for idx, member in enumerate(new_settings.get("members", [])):
        old_id = member.get("id")
        new_id = f"member-{idx + 1}"
        member_map.setdefault(old_id, []).append(new_id)
        member["id"] = new_id
        clean_members.append(member)
    
    new_settings["members"] = clean_members

    # Update Chairman ID
    old_chairman_id = new_settings.get("chairman_id")
    if old_chairman_id in member_map:
        new_settings["chairman_id"] = member_map[old_chairman_id][0]

    # Map old Stage UUID -> new "clean" ID (e.g. "stage-1")
    clean_stages = []
    for idx, stage in enumerate(new_settings.get("stages", [])):
        stage["id"] = f"stage-{idx + 1}"
        
        # Update Member IDs in Stage
        new_member_ids = []
        seen_counts: Dict[str, int] = {}
        for mid in stage.get("member_ids", []):
            if mid not in member_map:
                continue
            occurrence = seen_counts.get(mid, 0)
            mapped_ids = member_map[mid]
            if occurrence < len(mapped_ids):
                new_member_ids.append(mapped_ids[occurrence])
                seen_counts[mid] = occurrence + 1
            else:
                # Fallback to first mapped id if stage references exceed member list
                new_member_ids.append(mapped_ids[0])
        # Deduplicate while preserving order to avoid duplicate member IDs in presets
        deduped_member_ids = []
        seen_member_ids = set()
        for mid in new_member_ids:
            if mid in seen_member_ids:
                continue
            seen_member_ids.add(mid)
            deduped_member_ids.append(mid)
        stage["member_ids"] = deduped_member_ids
        clean_stages.append(stage)

    new_settings["stages"] = clean_stages
    return new_settings


def build_default_stages(members: List[Dict[str, Any]], chairman_id: str | None) -> List[Dict[str, Any]]:
    member_ids = [member.get("id") for member in members if member.get("id")]
    default_chairman = chairman_id if chairman_id in member_ids else (member_ids[0] if member_ids else "")
    stage1 = {
        "id": "stage-1",
        "name": "Individual Responses",
        "kind": "responses",
        "prompt": "",
        "execution_mode": "parallel",
        "member_ids": list(member_ids),
    }
    stage2 = {
        "id": "stage-2",
        "name": "Peer Rankings",
        "kind": "rankings",
        "prompt": DEFAULT_STAGE2_PROMPT,
        "execution_mode": "parallel",
        "member_ids": list(member_ids),
    }
    stage3 = {
        "id": "stage-3",
        "name": "Final Synthesis",
        "kind": "synthesis",
        "prompt": DEFAULT_STAGE3_PROMPT,
        "execution_mode": "sequential",
        "member_ids": [default_chairman] if default_chairman else [],
    }
    return [stage1, stage2, stage3]


def ensure_stage_config(settings: Dict[str, Any]) -> Dict[str, Any]:
    if settings.get("stages"):
        stages = settings.get("stages", [])
        members = settings.get("members", [])
        member_ids = [m.get("id") for m in members if m.get("id")]
        chairman_id = settings.get("chairman_id") or (member_ids[0] if member_ids else None)

        def _kind_for_stage(stage: Dict[str, Any], index: int) -> str:
            kind = stage.get("kind")
            if kind in {"responses", "rankings", "synthesis"}:
                return kind

            stage_name = (stage.get("name") or "").strip().lower()
            if "synthesis" in stage_name:
                return "synthesis"
            if "ranking" in stage_name:
                return "rankings"
            if "response" in stage_name:
                return "responses"

            stage_id = (stage.get("id") or "").strip().lower()
            if stage_id.startswith("stage-"):
                suffix = stage_id[len("stage-"):]
                if suffix.isdigit():
                    stage_number = int(suffix)
                    if stage_number == 2:
                        return "rankings"
                    if stage_number == 3:
                        return "synthesis"
                    if stage_number == 1:
                        return "responses"

            # Positional fallback for malformed/legacy stage entries.
            if index == len(stages) - 1:
                return "synthesis"
            if index == 1:
                return "rankings"
            return "responses"

        for index, stage in enumerate(stages):
            stage["id"] = stage.get("id") or f"stage-{index + 1}"
            stage["name"] = stage.get("name") or f"Stage {index + 1}"
            stage["kind"] = _kind_for_stage(stage, index)
            stage["execution_mode"] = "sequential" if stage.get("execution_mode") == "sequential" else "parallel"
            stage["member_ids"] = [
                mid for mid in (stage.get("member_ids") or [])
                if mid in member_ids
            ]

            if stage["kind"] == "rankings" and not stage.get("prompt"):
                stage["prompt"] = DEFAULT_STAGE2_PROMPT
            if stage["kind"] == "synthesis":
                stage["execution_mode"] = "sequential"
                if not stage.get("prompt"):
                    stage["prompt"] = DEFAULT_STAGE3_PROMPT

        synthesis_indexes = [i for i, stage in enumerate(stages) if stage.get("kind") == "synthesis"]

        if not synthesis_indexes:
            stages.append({
                "id": f"stage-{len(stages) + 1}",
                "name": "Final Synthesis",
                "kind": "synthesis",
                "prompt": DEFAULT_STAGE3_PROMPT,
                "execution_mode": "sequential",
                "member_ids": [chairman_id] if chairman_id else [],
            })
            synthesis_index = len(stages) - 1
        else:
            synthesis_index = synthesis_indexes[-1]
            # Keep only the last synthesis stage as canonical.
            for idx in synthesis_indexes[:-1]:
                stages[idx]["kind"] = "responses"
            synthesis_stage = stages.pop(synthesis_index)
            stages.append(synthesis_stage)
            synthesis_index = len(stages) - 1

        synthesis_stage = stages[synthesis_index]
        if not synthesis_stage.get("member_ids"):
            synthesis_stage["member_ids"] = [chairman_id] if chairman_id else []
        if len(synthesis_stage["member_ids"]) > 1:
            synthesis_stage["member_ids"] = [synthesis_stage["member_ids"][0]]

        if synthesis_stage.get("member_ids"):
            settings["chairman_id"] = synthesis_stage["member_ids"][0]
        elif chairman_id:
            settings["chairman_id"] = chairman_id

        settings["stages"] = stages
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
                "max_output_tokens": DEFAULT_MEMBER_MAX_OUTPUT_TOKENS,
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
        normalized_max_tokens = _normalize_member_max_output_tokens(member.get("max_output_tokens"))
        if member.get("max_output_tokens") != normalized_max_tokens:
            member["max_output_tokens"] = normalized_max_tokens
            changed = True
    if "use_system_prompt_stage2" not in settings:
        settings["use_system_prompt_stage2"] = True
        changed = True
    if "use_system_prompt_stage3" not in settings:
        settings["use_system_prompt_stage3"] = True
        changed = True
    before_stage_normalize = json.dumps(settings, sort_keys=True)
    settings = ensure_stage_config(settings)
    after_stage_normalize = json.dumps(settings, sort_keys=True)
    if before_stage_normalize != after_stage_normalize:
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
