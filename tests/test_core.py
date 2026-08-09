import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import build_messages, file_sha256


class CoreTests(unittest.TestCase):
    def test_explain_prompt(self):
        messages = build_messages("explain", "Transformer")
        self.assertIn("解释", messages[1]["content"])
        self.assertIn("Transformer", messages[1]["content"])

    def test_translate_direction(self):
        zh = build_messages("translate", "知识树")[1]["content"]
        en = build_messages("translate", "knowledge tree")[1]["content"]
        self.assertIn("英文", zh)
        self.assertIn("简体中文", en)

    def test_sha256(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "sample.bin"
            target.write_bytes(b"huacitong")
            self.assertEqual(file_sha256(target), hashlib.sha256(b"huacitong").hexdigest())


if __name__ == "__main__":
    unittest.main()
