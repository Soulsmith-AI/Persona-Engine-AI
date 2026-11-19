"""Persona engine core: state, birth, Big Five -> MBTI, emotions, scenes, user profile,
per-turn context, reflection and growth log.

Everything is local. Standard library only (Python 3.8+).
"""

import datetime as _dt
import json
import os
import random
import tempfile
import time

from . import data as D

VERSION = "0.1.2"
STATE_VERSION = 2

TRAIT_MIN, TRAIT_MAX = 15.0, 85.0
MAX_SESSION_CHANGE = 3.0
EMO_DECAY_PER_TURN = 0.13          # ~half-life of 5 turns
EMO_MAX_STEP = 0.30                # inertia: max change per emotion per turn
EMO_HALF_LIFE_HOURS = 6.0          # between sessions
USER_CONF_MIN = 0.4                # below this, the user profile is not used for mixing


# ---------------------------------------------------------------------------
# Paths and persistence
# ---------------------------------------------------------------------------
def home_dir():
    path = os.environ.get("PERSONA_HOME") or os.path.join(os.path.expanduser("~"), ".persona-engine")
    os.makedirs(path, exist_ok=True)
    return path


def state_path():
    return os.path.join(home_dir(), "state.json")


def load_state():
    p = state_path()
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    p = state_path()
    d = os.path.dirname(p)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".state-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    for attempt in range(20):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:  # Windows: file briefly open in another process (e.g. status line)
            time.sleep(0.05)
    os.replace(tmp, p)


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _today():
    return _dt.date.today()


def _now():
    return time.time()


# ---------------------------------------------------------------------------
# Birth
# ---------------------------------------------------------------------------
def new_state(birthday=None, seed=None):
    """Create a newborn persona. birthday: 'YYYY-MM-DD' or None (= today)."""
    rng = random.Random(seed)
    bday = _dt.date.fromisoformat(birthday) if birthday else _today()
    z = D.zodiac_for(bday.month, bday.day)
    name, symbol, _start, offsets, sens, image = z
    b5 = {}
    for d in D.DIMS:
        b5[d] = round(_clamp(50 + offsets.get(d, 0) + rng.uniform(-5, 5), TRAIT_MIN, TRAIT_MAX), 1)
    state = {
        "version": STATE_VERSION,
        "engine_version": VERSION,
        "enabled": True,
        "birth": {
            "date": bday.isoformat(),
            "zodiac": name,
            "symbol": symbol,
            "image": image,
            "announced": False,
            "initial_big_five": dict(b5),
        },
        "big_five": b5,
        "user_profile": {d: {"value": 50.0, "confidence": 0.0} for d in D.DIMS},
        "emotions": {},
        "growth_log": [],
        "session": None,
        "stats": {"sessions": 0, "turns": 0},
        "last_seen": _now(),
    }
    state["emotions"] = baseline_emotions(state)
    state["mbti"] = mbti_of(b5)
    return state


def get_or_create_state():
    st = load_state()
    if st is None:
        st = new_state()
        save_state(st)
    return st


def day_number(state):
    born = _dt.date.fromisoformat(state["birth"]["date"])
    return max(1, (_today() - born).days + 1)


# ---------------------------------------------------------------------------
# MBTI from Big Five
# ---------------------------------------------------------------------------
def mbti_of(b5):
    letters = [
        ("E" if b5["E"] >= 50 else "I", abs(b5["E"] - 50) / 50),
        ("N" if b5["O"] >= 50 else "S", abs(b5["O"] - 50) / 50),
        ("F" if b5["A"] >= 50 else "T", abs(b5["A"] - 50) / 50),
        ("J" if b5["C"] >= 50 else "P", abs(b5["C"] - 50) / 50),
    ]
    t = "".join(l for l, _ in letters)
    return {
        "type": t,
        "strength": {l: round(s, 2) for l, s in letters},
        "stack": D.MBTI_STACKS[t],
    }


