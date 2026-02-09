import os
import unittest
from contextlib import contextmanager
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend import compaction
from backend import council
from backend import db
from backend import main
from backend import storage


@contextmanager
def isolated_db_path():
    original_path = db.DB_PATH
    original_initialized = db._DB_INITIALIZED
    with TemporaryDirectory() as temp_dir:
        temp_db_path = os.path.join(temp_dir, "council.db")
        db.DB_PATH = temp_db_path
        db._DB_INITIALIZED = False
        try:
            yield temp_db_path
        finally:
            db.DB_PATH = original_path
            db._DB_INITIALIZED = original_initialized


def _legacy_build_chat_history_messages(conversation_messages):
    messages = []
    for msg in conversation_messages:
        role = msg.get("role")
        if role == "user":
            content = (msg.get("content") or "").strip()
            if content:
                messages.append({"role": "user", "content": content})
            continue

        if role != "assistant":
            continue

        message_type = msg.get("message_type", "speaker")
        if message_type == "speaker":
            content = (msg.get("response") or msg.get("speaker_response") or "").strip()
            if content:
                messages.append({"role": "assistant", "content": content})
            continue

        stages = msg.get("stages") or []
        final = council.get_final_response(stages)
        content = (final.get("response") or "").strip()
        if content:
            messages.append({"role": "assistant", "content": content})
    return messages


def _legacy_build_speaker_context(conversation_messages, context_level="full"):
    context_parts = []

    council_response = None
    for msg in conversation_messages:
        if msg.get("role") == "assistant" and msg.get("message_type") == "council":
            council_response = msg
            break

    if not council_response:
        return ""

    if context_level == "minimal":
        final_result = council.get_final_response(council_response.get("stages") or [])
        if final_result.get("response"):
            context_parts.append(f"Council's Initial Analysis:\n{final_result.get('response')}")

    elif context_level == "standard":
        final_result = council.get_final_response(council_response.get("stages") or [])
        if final_result.get("response"):
            context_parts.append(f"Council's Initial Analysis:\n{final_result.get('response')}")

        user_queries = []
        for msg in conversation_messages:
            if msg.get("role") == "user":
                user_queries.append(msg.get("content", ""))
        if user_queries:
            context_parts.append("User Queries:\n" + "\n---\n".join(user_queries))

    elif context_level == "full":
        stages = council_response.get("stages") or []

        for stage in stages:
            stage_name = stage.get("name", "Stage")
            stage_prompt = stage.get("prompt", "")
            results = stage.get("results")

            stage_text = f"=== {stage_name} ==="
            if stage_prompt:
                if len(stage_prompt) > 500:
                    stage_text += f"\nPrompt: {stage_prompt[:500]}..."
                else:
                    stage_text += f"\nPrompt: {stage_prompt}"

            if isinstance(results, list):
                for result in results:
                    if isinstance(result, dict):
                        model = result.get("model", "Unknown")
                        response = result.get("response") or result.get("ranking", "")
                        stage_text += f"\n\n[{model}]:\n{response}"
            elif isinstance(results, dict):
                model = results.get("model", "Unknown")
                response = results.get("response", "")
                stage_text += f"\n\n[{model}]:\n{response}"

            context_parts.append(stage_text)

        conv_history = []
        for msg in conversation_messages:
            role = msg.get("role")
            if role == "user":
                conv_history.append(f"User: {msg.get('content', '')}")
            elif role == "assistant":
                if msg.get("message_type") == "speaker":
                    conv_history.append(f"Speaker: {msg.get('response', '')}")
                else:
                    conv_history.append("Assistant: [Council Analysis - see above]")

        if conv_history:
            context_parts.append("=== Conversation History ===\n" + "\n\n".join(conv_history))

    return "\n\n".join(context_parts)


