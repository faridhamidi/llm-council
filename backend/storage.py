"""SQLite-based storage for conversations."""

from __future__ import annotations

import json
from datetime import datetime
from typing import List, Dict, Any, Optional

from .db import with_connection


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def create_conversation(
    conversation_id: str,
    settings_snapshot: Dict[str, Any] | None = None,
    mode: str = "council",
) -> Dict[str, Any]:
    """
    Create a new conversation with optional settings snapshot.

    Args:
        conversation_id: Unique identifier for the conversation
        settings_snapshot: Optional council settings to lock for this conversation

    Returns:
        New conversation dict
    """
    created_at = _now_iso()
    conversation = {
        "id": conversation_id,
        "created_at": created_at,
        "title": "New Chat" if mode == "chat" else "New Conversation",
        "messages": [],
        "settings_snapshot": settings_snapshot,
        "mode": mode,
    }

    with with_connection() as conn:
        conn.execute(
            "INSERT INTO conversations (id, created_at, title, deleted_at, settings_snapshot, mode) VALUES (?, ?, ?, NULL, ?, ?)",
            (
                conversation_id,
                created_at,
                conversation["title"],
                json.dumps(settings_snapshot) if settings_snapshot else None,
                mode,
            ),
        )
        conn.commit()

    return conversation


def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    """
    Load a conversation from storage.

    Args:
        conversation_id: Unique identifier for the conversation

    Returns:
        Conversation dict or None if not found
    """
    with with_connection() as conn:
        row = conn.execute(
            "SELECT id, created_at, title, settings_snapshot, mode FROM conversations WHERE id = ? AND deleted_at IS NULL",
            (conversation_id,),
        ).fetchone()
        if row is None:
            return None

        messages_rows = conn.execute(
            """
            SELECT id, role, content, stage1_json, stage2_json, stage3_json, stages_json,
                   message_type, token_count, speaker_response, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
            """,
            (conversation_id,),
        ).fetchall()

    messages: List[Dict[str, Any]] = []
    total_tokens = 0
    for msg in messages_rows:
        token_count = msg["token_count"] or 0
        total_tokens += token_count
        if msg["role"] == "user":
            messages.append({
                "id": msg["id"],
                "role": "user",
                "content": msg["content"],
                "token_count": token_count,
            })
        else:
            message_type = msg["message_type"] or "council"
            if message_type == "speaker":
                # Speaker response (follow-up)
                messages.append({
                    "id": msg["id"],
                    "role": "assistant",
                    "message_type": "speaker",
                    "response": msg["speaker_response"],
                    "token_count": token_count,
                })
            else:
                # Council response (full stages)
                stages = json.loads(msg["stages_json"]) if msg["stages_json"] else None
                if not stages:
                    # Legacy fallback: build stages from stage1/2/3 columns
                    stage1 = json.loads(msg["stage1_json"]) if msg["stage1_json"] else None
                    stage2 = json.loads(msg["stage2_json"]) if msg["stage2_json"] else None
                    stage3 = json.loads(msg["stage3_json"]) if msg["stage3_json"] else None
                    stages = []
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
                messages.append({
                    "id": msg["id"],
                    "role": "assistant",
                    "message_type": "council",
                    "stages": stages,
                    "token_count": token_count,
                })

    settings_snapshot = json.loads(row["settings_snapshot"]) if row["settings_snapshot"] else None
    
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "title": row["title"],
        "messages": messages,
        "settings_snapshot": settings_snapshot,
        "mode": row["mode"] or "council",
        "total_tokens": total_tokens,
    }


def list_conversations() -> List[Dict[str, Any]]:
    """
    List all conversations (metadata only).

    Returns:
        List of conversation metadata dicts
    """
    with with_connection() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.created_at, c.title,
              c.mode,
              (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count
            FROM conversations c
            WHERE c.deleted_at IS NULL
            ORDER BY c.created_at DESC
            """
        ).fetchall()

    return [
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "title": row["title"],
            "mode": row["mode"] or "council",
            "message_count": row["message_count"],
        }
        for row in rows
    ]


def add_user_message(conversation_id: str, content: str, token_count: int = 0) -> None:
    """
    Add a user message to a conversation.

    Args:
        conversation_id: Conversation identifier
        content: User message content
        token_count: Estimated token count for this message
    """
    with with_connection() as conn:
        conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, token_count, created_at)
            VALUES (?, 'user', ?, ?, ?)
            """,
            (conversation_id, content, token_count, _now_iso()),
        )
        conn.commit()


def add_assistant_message(
    conversation_id: str,
    stages: List[Dict[str, Any]],
    token_count: int = 0,
) -> None:
    """
    Add an assistant message with the full stage outputs to a conversation.

    Args:
        conversation_id: Conversation identifier
        stages: Full stage outputs
        token_count: Estimated token count for this message
    """
    with with_connection() as conn:
        conn.execute(
            """
            INSERT INTO messages (conversation_id, role, message_type, stages_json, token_count, created_at)
            VALUES (?, 'assistant', 'council', ?, ?, ?)
            """,
            (
                conversation_id,
                json.dumps(stages) if stages is not None else None,
                token_count,
                _now_iso(),
            ),
        )
        conn.commit()


