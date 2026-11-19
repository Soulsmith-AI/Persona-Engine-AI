import filecmp
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIN = os.path.join(ROOT, "windows")


def files_under(base, sub):
    out = []
    for dirpath, dirs, files in os.walk(os.path.join(base, sub)):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if not f.endswith(".pyc"):
                out.append(os.path.relpath(os.path.join(dirpath, f), base))
    return sorted(out)


class TestWindowsVariant(unittest.TestCase):
    """windows/ must be an exact copy of the main plugin apart from hooks and manifest."""

    def test_code_is_in_sync(self):
        for sub in ("persona_engine", "scripts", "skills"):
            main_files = files_under(ROOT, sub)
            self.assertEqual(main_files, files_under(WIN, sub), f"{sub} 文件列表不同，请运行 tools/sync_windows.py")
            for rel in main_files:
                self.assertTrue(filecmp.cmp(os.path.join(ROOT, rel), os.path.join(WIN, rel), shallow=False),
                                f"{rel} 内容不同，请运行 tools/sync_windows.py")

    def test_hook_commands(self):
        main = json.load(open(os.path.join(ROOT, "hooks", "hooks.json"), encoding="utf-8"))
        win = json.load(open(os.path.join(WIN, "hooks", "hooks.json"), encoding="utf-8"))
        for ev in ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"):
            m = main["hooks"][ev][0]["hooks"][0]
            w = win["hooks"][ev][0]["hooks"][0]
            self.assertEqual(m["command"], "python3")
            self.assertEqual(w["command"], "python")
            self.assertIn("args", m)  # exec form: no shell, works without Git Bash
            self.assertEqual(m["args"], w["args"])

    def test_versions_match(self):
        a = json.load(open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8"))
        b = json.load(open(os.path.join(WIN, ".claude-plugin", "plugin.json"), encoding="utf-8"))
        self.assertEqual(a["version"], b["version"])
        self.assertEqual(b["name"], "persona-engine-windows")


if __name__ == "__main__":
    unittest.main()
