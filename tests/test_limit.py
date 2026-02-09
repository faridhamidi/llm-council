
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from backend import main


class OutputCountTest(unittest.TestCase):
    def test_calculate_council_output_count_empty(self):
        messages = []
        count = main.calculate_council_output_count(messages)
        self.assertEqual(count, 0)
    
    def test_calculate_council_output_count_simple(self):
        # One council message with one stage containing 2 results
        messages = [
            {
                "role": "assistant", 
                "message_type": "council",
                "stages": [
                    {
                        "kind": "responses",
                        "results": [
                            {"model": "A", "response": "foo"},
                            {"model": "B", "response": "bar"}
                        ]
                    }
                ]
            }
        ]
        count = main.calculate_council_output_count(messages)
        self.assertEqual(count, 2)

    def test_calculate_council_output_count_multiple_stages(self):
        # Responses + Synthesis
        messages = [
            {
                "role": "assistant",
                "message_type": "council",
                "stages": [
                    {
                        "kind": "responses",
                        "results": [
                            {"model": "A", "response": "foo"},
                            {"model": "B", "response": "bar"}
                        ]
                    },
                    {
                        "kind": "synthesis",
                        "results": {
                           "model": "Chairman", "response": "sum"
                        }
                    }
                ]
            }
        ]
        count = main.calculate_council_output_count(messages)
        # 2 responses + 1 synthesis = 3 outputs
        self.assertEqual(count, 3)

    def test_calculate_council_output_count_ignores_speaker(self):
        messages = [
            {
                "role": "assistant",
                "message_type": "speaker",  # Should be ignored
                "response": "Hello"
            },
            {
                "role": "assistant", 
                "message_type": "council",
                "stages": [
                    {
                        "kind": "synthesis",
                        "results": {"model": "C", "response": "ok"}
                    }
                ]
            }
        ]
        count = main.calculate_council_output_count(messages)
        self.assertEqual(count, 1)

class RemainingLimitTest(unittest.TestCase):
    def test_logic_calculation(self):
        # Mock values
        MAX_FOLLOW_UP = 20
        N = 5 # 5 council outputs
        # Logic: Limit = 20 + 5 = 25
        
        # User has sent 2 messages. 
        # The first one triggered the council (cost 0 follow-ups).
        # The second one is a follow-up (cost 1 follow-up).
        user_message_count = 2
        used_followups = user_message_count - 1 # 1
        
        remaining = (MAX_FOLLOW_UP + N) - used_followups
        # 20 + 5 - 1 = 24
        self.assertEqual(remaining, 24)


class ChatModeLimitTest(unittest.IsolatedAsyncioTestCase):
    async def test_chat_mode_rejects_101st_message(self):
        conversation = {
            "id": "conv-1",
            "mode": "chat",
            "messages": [{"role": "user", "content": f"u{i}"} for i in range(100)],
        }
        payload = main.SendMessageRequest(content="should fail")
        request = SimpleNamespace(state=SimpleNamespace(session_id="session-1"))

        with patch.object(main.storage, "get_conversation", return_value=conversation):
            with self.assertRaises(HTTPException) as exc_ctx:
                await main.send_message("conv-1", payload, request)

        self.assertEqual(exc_ctx.exception.status_code, 400)
        self.assertIn("Maximum 100 messages", str(exc_ctx.exception.detail))

    async def test_chat_mode_allows_100th_message(self):
        base_messages = [{"role": "user", "content": f"u{i}"} for i in range(99)]
        conversation_before = {
            "id": "conv-1",
            "mode": "chat",
            "messages": base_messages,
            "settings_snapshot": {"members": [], "chairman_id": None},
        }
        conversation_after_user = {
            "id": "conv-1",
            "mode": "chat",
            "messages": base_messages + [{"role": "user", "content": "new"}],
            "settings_snapshot": {"members": [], "chairman_id": None},
        }
        conversation_after_assistant = {
            "id": "conv-1",
            "mode": "chat",
            "messages": base_messages + [
                {"role": "user", "content": "new"},
                {"role": "assistant", "message_type": "speaker", "response": "ok"},
            ],
            "settings_snapshot": {"members": [], "chairman_id": None},
            "total_tokens": 123,
        }

        payload = main.SendMessageRequest(content="new")
        request = SimpleNamespace(state=SimpleNamespace(session_id="session-1"))

        with patch.object(
            main.storage,
            "get_conversation",
            side_effect=[conversation_before, conversation_after_user, conversation_after_assistant],
        ), patch.object(main.storage, "add_user_message"), patch.object(main.storage, "add_speaker_message"), patch.object(
            main,
            "query_normal_chat",
            return_value={"model": "Assistant", "response": "ok", "token_count": 3, "error": False},
        ), patch.object(main, "_maybe_handle_auto_compaction", return_value=None):
            result = await main.send_message("conv-1", payload, request)

        self.assertEqual(result["max_messages"], 100)
        self.assertEqual(result["mode"], "chat")

    async def test_chat_mode_info_reports_100_max_messages(self):
        conversation = {
            "id": "conv-1",
            "title": "Chat",
            "mode": "chat",
            "messages": [{"role": "user", "content": "hello"}],
            "settings_snapshot": {},
            "total_tokens": 10,
        }

        with patch.object(main.storage, "get_conversation", return_value=conversation):
            info = await main.get_conversation_info("conv-1")

        self.assertEqual(info["max_messages"], 100)

if __name__ == "__main__":
    unittest.main()
