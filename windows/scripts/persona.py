#!/usr/bin/env python3
"""Persona Engine command line.

Used by Claude Code hooks (`persona.py hook <event>`), the status line (`persona.py statusline`)
and the /persona skill (`persona.py show`, `me`, `card`, ...). Standard library only.
"""

import argparse
import contextlib
import json
import os
import shutil
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from persona_engine import card as K  # noqa: E402
from persona_engine import core as C  # noqa: E402
from persona_engine import data as D  # noqa: E402

try:  # stdout must be UTF-8 for Chinese text (Windows consoles default to other code pages)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def state_lock():
    path = os.path.join(C.home_dir(), ".lock")
    f = open(path, "a+")
    try:
        try:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)
        except ImportError:
            pass
        yield
    finally:
        try:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_UN)
        except ImportError:
            pass
        f.close()


def log_error():
    try:
        with open(os.path.join(C.home_dir(), "error.log"), "a", encoding="utf-8") as f:
            f.write(traceback.format_exc() + "\n")
    except Exception:
        pass


def read_stdin_json():
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    except AttributeError:
        raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def emit_context(event_name, text):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": text}},
                     ensure_ascii=False))


def sync_app():
    """Copy the engine to ~/.persona-engine/app so the status line has a stable path."""
    app = os.path.join(C.home_dir(), "app")
    marker = os.path.join(app, "VERSION")
    try:
        if os.path.exists(marker) and open(marker, encoding="utf-8").read().strip() == C.VERSION:
            return
    except Exception:
        pass
    os.makedirs(os.path.join(app, "persona_engine"), exist_ok=True)
    os.makedirs(os.path.join(app, "scripts"), exist_ok=True)
    for name in os.listdir(os.path.join(ROOT, "persona_engine")):
        if name.endswith(".py"):
            shutil.copy2(os.path.join(ROOT, "persona_engine", name), os.path.join(app, "persona_engine", name))
    shutil.copy2(os.path.join(HERE, "persona.py"), os.path.join(app, "scripts", "persona.py"))
    with open(marker, "w", encoding="utf-8") as f:
        f.write(C.VERSION)


# ---------------------------------------------------------------------------
# hook handlers
# ---------------------------------------------------------------------------
def run_hook(event):
    payload = read_stdin_json()
    sid = payload.get("session_id") or "unknown"
    try:
        with state_lock():
            state = C.get_or_create_state()
            if not state.get("enabled", True):
                return
            if event == "session-start":
                text = C.on_session_start(state, sid)
                C.save_state(state)
                try:
                    sync_app()
                except Exception:
                    log_error()
                emit_context("SessionStart", text)
            elif event == "user-prompt":
                text = C.on_user_prompt(state, sid, payload.get("prompt", ""))
                C.save_state(state)
                emit_context("UserPromptSubmit", text)
            elif event == "stop":
                C.on_stop(state, sid, payload.get("last_assistant_message", ""))
                C.save_state(state)  # no output: output from a Stop hook would keep Claude talking
            elif event == "session-end":
                C.on_session_end(state, sid)
                C.save_state(state)
    except Exception:
        log_error()  # never break the user's Claude Code session


# ---------------------------------------------------------------------------
# status line installation
# ---------------------------------------------------------------------------
def settings_path():
    return os.path.join(os.path.expanduser("~"), ".claude", "settings.json")


def statusline_command():
    script = os.path.join(C.home_dir(), "app", "scripts", "persona.py")
    py = sys.executable or "python3"
    return f'"{py}" "{script}" statusline'


