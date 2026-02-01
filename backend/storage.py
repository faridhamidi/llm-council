"""SQLite-based storage for conversations."""

from __future__ import annotations

import json
from datetime import datetime
from typing import List, Dict, Any, Optional

from .db import with_connection


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def create_conversation(conversation_id: str) -> Dict[str, Any]:
    """
    Create a new conversation.

    Args:
        conversation_id: Unique identifier for the conversation

    Returns:
        New conversation dict
    """
    created_at = _now_iso()
    conversation = {
        "id": conversation_id,
        "created_at": created_at,
        "title": "New Conversation",
        "messages": [],
    }

    with with_connection() as conn:
        conn.execute(
            "INSERT INTO conversations (id, created_at, title, deleted_at) VALUES (?, ?, ?, NULL)",
            (conversation_id, created_at, conversation["title"]),
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
            "SELECT id, created_at, title FROM conversations WHERE id = ? AND deleted_at IS NULL",
            (conversation_id,),
        ).fetchone()
        if row is None:
            return None

        messages_rows = conn.execute(
            """
            SELECT role, content, stage1_json, stage2_json, stage3_json, stages_json, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
            """,
            (conversation_id,),
        ).fetchall()

    messages: List[Dict[str, Any]] = []
    for msg in messages_rows:
        if msg["role"] == "user":
            messages.append({"role": "user", "content": msg["content"]})
        else:
            stage1 = json.loads(msg["stage1_json"]) if msg["stage1_json"] else None
            stage2 = json.loads(msg["stage2_json"]) if msg["stage2_json"] else None
            stage3 = json.loads(msg["stage3_json"]) if msg["stage3_json"] else None
            stages = json.loads(msg["stages_json"]) if msg["stages_json"] else None
            messages.append({
                "role": "assistant",
                "stage1": stage1,
                "stage2": stage2,
                "stage3": stage3,
                "stages": stages,
            })

    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "title": row["title"],
        "messages": messages,
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
            "message_count": row["message_count"],
        }
        for row in rows
    ]


def add_user_message(conversation_id: str, content: str) -> None:
    """
    Add a user message to a conversation.

    Args:
        conversation_id: Conversation identifier
        content: User message content
    """
    with with_connection() as conn:
        conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, created_at)
            VALUES (?, 'user', ?, ?)
            """,
            (conversation_id, content, _now_iso()),
        )
        conn.commit()


def add_assistant_message(
    conversation_id: str,
    stage1: List[Dict[str, Any]],
    stage2: List[Dict[str, Any]],
    stage3: Dict[str, Any],
    stages: List[Dict[str, Any]] | None = None,
) -> None:
    """
    Add an assistant message with all 3 stages to a conversation.

    Args:
        conversation_id: Conversation identifier
        stage1: List of individual model responses
        stage2: List of model rankings
        stage3: Final synthesized response
        stages: Full stage outputs
    """
    with with_connection() as conn:
        conn.execute(
            """
            INSERT INTO messages (conversation_id, role, stage1_json, stage2_json, stage3_json, stages_json, created_at)
            VALUES (?, 'assistant', ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                json.dumps(stage1),
                json.dumps(stage2),
                json.dumps(stage3),
                json.dumps(stages) if stages is not None else None,
                _now_iso(),
            ),
        )
        conn.commit()


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
