import sys
import unittest
from pathlib import Path

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mainfiles"))

from backend.schemas import ChatStreamRequest


class ChatStreamRequestTests(unittest.TestCase):
    def test_accepts_a_user_message_as_the_final_turn(self):
        request = ChatStreamRequest(
            model="openai::gpt-4o",
            messages=[{"role": "user", "content": "Hello"}],
        )

        self.assertEqual(request.messages[-1].role, "user")
        self.assertEqual(request.file_ids, [])

    def test_rejects_a_request_without_a_final_user_turn(self):
        with self.assertRaises(ValidationError):
            ChatStreamRequest(messages=[{"role": "assistant", "content": "Hello"}])


if __name__ == "__main__":
    unittest.main()