def install_statusline(force=False):
    sync_app()
    p = settings_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    settings = {}
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            raw = f.read()
        if raw.strip():
            try:
                settings = json.loads(raw)
            except json.JSONDecodeError:
                print(f"无法解析 {p}，为安全起见没有修改。请手动加入：")
                print(json.dumps({"statusLine": {"type": "command", "command": statusline_command()}},
                                 ensure_ascii=False, indent=2))
                return 1
    existing = settings.get("statusLine")
    if existing and "persona.py" not in json.dumps(existing) and not force:
        print("你已经有自己的状态栏配置，为避免覆盖，没有修改。")
        print("如果确定要替换，运行：persona.py install-statusline --force（会先备份原文件）")
        return 1
    # Back up only once, right before the first real write, so the
    # pre-install original is never overwritten by later reinstalls.
    backup = p + ".persona-backup"
    if os.path.exists(p) and not os.path.exists(backup):
        shutil.copy2(p, backup)
    settings["statusLine"] = {"type": "command", "command": statusline_command()}
    with open(p, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    if os.path.exists(backup):
        note = f"安装前的原文件备份在 {backup}"
    else:
        note = "安装前没有 settings.json，无需备份"
    print(f"已安装状态栏（{p}，{note}）。重启 Claude Code 后生效。")
    return 0


def uninstall_statusline():
    p = settings_path()
    if not os.path.exists(p):
        print("没有找到 settings.json。")
        return 0
    with open(p, encoding="utf-8") as f:
        settings = json.load(f)
    if "persona.py" in json.dumps(settings.get("statusLine", "")):
        settings.pop("statusLine", None)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        print("已移除人格引擎的状态栏。")
    else:
        print("当前状态栏不是人格引擎的，没有修改。")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(prog="persona.py", description="Persona Engine")
    sub = ap.add_subparsers(dest="cmd")
    h = sub.add_parser("hook")
    h.add_argument("event", choices=["session-start", "user-prompt", "stop", "session-end"])
    sub.add_parser("show")
    sub.add_parser("me")
    lg = sub.add_parser("log")
    lg.add_argument("n", nargs="?", type=int, default=20)
    cd = sub.add_parser("card")
    cd.add_argument("--out", default=None)
    sub.add_parser("statusline")
    il = sub.add_parser("install-statusline")
    il.add_argument("--force", action="store_true")
    sub.add_parser("uninstall-statusline")
    co = sub.add_parser("correct")
    co.add_argument("dim")
    co.add_argument("value", type=float)
    ev = sub.add_parser("event")
    ev.add_argument("name", choices=sorted(D.EXPERIENCE_RULES))
    ev.add_argument("--reason", default=None)
    sub.add_parser("events")
    sub.add_parser("reflect")
    rb = sub.add_parser("rebirth")
    rb.add_argument("--birthday", default=None)
    rb.add_argument("--yes", action="store_true")
    dl = sub.add_parser("delete")
    dl.add_argument("--yes", action="store_true")
    sub.add_parser("on")
    sub.add_parser("off")
    sub.add_parser("export")
    args = ap.parse_args(argv)

    if args.cmd == "hook":
        run_hook(args.event)
        return 0

    if args.cmd == "statusline":
        read_stdin_json()
        try:
            st = C.load_state()
            print(C.status_line(st) if st else "🌱 人格引擎：等待诞生")
        except Exception:
            print("人格引擎")
        return 0

    if args.cmd == "install-statusline":
        return install_statusline(args.force)
    if args.cmd == "uninstall-statusline":
        return uninstall_statusline()

    if args.cmd == "delete":
        if not args.yes:
            print("这会删除人格、成长日志和对你的推测，且无法恢复。确认请加 --yes")
            return 1
        p = C.state_path()
        if os.path.exists(p):
            os.remove(p)
        print("已删除全部人格数据。下次会话会重新诞生。")
        return 0

    with state_lock():
        st = C.get_or_create_state()
        if args.cmd in (None, "show"):
            print(C.render_profile(st))
        elif args.cmd == "me":
            print(C.render_user(st))
        elif args.cmd == "log":
            logs = st["growth_log"][-args.n:]
            if not logs:
                print("还没有成长记录。")
            for g in logs:
                ch = " ".join(f"{d}{v:+.1f}" for d, v in g["change"].items()) or "无数值变化"
                print(f"第 {g['day']} 天（{g['date']}）[{ch}] {g['mbti']}：" + "；".join(g["reasons"]))
        elif args.cmd == "card":
            out = args.out or os.path.join(C.home_dir(), "persona-card.svg")
            with open(out, "w", encoding="utf-8") as f:
                f.write(K.render_card(st))
            print(f"人格卡片已生成：{out}")
        elif args.cmd == "correct":
            C.correct_user(st, args.dim, args.value)
            C.save_state(st)
            print(f"已更新：你的{D.DIM_NAMES[args.dim.upper()]}设为 {args.value:.0f}（置信度 0.9）。")
        elif args.cmd == "event":
            C.apply_manual_event(st, args.name, args.reason)
            C.save_state(st)
            print(f"已记录经历：{D.EXPERIENCE_NAMES[args.name]}。会在会话结束时的反思中生效。")
        elif args.cmd == "events":
            for k, (rule, reason) in D.EXPERIENCE_RULES.items():
                ch = " ".join(f"{d}{v:+.1f}" for d, v in rule.items())
                print(f"{k:22} {D.EXPERIENCE_NAMES[k]}（{ch}）")
        elif args.cmd == "reflect":
            entry = C.reflect(st)
            C.save_state(st)
            if entry:
                ch = " ".join(f"{d}{v:+.1f}" for d, v in entry["change"].items()) or "无数值变化"
                print(f"反思完成 [{ch}]：" + "；".join(entry["reasons"]))
            else:
                print("这段时间没有足以改变人格的经历。")
        elif args.cmd == "rebirth":
            if not args.yes:
                print("重新诞生会清空当前人格和成长日志。确认请加 --yes")
                return 1
            new = C.new_state(birthday=args.birthday)
            new["user_profile"] = st["user_profile"]  # keep what it learned about the user
            C.save_state(new)
            print(f"已重新诞生：{new['birth']['symbol']} {new['birth']['zodiac']}座 · {new['mbti']['type']}")
        elif args.cmd in ("on", "off"):
            st["enabled"] = args.cmd == "on"
            C.save_state(st)
            print("人格引擎已开启。" if st["enabled"] else "人格引擎已暂停（数据保留）。")
        elif args.cmd == "export":
            print(json.dumps(st, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
