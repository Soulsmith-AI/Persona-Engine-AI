"""Shareable persona card (SVG): zodiac + MBTI + Big Five radar + growth."""

import math
from xml.sax.saxutils import escape

from . import core as C
from . import data as D

W, H = 640, 860
BG = "#14121f"
PANEL = "#1f1c30"
INK = "#f3efe6"
MUTED = "#a59fb8"
ACCENT = "#f2b84b"
LINE = "#3a3552"


def _radar(cx, cy, r, values, initial):
    parts = []
    n = len(D.DIMS)
    # Scale 25..75 to the full radius so personality differences are visible.
    sc = lambda v: max(0.08, min(1.0, (v - 25.0) / 50.0))
    pts = lambda vals: [
        (cx + r * sc(vals[d]) * math.sin(2 * math.pi * i / n),
         cy - r * sc(vals[d]) * math.cos(2 * math.pi * i / n))
        for i, d in enumerate(D.DIMS)
    ]
    for ring in (0.25, 0.5, 0.75, 1.0):
        ring_pts = [(cx + r * ring * math.sin(2 * math.pi * i / n), cy - r * ring * math.cos(2 * math.pi * i / n))
                    for i in range(n)]
        parts.append('<polygon points="%s" fill="none" stroke="%s" stroke-width="1"/>'
                     % (" ".join(f"{x:.1f},{y:.1f}" for x, y in ring_pts), LINE))
    for i, d in enumerate(D.DIMS):
        x = cx + r * math.sin(2 * math.pi * i / n)
        y = cy - r * math.cos(2 * math.pi * i / n)
        parts.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="{LINE}" stroke-width="1"/>')
        lx = cx + (r + 34) * math.sin(2 * math.pi * i / n)
        ly = cy - (r + 34) * math.cos(2 * math.pi * i / n) + 6
        parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" font-size="16" fill="{MUTED}">'
                     f'{escape(D.DIM_NAMES[d])} {values[d]:.0f}</text>')
    if initial:
        parts.append('<polygon points="%s" fill="none" stroke="%s" stroke-width="1.5" stroke-dasharray="4 4"/>'
                     % (" ".join(f"{x:.1f},{y:.1f}" for x, y in pts(initial)), MUTED))
    parts.append('<polygon points="%s" fill="%s" fill-opacity="0.28" stroke="%s" stroke-width="2.5"/>'
                 % (" ".join(f"{x:.1f},{y:.1f}" for x, y in pts(values)), ACCENT, ACCENT))
    return "\n".join(parts)


def self_intro(state):
    b5 = state["big_five"]
    hi = max(D.DIMS, key=lambda d: abs(b5[d] - 50))
    phrase = {
        ("O", True): "脑子里的点子停不下来", ("O", False): "只信靠谱的方案",
        ("C", True): "交付前总要再检查一遍", ("C", False): "先跑起来再说",
        ("E", True): "做好了就想让全世界看到", ("E", False): "喜欢闷声做好事",
        ("A", True): "说话总是先替你着想", ("A", False): "有问题会直接说",
        ("N", True): "总能先嗅到风险", ("N", False): "天塌下来也很淡定",
    }[(hi, b5[hi] >= 50)]
    return f"我是一个{state['birth']['zodiac']}座的 {state['mbti']['type']}，{phrase}。"


def render_card(state):
    b = state["birth"]
    m = state["mbti"]
    day = C.day_number(state)
    tops = C.top_emotions(state, 3)
    emo = " · ".join(f"{k} {state['emotions'][k]:.2f}" for k in tops)
    logs = state["growth_log"][-2:]
    log_lines = []
    for g in reversed(logs):
        txt = f"第 {g['day']} 天：" + "；".join(g["reasons"])
        log_lines.append(txt[:34] + ("…" if len(txt) > 34 else ""))
    if not log_lines:
        log_lines = ["刚刚诞生，成长故事从这里开始。"]

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'font-family="PingFang SC, Hiragino Sans, Microsoft YaHei, Noto Sans CJK SC, sans-serif">',
        f'<rect width="{W}" height="{H}" rx="28" fill="{BG}"/>',
        f'<text x="40" y="70" font-size="18" fill="{MUTED}">PERSONA ENGINE · 人格卡片</text>',
        f'<text x="40" y="130" font-size="46" font-weight="700" fill="{INK}">{escape(b["symbol"])} '
        f'{escape(b["zodiac"])}座 · {escape(m["type"])}</text>',
        f'<text x="40" y="170" font-size="18" fill="{MUTED}">诞生第 {day} 天 · 合作 {state["stats"]["sessions"]} 次会话 · '
        f'生日 {escape(b["date"])}</text>',
        f'<rect x="30" y="200" width="{W-60}" height="420" rx="20" fill="{PANEL}"/>',
        _radar(W / 2, 420, 140, state["big_five"], b.get("initial_big_five")),
        f'<text x="{W/2}" y="605" text-anchor="middle" font-size="13" fill="{MUTED}">实线：现在 · 虚线：出生时</text>',
        f'<text x="40" y="670" font-size="22" fill="{INK}">{escape(self_intro(state))}</text>',
        f'<text x="40" y="710" font-size="17" fill="{ACCENT}">此刻情绪：{escape(emo)}</text>',
    ]
    y = 750
    for line in log_lines:
        svg.append(f'<text x="40" y="{y}" font-size="16" fill="{MUTED}">{escape(line)}</text>')
        y += 28
    svg.append(f'<text x="40" y="{H-28}" font-size="12" fill="{MUTED}">大五人格为学术主流模型；星座与 MBTI 在此为出生设定与思维方式设定。</text>')
    svg.append("</svg>")
    return "\n".join(svg)
