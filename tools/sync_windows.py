#!/usr/bin/env python3
"""Build the Windows variant of the plugin in ./windows from the main plugin.

Why two variants: Claude Code hooks run in "exec form" (no shell) so they work on Windows
without Git Bash, and exec form needs one fixed program name. On macOS/Linux that is `python3`;
on Windows (python.org installer) it is `python`. The code is identical; only hooks.json and the
plugin name differ. Run this after every change, before committing:

    python3 tools/sync_windows.py
"""
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIN = os.path.join(ROOT, "windows")
SYNCED_DIRS = ["persona_engine", "scripts", "skills"]
SYNCED_FILES = ["LICENSE"]


def hooks_for(python_cmd):
    events = [("SessionStart", "session-start", 15), ("UserPromptSubmit", "user-prompt", 15),
              ("Stop", "stop", 15), ("SessionEnd", "session-end", 10)]
    return {
        "description": "Persona Engine: load the persona at session start, update emotions every turn, "
                       "reflect at session end. Exec form (no shell).",
        "hooks": {ev: [{"hooks": [{"type": "command", "command": python_cmd,
                                   "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/persona.py", "hook", arg],
                                   "timeout": t}]}] for ev, arg, t in events},
    }


def main():
    main_manifest = json.load(open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8"))
    if os.path.exists(WIN):
        shutil.rmtree(WIN)
    for d in SYNCED_DIRS:
        shutil.copytree(os.path.join(ROOT, d), os.path.join(WIN, d),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for f in SYNCED_FILES:
        shutil.copy2(os.path.join(ROOT, f), os.path.join(WIN, f))
    os.makedirs(os.path.join(WIN, ".claude-plugin"))
    os.makedirs(os.path.join(WIN, "hooks"))
    manifest = dict(main_manifest)
    manifest["name"] = "persona-engine-windows"
    manifest["displayName"] = main_manifest.get("displayName", "Persona Engine") + "（Windows）"
    manifest["description"] = main_manifest["description"] + " Windows 版：钩子调用 python。"
    if "icon" in main_manifest:
        shutil.copy2(os.path.join(ROOT, ".claude-plugin", "icon.png"), os.path.join(WIN, ".claude-plugin", "icon.png"))
    json.dump(manifest, open(os.path.join(WIN, ".claude-plugin", "plugin.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(hooks_for("python"), open(os.path.join(WIN, "hooks", "hooks.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(hooks_for("python3"), open(os.path.join(ROOT, "hooks", "hooks.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    with open(os.path.join(WIN, "README.md"), "w", encoding="utf-8") as f:
        f.write("# Persona Engine（Windows 版）\n\n这个文件夹由 `tools/sync_windows.py` 自动生成，请不要直接修改。"
                "代码与主插件完全相同，只是钩子调用 `python` 而不是 `python3`。说明见仓库根目录的 README。\n")
    print("windows/ 已同步，版本", manifest["version"])


if __name__ == "__main__":
    main()