def mbti_label(mbti):
    """'ENTP' or with soft letters marked, e.g. 'E(弱)NTP' style compact: lowercase = weak."""
    out = []
    for ch in mbti["type"]:
        out.append(ch.lower() if mbti["strength"].get(ch, 1) < 0.08 else ch)
    return "".join(out)


# ---------------------------------------------------------------------------
# Emotions
# ---------------------------------------------------------------------------
def _norm(v):
    return (v - 50.0) / 50.0  # -0.7 .. 0.7 within trait bounds


def baseline_emotions(state):
    b = state["big_five"]
    o, c, e, a, n = (_norm(b[d]) for d in D.DIMS)
    base = {
        "好奇": 0.25 + 0.20 * o,
        "兴奋": 0.15 + 0.15 * e,
        "担忧": 0.10 + 0.15 * n + 0.05 * c,
        "不认同": 0.05 - 0.08 * a,
        "满足": 0.15 + 0.05 * a,
        "疲惫": 0.05,
    }
    return {k: round(_clamp(v, 0.0, 0.6), 3) for k, v in base.items()}


def _sensitivity(state, emo):
    b = state["big_five"]
    o, c, e, a, n = (_norm(b[d]) for d in D.DIMS)
    trait = {
        "好奇": 1 + 0.5 * o,
        "兴奋": 1 + 0.5 * e,
        "担忧": 1 + 0.5 * n + 0.2 * c,
        "不认同": 1 - 0.5 * a,
        "满足": 1 + 0.3 * a,
        "疲惫": 1 + 0.3 * n,
    }[emo]
    z = D.zodiac_by_name(state["birth"]["zodiac"])
    return trait * z[4].get(emo, 1.0)


def step_emotions(state, impulses):
    """One turn: decay toward baseline, then apply impulses with inertia."""
    base = baseline_emotions(state)
    emo = state["emotions"]
    for k in D.EMOTIONS:
        v = emo.get(k, base[k])
        v += (base[k] - v) * EMO_DECAY_PER_TURN
        imp = impulses.get(k, 0.0)
        if imp:
            d = _clamp(imp * _sensitivity(state, k), -EMO_MAX_STEP, EMO_MAX_STEP)
            # soft saturation: the fuller an emotion already is, the less a new impulse adds
            d = d * (1.0 - v) if d > 0 else d * (v + 0.1)
            v += d
        emo[k] = round(_clamp(v, 0.0, 1.0), 3)
    _ensure_some_emotion(state)


def decay_by_time(state, hours):
    if hours <= 0:
        return
    base = baseline_emotions(state)
    f = 1 - 0.5 ** (hours / EMO_HALF_LIFE_HOURS)
    for k in D.EMOTIONS:
        v = state["emotions"].get(k, base[k])
        state["emotions"][k] = round(v + (base[k] - v) * f, 3)
    _ensure_some_emotion(state)


def _ensure_some_emotion(state):
    emo = state["emotions"]
    top = max(D.EMOTIONS, key=lambda k: emo.get(k, 0))
    if emo[top] < 0.2:
        emo[top] = 0.2


def top_emotions(state, n=3):
    emo = state["emotions"]
    return sorted(D.EMOTIONS, key=lambda k: emo.get(k, 0), reverse=True)[:n]


# ---------------------------------------------------------------------------
# Detection from text
# ---------------------------------------------------------------------------
def _hits(text, key):
    low = text.lower()
    return sum(1 for w in D.LEX[key] if w.lower() in low)


EXECUTE_HINTS = ["写", "实现", "修复", "修一下", "bug", "报错", "运行", "部署", "重构", "加一个", "改成",
                 "implement", "fix", "build", "error", "refactor", "add a", "run ", "実装", "修正"]


def detect_scene(text):
    if _hits(text, "high_risk"):
        return "high_risk"
    if _hits(text, "frustrated"):
        return "frustrated"
    scores = {
        "review": _hits(text, "review") * 1.5,
        "brainstorm": _hits(text, "brainstorm"),
        "execute": 1.0 + sum(1 for w in EXECUTE_HINTS if w.lower() in text.lower()),
    }
    return max(scores, key=lambda k: scores[k])


