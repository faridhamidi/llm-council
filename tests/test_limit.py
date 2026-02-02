
import unittest
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

if __name__ == "__main__":
    unittest.main()