class CompactionDbFoundationTest(unittest.TestCase):
    def test_db_init_creates_compaction_tables_idempotently(self):
        with isolated_db_path():
            db.init_db()
            db.init_db()
            with db.with_connection() as conn:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
                names = {row["name"] for row in rows}

        self.assertIn("conversation_compaction_state", names)
        self.assertIn("conversation_compaction_events", names)

    def test_storage_compaction_state_crud_and_event_append(self):
        with isolated_db_path():
            db.init_db()
            storage.create_conversation("conv-foundation", mode="chat")

            self.assertIsNone(storage.get_compaction_state("conv-foundation"))

            storage.upsert_compaction_state(
                "conv-foundation",
                summary_text="Running summary",
                summary_token_count=321,
                compacted_until_message_id=12,
            )
            state = storage.get_compaction_state("conv-foundation")
            self.assertIsNotNone(state)
            self.assertEqual(state["summary_text"], "Running summary")
            self.assertEqual(state["summary_token_count"], 321)
            self.assertEqual(state["compacted_until_message_id"], 12)

            storage.append_compaction_event(
                "conv-foundation",
                trigger_reason="test_event",
                before_tokens=2000,
                after_tokens=1500,
            )
            with db.with_connection() as conn:
                event = conn.execute(
                    """
                    SELECT trigger_reason, before_tokens, after_tokens
                    FROM conversation_compaction_events
                    WHERE conversation_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    ("conv-foundation",),
                ).fetchone()

        self.assertEqual(event["trigger_reason"], "test_event")
        self.assertEqual(event["before_tokens"], 2000)
        self.assertEqual(event["after_tokens"], 1500)


class CompactionPrimitiveTest(unittest.TestCase):
    def test_should_compact_is_false_when_disabled(self):
        self.assertFalse(
            compaction.should_compact(
                999_999,
                enabled=False,
                thresholds={"trigger_tokens": 10_000, "target_tokens": 5_000},
            )
        )

    def test_select_messages_for_rollup_preserves_recent_turns(self):
        messages = [
            {"id": 1, "role": "user", "content": "u1"},
            {"id": 2, "role": "assistant", "message_type": "speaker", "response": "a1"},
            {"id": 3, "role": "user", "content": "u2"},
            {"id": 4, "role": "assistant", "message_type": "speaker", "response": "a2"},
            {"id": 5, "role": "user", "content": "u3"},
            {"id": 6, "role": "assistant", "message_type": "speaker", "response": "a3"},
        ]
        selection = compaction.select_messages_for_rollup(
            messages,
            compacted_until_message_id=None,
            recent_turns=2,
        )

        rolled_up_ids = [message["id"] for message in selection["messages_to_rollup"]]
        kept_ids = [message["id"] for message in selection["messages_to_keep"]]
        self.assertEqual(rolled_up_ids, [1, 2])
        self.assertEqual(kept_ids, [3, 4, 5, 6])
        self.assertEqual(selection["next_compacted_until_message_id"], 2)


class ContextParityTest(unittest.TestCase):
    def test_chat_history_assembly_matches_legacy(self):
        conversation_messages = [
            {"role": "user", "content": "Question 1"},
            {
                "role": "assistant",
                "message_type": "council",
                "stages": [
                    {
                        "id": "stage-3",
                        "kind": "synthesis",
                        "name": "Final",
                        "results": {"model": "Chairman", "response": "Council synthesis"},
                    }
                ],
            },
            {"role": "user", "content": "Follow-up"},
            {"role": "assistant", "message_type": "speaker", "response": "Speaker answer"},
        ]

        self.assertEqual(
            council._build_chat_history_messages(conversation_messages),
            _legacy_build_chat_history_messages(conversation_messages),
        )

    def test_speaker_context_assembly_matches_legacy(self):
        conversation_messages = [
            {"role": "user", "content": "Question 1"},
            {
                "role": "assistant",
                "message_type": "council",
                "stages": [
                    {
                        "id": "stage-1",
                        "kind": "responses",
                        "name": "Responses",
                        "prompt": "Analyze deeply",
                        "results": [{"model": "A", "response": "Resp A"}],
                    },
                    {
                        "id": "stage-3",
                        "kind": "synthesis",
                        "name": "Synthesis",
                        "results": {"model": "Chairman", "response": "Council synthesis"},
                    },
                ],
            },
            {"role": "user", "content": "Follow-up"},
            {"role": "assistant", "message_type": "speaker", "response": "Speaker answer"},
        ]

        for level in ("minimal", "standard", "full"):
            with self.subTest(level=level):
                self.assertEqual(
                    council._build_speaker_context(conversation_messages, {}, context_level=level),
                    _legacy_build_speaker_context(conversation_messages, context_level=level),
                )


class CompactionHookDisabledTest(unittest.IsolatedAsyncioTestCase):
    async def test_compaction_hook_returns_early_when_disabled(self):
        with patch.object(main, "AUTO_COMPACTION_ENABLED", False), patch.object(
            main.storage,
            "get_conversation",
        ) as get_conversation:
            await main._maybe_handle_auto_compaction("conv-disabled")

        get_conversation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