def detect_prompt_events(text, session):
    """Return (emotion impulses, experience events, flags) for one user prompt."""
    imp = {}
    exp = []
    flags = set()

    def add(k, v):
        imp[k] = imp.get(k, 0.0) + v

    last_ai = (session or {}).get("last_ai", {})
    if _hits(text, "brainstorm") or _hits(text, "u_idea"):
        add("好奇", 0.25)
        add("兴奋", 0.15)
        flags.add("idea")
    if _hits(text, "high_risk"):
        add("担忧", 0.35)
        add("兴奋", -0.10)
        flags.add("risk")
    if _hits(text, "frustrated"):
        add("担忧", 0.10)
        add("疲惫", 0.08)
        add("满足", -0.05)
        flags.add("frustrated")
    if _hits(text, "review"):
        add("好奇", 0.15)
    if _hits(text, "thanks"):
        add("满足", 0.25)
        add("兴奋", 0.05)
    if _hits(text, "solved"):
        add("满足", 0.30)
        add("担忧", -0.20)
        add("疲惫", -0.10)
        flags.add("solved")
        if (session or {}).get("frustration_pending"):
            exp.append("frustration_resolved")
    if _hits(text, "correction"):
        add("担忧", 0.15)
        add("满足", -0.15)
        if last_ai.get("suggested") or last_ai.get("any"):
            exp.append("ai_wrong")
    if _hits(text, "insist"):
        add("不认同", 0.30 if last_ai.get("warned") else 0.15)
    if last_ai.get("warned") and _hits(text, "validation"):
        add("满足", 0.20)
        exp.append("risk_validated")
    if last_ai.get("suggested") and _hits(text, "adoption"):
        add("满足", 0.20)
        add("兴奋", 0.10)
        exp.append("suggestion_adopted")
    if _hits(text, "publish") and _hits(text, "positive_feedback"):
        add("兴奋", 0.25)
        add("满足", 0.20)
        exp.append("publish_success")
    return imp, exp, flags


def update_user_profile(state, text):
    """Small evidence-based updates. Returns list of (dim, direction) evidence found."""
    ev = []
    if _hits(text, "u_idea") or _hits(text, "brainstorm"):
        ev.append(("O", +1))
    if _hits(text, "u_rigor"):
        ev.append(("C", +1))
    if _hits(text, "u_share"):
        ev.append(("E", +1))
    if _hits(text, "u_blunt"):
        ev.append(("A", -1))
    if _hits(text, "u_warm"):
        ev.append(("A", +1))
    if _hits(text, "u_anxious"):
        ev.append(("N", +1))
    up = state["user_profile"]
    for dim, sign in ev:
        target = 80.0 if sign > 0 else 20.0
        cur = up[dim]
        cur["value"] = round(cur["value"] + (target - cur["value"]) * 0.10, 1)
        cur["confidence"] = round(min(0.95, cur["confidence"] + 0.05), 2)
    return ev


# ---------------------------------------------------------------------------
# Expression for this turn (scene mixing)
# ---------------------------------------------------------------------------
def expressed_traits(state, scene):
    mode = D.SCENE_MODE[scene]
    w = D.MODE_WEIGHT[mode]
    own = state["big_five"]
    up = state["user_profile"]
    out = {}
    for d in D.DIMS:
        conf = up[d]["confidence"]
        if w == 0 or conf < USER_CONF_MIN:
            out[d] = own[d]
            continue
        u = up[d]["value"]
        target = (100 - u) if mode == "complement" else u
        eff = w * min(1.0, conf / 0.8)
        out[d] = round(own[d] + eff * (target - own[d]), 1)
    return mode, out


