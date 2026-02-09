"""Foundation helpers for auto-compaction (feature-gated, no execution by default)."""

from __future__ import annotations

from typing import Any, Dict, List


def should_compact(total_tokens: int, enabled: bool, thresholds: Dict[str, int]) -> bool:
    """
    Decide whether compaction should run using simple token budget thresholds.

    This helper is intentionally strict in foundation mode:
    - disabled feature always returns False
    - invalid thresholds do not trigger compaction
    """
    if not enabled:
        return False

    trigger_tokens = int(thresholds.get("trigger_tokens", 0) or 0)
    target_tokens = int(thresholds.get("target_tokens", 0) or 0)
    if trigger_tokens <= 0 or target_tokens <= 0:
        return False
    if target_tokens >= trigger_tokens:
        return False
    return int(total_tokens or 0) >= trigger_tokens


def select_messages_for_rollup(
    messages: List[Dict[str, Any]],
    compacted_until_message_id: int | None = None,
    recent_turns: int = 12,
) -> Dict[str, Any]:
    """
    Choose which messages are eligible for rollup while preserving recent user turns.

    Returns a dict with:
    - messages_to_rollup
    - messages_to_keep
    - next_compacted_until_message_id
    """
    normalized: List[Dict[str, Any]] = []
    for index, message in enumerate(messages):
        msg_id = message.get("id")
        try:
            resolved_id = int(msg_id)
        except (TypeError, ValueError):
            resolved_id = index + 1
        item = dict(message)
        item["_resolved_message_id"] = resolved_id
        normalized.append(item)

    candidates = [
        message
        for message in normalized
        if compacted_until_message_id is None
        or message["_resolved_message_id"] > compacted_until_message_id
    ]
    if not candidates:
        return {
            "messages_to_rollup": [],
            "messages_to_keep": [],
            "next_compacted_until_message_id": compacted_until_message_id,
        }

    safe_recent_turns = max(0, int(recent_turns or 0))
    user_positions = [index for index, msg in enumerate(candidates) if msg.get("role") == "user"]

    if safe_recent_turns <= 0:
        keep_start = len(candidates)
    elif len(user_positions) <= safe_recent_turns:
        keep_start = 0
    else:
        keep_start = user_positions[-safe_recent_turns]

    rollup = candidates[:keep_start]
    keep = candidates[keep_start:]
    next_id = compacted_until_message_id
    if rollup:
        next_id = max(msg["_resolved_message_id"] for msg in rollup)

    return {
        "messages_to_rollup": [_strip_internal_keys(message) for message in rollup],
        "messages_to_keep": [_strip_internal_keys(message) for message in keep],
        "next_compacted_until_message_id": next_id,
    }


def build_compaction_prompt_payload(
    existing_summary: str,
    messages_to_rollup: List[Dict[str, Any]],
    target_tokens: int,
    summary_max_tokens: int,
) -> Dict[str, Any]:
    """
    Build a model-ready payload for summary compaction.

    Foundation mode only prepares payload text; execution is handled elsewhere.
    """
    transcript = "\n\n".join(_render_rollup_message(message) for message in messages_to_rollup)
    existing = (existing_summary or "").strip()
    user_prompt = (
        "Update the running summary so it preserves all critical facts, decisions, and unresolved questions.\n\n"
        f"Current Summary:\n{existing or '[none]'}\n\n"
        f"New Transcript Block:\n{transcript or '[none]'}\n\n"
        f"Target Summary Tokens: {int(target_tokens)}\n"
        f"Hard Max Summary Tokens: {int(summary_max_tokens)}"
    )
    return {
        "system_prompt": (
            "You maintain long-running chat memory. Compress transcript history without losing facts that affect "
            "future answers."
        ),
        "user_prompt": user_prompt,
        "message_count": len(messages_to_rollup),
        "target_tokens": int(target_tokens),
        "summary_max_tokens": int(summary_max_tokens),
    }


def _strip_internal_keys(message: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(message)
    item.pop("_resolved_message_id", None)
    return item


def _render_rollup_message(message: Dict[str, Any]) -> str:
    role = message.get("role")
    if role == "user":
        return f"User: {(message.get('content') or '').strip()}"

    if role == "assistant":
        message_type = message.get("message_type", "speaker")
        if message_type == "speaker":
            text = (message.get("response") or message.get("speaker_response") or "").strip()
            return f"Assistant: {text}"
        if message_type == "council":
            stages = message.get("stages") or []
            final_text = ""
            for stage in reversed(stages):
                results = stage.get("results")
                if isinstance(results, dict) and results.get("response"):
                    final_text = str(results.get("response"))
                    break
            return f"Council: {(final_text or '[deliberation]').strip()}"

    return f"Unknown: {str(message)}"
