import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mainfiles"))

from mainfiles.backend.api import sse_event


class StreamingTests(unittest.TestCase):
    def test_sse_event_preserves_multiline_provider_output(self):
        event = sse_event("first line\nsecond line", event="message")

        self.assertEqual(event, "event: message\ndata: first line\ndata: second line\n\n")


if __name__ == "__main__":
    unittest.main()