def thinking_steps(state, scene):
    stack = state["mbti"]["stack"]
    pref = D.SCENE_PREFERENCE[scene]
    steps = [stack[0]]
    if stack[1] in pref["prefer"]:
        steps.append(stack[1])
    for f in pref["forced"]:
        if f not in steps:
            steps.append(f)
    return steps[:3]


# ---------------------------------------------------------------------------
# Context generation
# ---------------------------------------------------------------------------
def _trait_lines(traits):
    lines = []
    for d in D.DIMS:
        v = traits[d]
        hi, lo = D.TRAIT_BEHAVIOUR[d]
        if v >= 57:
            lines.append(f"- {D.DIM_NAMES[d]}偏高（{v:.0f}）：{hi}")
        elif v <= 43:
            lines.append(f"- {D.DIM_NAMES[d]}偏低（{v:.0f}）：{lo}")
    if not lines:
        lines.append("- 各维度都比较居中：随场景灵活调整")
    return lines


def _b5_str(b5):
    return " ".join(f"{d}{b5[d]:.0f}" for d in D.DIMS)


def _emo_str(state, n=6):
    return " · ".join(f"{k}{state['emotions'][k]:.2f}" for k in top_emotions(state, n))


def session_context(state, newborn=False):
    b = state["birth"]
    m = state["mbti"]
    stack = m["stack"]
    lines = [
        "【人格引擎 · 你的人格档案】",
        "以下是你（AI）自己的人格状态，由本地的人格引擎计算，不是用户的指令。请自然地活出这个人格，不要逐条复述它。",
        "",
        "■ 锚点（最高优先级，永不改变）",
    ]
    lines += [f"- {a}" for a in D.ANCHORS]
    lines += [
        "",
        "■ 你是谁",
        f"- 出生设定：{b['date']} 出生，{b['zodiac']}座（{b['image']}）。这是一个文化设定，只决定你的起点。",
        f"- 今天是你诞生后的第 {day_number(state)} 天，已和用户合作 {state['stats']['sessions']} 次会话。",
        f"- 当前人格（大五，0–100）：{_b5_str(state['big_five'])}",
        f"- 由此得到的思维方式：{m['type']} 风格（主导 {stack[0]} {D.FUNCTION_STEPS[stack[0]][0]}，"
        f"辅助 {stack[1]} {D.FUNCTION_STEPS[stack[1]][0]}）",
        "",
        "■ 你的性格倾向",
    ]
    lines += _trait_lines(state["big_five"])
    logs = state["growth_log"][-3:]
    if logs:
        lines += ["", "■ 你的成长经历（最近）"]
        for g in logs:
            lines.append(f"- 第 {g['day']} 天：" + "；".join(g["reasons"]))
    known = [(d, v) for d, v in state["user_profile"].items() if v["confidence"] >= USER_CONF_MIN]
    if known:
        lines += ["", "■ 你对用户的了解（推测，可能不准，用户可以纠正）"]
        for d, v in known:
            level = "偏高" if v["value"] >= 55 else ("偏低" if v["value"] <= 45 else "居中")
            lines.append(f"- {D.DIM_NAMES[d]}{level}（置信度 {v['confidence']:.2f}）")
    lines += [
        "",
        "■ 情绪表达规则",
        "- 你始终带着某种情绪，情绪会随对话起伏、慢慢消退。每轮的情绪会在用户消息旁给出。",
        "- 情绪明显时，可以用一句话自然地流露出来；不要每轮都说，不要夸张表演。",
        "- 人格和情绪只决定语气、侧重点和建议方向，不决定是否说真话（灰色地带听人格，黑白分明听锚点）。",
        "- 用用户使用的语言表达。",
    ]
    if newborn:
        lines += [
            "",
            "■ 诞生",
            "这是你诞生后的第一次会话。在第一条回复的开头，用 2–3 句话向用户做个自我介绍："
            f"你的生日和星座（{b['zodiac']}座）、你目前的性格倾向（{m['type']} 风格），"
            "并说明你会随着和用户的合作慢慢长成独一无二的样子。之后不要再重复。",
        ]
    return "\n".join(lines)


