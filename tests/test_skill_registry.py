import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mainfiles"))

from backend.skills.registry import SkillRegistry


class SkillRegistryTests(unittest.TestCase):
    def test_loads_the_tracked_skill_catalog(self):
        registry = SkillRegistry()

        self.assertEqual(
            {"api-design", "coding-standards", "debugging", "web-search"},
            set(registry.skills),
        )

    def test_rejects_missing_required_parameters(self):
        registry = SkillRegistry()

        with self.assertRaisesRegex(ValueError, "spec_type"):
            registry.build_prompt("api-design")


if __name__ == "__main__":
    unittest.main()