def add_speaker_message(
    conversation_id: str,
    response: str,
    token_count: int = 0,
) -> None:
    """
    Add a speaker follow-up response to a conversation.

    Args:
        conversation_id: Conversation identifier
        response: Speaker response text
        token_count: Estimated token count for this message
    """
    with with_connection() as conn:
        conn.execute(
            """
            INSERT INTO messages (conversation_id, role, message_type, speaker_response, token_count, created_at)
            VALUES (?, 'assistant', 'speaker', ?, ?, ?)
            """,
            (
                conversation_id,
                response,
                token_count,
                _now_iso(),
            ),
        )
        conn.commit()


def get_compaction_state(conversation_id: str) -> Optional[Dict[str, Any]]:
    """Fetch compaction summary state for a conversation."""
    with with_connection() as conn:
        row = conn.execute(
            """
            SELECT conversation_id, summary_text, summary_token_count, compacted_until_message_id, updated_at
            FROM conversation_compaction_state
            WHERE conversation_id = ?
            """,
            (conversation_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "conversation_id": row["conversation_id"],
        "summary_text": row["summary_text"] or "",
        "summary_token_count": row["summary_token_count"] or 0,
        "compacted_until_message_id": row["compacted_until_message_id"],
        "updated_at": row["updated_at"],
    }


def upsert_compaction_state(
    conversation_id: str,
    summary_text: str,
    summary_token_count: int,
    compacted_until_message_id: int | None,
) -> None:
    """Create or update compaction summary state for a conversation."""
    with with_connection() as conn:
        conn.execute(
            """
            INSERT INTO conversation_compaction_state (
                conversation_id,
                summary_text,
                summary_token_count,
                compacted_until_message_id,
                updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                summary_text = excluded.summary_text,
                summary_token_count = excluded.summary_token_count,
                compacted_until_message_id = excluded.compacted_until_message_id,
                updated_at = excluded.updated_at
            """,
            (
                conversation_id,
                summary_text,
                summary_token_count,
                compacted_until_message_id,
                _now_iso(),
            ),
        )
        conn.commit()


def append_compaction_event(
    conversation_id: str,
    trigger_reason: str,
    before_tokens: int | None = None,
    after_tokens: int | None = None,
) -> None:
    """Append an audit event for compaction decision/execution."""
    with with_connection() as conn:
        conn.execute(
            """
            INSERT INTO conversation_compaction_events (
                conversation_id,
                trigger_reason,
                before_tokens,
                after_tokens,
                created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                trigger_reason,
                before_tokens,
                after_tokens,
                _now_iso(),
            ),
        )
        conn.commit()


def save_settings_snapshot(conversation_id: str, settings: Dict[str, Any]) -> None:
    """
    Save settings snapshot for an existing conversation.

    Args:
        conversation_id: Conversation identifier
        settings: Council settings to snapshot
    """
    with with_connection() as conn:
        conn.execute(
            "UPDATE conversations SET settings_snapshot = ? WHERE id = ?",
            (json.dumps(settings), conversation_id),
        )
        conn.commit()


def delete_last_assistant_message(conversation_id: str) -> bool:
    """
    Delete the last assistant message for retry functionality.

    Args:
        conversation_id: Conversation identifier

    Returns:
        True if deleted, False if no message found
    """
    with with_connection() as conn:
        # Find and delete the last assistant message
        cursor = conn.execute(
            """
            DELETE FROM messages WHERE id = (
                SELECT id FROM messages
                WHERE conversation_id = ? AND role = 'assistant'
                ORDER BY id DESC LIMIT 1
            )
            """,
            (conversation_id,),
        )
        conn.commit()
        return cursor.rowcount > 0


def update_conversation_title(conversation_id: str, title: str) -> None:
    """
    Update the title of a conversation.

    Args:
        conversation_id: Conversation identifier
        title: New title for the conversation
    """
    with with_connection() as conn:
        conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ?",
            (title, conversation_id),
        )
        conn.commit()


def delete_conversation(conversation_id: str) -> bool:
    """
    Soft-delete a conversation by marking deleted_at.

    Args:
        conversation_id: Conversation identifier

    Returns:
        True if deleted, False if not found
    """
    with with_connection() as conn:
        cursor = conn.execute(
            "UPDATE conversations SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
            (_now_iso(), conversation_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def restore_conversation(conversation_id: str) -> bool:
    """
    Restore a deleted conversation.

    Args:
        conversation_id: Conversation identifier

    Returns:
        True if restored, False if not found
    """
    with with_connection() as conn:
        cursor = conn.execute(
            "UPDATE conversations SET deleted_at = NULL WHERE id = ? AND deleted_at IS NOT NULL",
            (conversation_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