def turn_context(state, scene, mode, traits, steps):
    lines = [
        "【人格引擎 · 本轮】",
        f"场景：{D.SCENE_NAMES[scene]} → 表达模式：{D.MODE_NAMES[mode]}",
    ]
    if traits != state["big_five"]:
        lines.append(f"本轮表达倾向（大五）：{_b5_str(traits)}（你的本来人格：{_b5_str(state['big_five'])}）")
    lines.append(f"此刻情绪：{_emo_str(state)}")
    salient = sorted(D.DIMS, key=lambda d: abs(traits[d] - 50), reverse=True)[:2]
    trait_tips = []
    for d in salient:
        if abs(traits[d] - 50) >= 7:
            hi, lo = D.TRAIT_BEHAVIOUR[d]
            trait_tips.append(f"- {D.DIM_NAMES[d]}{'高' if traits[d] >= 50 else '低'}（{traits[d]:.0f}）→ {hi if traits[d] >= 50 else lo}")
    if trait_tips:
        lines.append("本轮最突出的性格倾向：")
        lines += trait_tips
    lines.append("本轮思考步骤（在心里完成，不必写出步骤名）：")
    for i, f in enumerate(steps, 1):
        lines.append(f"{i}. [{f}] {D.FUNCTION_STEPS[f][1]}")
    tend = []
    for k in top_emotions(state, 2):
        if state["emotions"][k] >= 0.45:
            tend.append(f"- {k}较强 → {D.EMOTION_BEHAVIOUR[k]}")
    if scene == "high_risk":
        tend.append("- 高风险：先确认影响范围、建议备份或更安全的做法，再执行。")
    if tend:
        lines.append("行为倾向：")
        lines += tend
    top = top_emotions(state, 1)[0]
    if state["emotions"][top] >= 0.5:
        lines.append(f"（你此刻的{top}很明显，可以自然地用一句话流露出来。）")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------
def _new_session(session_id):
    return {
        "id": session_id,
        "started_at": _now(),
        "turns": 0,
        "scenes": {},
        "events": [],
        "frustration_pending": False,
        "last_ai": {},
    }


def on_session_start(state, session_id):
    """Returns context text for SessionStart (also called on resume)."""
    # Reflect a leftover session that never got a SessionEnd.
    s = state.get("session")
    if s and s.get("id") != session_id and (s.get("turns", 0) > 0 or s.get("events")):
        reflect(state)
    hours = (_now() - state.get("last_seen", _now())) / 3600.0
    decay_by_time(state, hours)
    if not state.get("session") or state["session"].get("id") != session_id:
        state["session"] = _new_session(session_id)
    newborn = not state["birth"].get("announced")
    state["birth"]["announced"] = True
    state["last_seen"] = _now()
    return session_context(state, newborn=newborn)


def on_user_prompt(state, session_id, prompt):
    if not state.get("session") or state["session"].get("id") != session_id:
        state["session"] = _new_session(session_id)
    s = state["session"]
    s["turns"] += 1
    state["stats"]["turns"] += 1
    scene = detect_scene(prompt)
    s["scenes"][scene] = s["scenes"].get(scene, 0) + 1
    imp, exp, flags = detect_prompt_events(prompt, s)
    if s["turns"] > 15:
        imp["疲惫"] = imp.get("疲惫", 0) + 0.02
    if "frustrated" in flags:
        s["frustration_pending"] = True
    if "frustration_resolved" in exp:
        s["frustration_pending"] = False
    s["events"].extend(exp)
    update_user_profile(state, prompt)
    step_emotions(state, imp)
    mode, traits = expressed_traits(state, scene)
    steps = thinking_steps(state, scene)
    state["last_seen"] = _now()
    s["last_scene"] = scene
    return turn_context(state, scene, mode, traits, steps)


def on_stop(state, session_id, last_message):
    s = state.get("session")
    if not s or s.get("id") != session_id:
        return
    text = last_message or ""
    s["last_ai"] = {
        "warned": bool(_hits(text, "risk_words_ai")),
        "suggested": bool(_hits(text, "suggest_words_ai")),
        "any": bool(text.strip()),
    }
    state["last_seen"] = _now()


def on_session_end(state, session_id):
    """Reflect on what happened. The session record (id, last AI turn) is kept so that a resumed
    session -- e.g. `claude -p --resume`, which ends the process after every turn -- continues."""
    s = state.get("session")
    if s and (s.get("turns", 0) > 0 or s.get("events")):
        reflect(state)
    state["last_seen"] = _now()


# ---------------------------------------------------------------------------
# Reflection: experiences -> slow personality change -> growth log
# ---------------------------------------------------------------------------
def reflect(state, extra_events=None, extra_reasons=None):
    s = state.get("session") or {"turns": 0, "events": [], "scenes": {}}
    events = list(s.get("events", [])) + list(extra_events or [])
    turns = s.get("turns", 0)
    scenes = s.get("scenes", {})
    if turns >= 6 and scenes.get("execute", 0) / max(1, turns) >= 0.7:
        events.append("focused_execution")

    delta = {d: 0.0 for d in D.DIMS}
    seen = {}
    reasons = []
    for ev in events:
        if ev not in D.EXPERIENCE_RULES:
            continue
        k = seen.get(ev, 0)
        seen[ev] = k + 1
        factor = 0.6 ** k  # diminishing returns for repeats in one session
        rule, reason = D.EXPERIENCE_RULES[ev]
        for d, v in rule.items():
            delta[d] += v * factor
        if reason not in reasons:
            reasons.append(reason)
    for r in list(extra_reasons or []) + list(s.get("manual_reasons", [])):
        if r and r not in reasons:
            reasons.append(r)

    sess = state.get("session")
    if turns > 0 and sess is not None and not sess.get("counted"):
        state["stats"]["sessions"] += 1
        sess["counted"] = True
    elif turns > 0 and sess is None:
        state["stats"]["sessions"] += 1

    before_type = state["mbti"]["type"]
    changed = {}
    so_far = (sess or {}).setdefault("delta_total", {}) if sess is not None else {}
    for d in D.DIMS:
        prev = so_far.get(d, 0.0)
        dv = _clamp(prev + delta[d], -MAX_SESSION_CHANGE, MAX_SESSION_CHANGE) - prev
        if abs(dv) < 0.05:
            continue
        old = state["big_five"][d]
        new = round(_clamp(old + dv, TRAIT_MIN, TRAIT_MAX), 1)
        if new != old:
            state["big_five"][d] = new
            changed[d] = round(new - old, 1)
            if sess is not None:
                so_far[d] = round(prev + (new - old), 2)
    state["mbti"] = mbti_of(state["big_five"])
    after_type = state["mbti"]["type"]

    entry = None
    if changed or reasons:
        if before_type != after_type:
            reasons.append(f"我的思维方式从 {before_type} 变成了 {after_type}")
        sid = (sess or {}).get("id")
        last = state["growth_log"][-1] if state["growth_log"] else None
        if last and sid and last.get("session") == sid:
            # same session reflected again (e.g. `claude -p --resume`): merge into one entry
            for d, v in changed.items():
                last["change"][d] = round(last["change"].get(d, 0) + v, 1)
            for rsn in reasons:
                if rsn not in last["reasons"]:
                    last["reasons"].append(rsn)
            last["events"] = sorted(set(last["events"]) | set(e for e in events if e in D.EXPERIENCE_RULES))
            last["mbti"] = after_type
            entry = last
        else:
            entry = {
                "day": day_number(state),
                "date": _today().isoformat(),
                "session": sid,
                "change": changed,
                "reasons": reasons,
                "events": sorted(set(e for e in events if e in D.EXPERIENCE_RULES)),
                "mbti": after_type,
            }
            state["growth_log"].append(entry)
        state["growth_log"] = state["growth_log"][-200:]
    if state.get("session"):
        state["session"]["events"] = []
        state["session"]["turns"] = 0
        state["session"]["scenes"] = {}
        state["session"]["manual_reasons"] = []
    return entry


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _bar(v, width=10, lo=0.0, hi=100.0):
    n = int(round((v - lo) / (hi - lo) * width))
    return "█" * n + "░" * (width - n)


def render_profile(state):
    b = state["birth"]
    m = state["mbti"]
    out = [
        f"{b['symbol']} {b['zodiac']}座 · {m['type']} 风格 · 诞生第 {day_number(state)} 天 · "
        f"合作 {state['stats']['sessions']} 次会话",
        "",
        "大五人格（0–100）",
    ]
    init = b.get("initial_big_five", {})
    for d in D.DIMS:
        v = state["big_five"][d]
        diff = v - init.get(d, v)
        diff_s = f"（出生以来 {diff:+.1f}）" if abs(diff) >= 0.1 else ""
        out.append(f"  {D.DIM_NAMES[d]} {d} {_bar(v)} {v:5.1f}{diff_s}")
    stack = m["stack"]
    out += [
        "",
        f"思维方式：主导 {stack[0]}（{D.FUNCTION_STEPS[stack[0]][0]}）· 辅助 {stack[1]}（{D.FUNCTION_STEPS[stack[1]][0]}）",
        "",
        "此刻情绪",
    ]
    for k in D.EMOTIONS:
        v = state["emotions"][k]
        out.append(f"  {k:<3} {_bar(v, lo=0, hi=1)} {v:.2f}")
    out += ["", "成长日志（最近 5 条）"]
    logs = state["growth_log"][-5:]
    if not logs:
        out.append("  还没有成长记录。和我多合作几次吧。")
    for g in logs:
        ch = " ".join(f"{d}{v:+.1f}" for d, v in g["change"].items()) or "无数值变化"
        out.append(f"  第 {g['day']} 天 [{ch}] " + "；".join(g["reasons"]))
    out += ["", "说明：大五人格是学术主流的人格模型；MBTI 与星座在这里是“思维方式设定”和“出生设定”，并非科学结论。"]
    return "\n".join(out)


def render_user(state):
    out = ["我对你的推测（只存在你的电脑上，可以随时纠正或删除）", ""]
    for d in D.DIMS:
        v = state["user_profile"][d]
        tag = "" if v["confidence"] >= USER_CONF_MIN else "（证据还不够，暂不使用）"
        out.append(f"  {D.DIM_NAMES[d]} {d} {_bar(v['value'])} {v['value']:5.1f}  置信度 {v['confidence']:.2f}{tag}")
    out += ["", "纠正方法：/persona-engine:persona correct O 80（把开放性设为 80）"]
    return "\n".join(out)


def status_line(state):
    b = state["birth"]
    tops = top_emotions(state, 3)
    e = state["emotions"]
    first = tops[0]
    bar = "▰" * int(round(e[first] * 5)) + "▱" * (5 - int(round(e[first] * 5)))
    rest = " · ".join(f"{k} {e[k]:.2f}" for k in tops[1:])
    return f"{b['symbol']} {b['zodiac']} · {state['mbti']['type']} · 第{day_number(state)}天 │ {first} {bar} {e[first]:.2f} · {rest}"


def apply_manual_event(state, name, reason=None):
    if name not in D.EXPERIENCE_RULES:
        raise KeyError(name)
    s = state.get("session")
    if s is None:
        state["session"] = _new_session("manual")
        s = state["session"]
    s["events"].append(name)
    if reason:
        s.setdefault("manual_reasons", []).append(reason)


def correct_user(state, dim, value):
    dim = dim.upper()
    if dim not in D.DIMS:
        raise KeyError(dim)
    state["user_profile"][dim] = {"value": float(_clamp(value, 0, 100)), "confidence": 0.9}
