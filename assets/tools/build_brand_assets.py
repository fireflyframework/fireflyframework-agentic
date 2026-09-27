#!/usr/bin/env python3
"""Generate the Firefly Agentic banner and nine diagrams, fully offline.

Run with Python 3.13+: python assets/tools/build_brand_assets.py
Verify committed outputs: python assets/tools/build_brand_assets.py --check

No generation dependencies or installed fonts are required. Embedded font
advances make layout deterministic across operating systems. The shared family
wordmark and vendored icons remain vector paths, with no external resources.
All outputs are written to assets/ and mirrored byte-for-byte to docs/assets/.
Render with CairoSVG separately for visual inspection after content changes.
"""

from __future__ import annotations
import argparse
import sys
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ASSETS = REPO / "assets"
sys.path.insert(0, str(HERE))
from wordmark import FIREFLY_PATH, DOT_CX, DOT_CY, DOT_R
from icons import ICONS

# --------------------------------------------------------------------------- palette
WHITE = "#ffffff"
VIOLET = "#8b5cf6"
VIOLET2 = "#7c3aed"
VIOLETD = "#6d28d9"
MID = "#5b21b6"
DARK = "#4c1d95"
INK = "#1e1633"
BODY = "#322b45"
MUTED = "#756881"
SUB = "#f5f2fe"
STROKE = "#e4def5"
INDIGO = "#6366f1"
AMBER = "#c2722a"
DOT_HOT = "#F68000"
DOT_WARM = "#FFF9C1"
MONO = "ui-monospace,'SF Mono',Menlo,Consolas,monospace"
SANS = "-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"

# Fixed Arial advance widths, in em units, keep layout identical on every OS.
# Font files are not bundled or read at generation time. Rendering uses a system
# fallback stack, so generous card padding and visual checks remain necessary.
_REGULAR_ADVANCES = {
    " ": 0.2778,
    "!": 0.2778,
    '"': 0.355,
    "#": 0.5562,
    "$": 0.5562,
    "%": 0.8892,
    "&": 0.667,
    "'": 0.1909,
    "(": 0.333,
    ")": 0.333,
    "*": 0.3892,
    "+": 0.584,
    ",": 0.2778,
    "-": 0.333,
    ".": 0.2778,
    "/": 0.2778,
    "0": 0.5562,
    "1": 0.5562,
    "2": 0.5562,
    "3": 0.5562,
    "4": 0.5562,
    "5": 0.5562,
    "6": 0.5562,
    "7": 0.5562,
    "8": 0.5562,
    "9": 0.5562,
    ":": 0.2778,
    ";": 0.2778,
    "<": 0.584,
    "=": 0.584,
    ">": 0.584,
    "?": 0.5562,
    "@": 1.0151,
    "A": 0.667,
    "B": 0.667,
    "C": 0.7222,
    "D": 0.7222,
    "E": 0.667,
    "F": 0.6108,
    "G": 0.7778,
    "H": 0.7222,
    "I": 0.2778,
    "J": 0.5,
    "K": 0.667,
    "L": 0.5562,
    "M": 0.833,
    "N": 0.7222,
    "O": 0.7778,
    "P": 0.667,
    "Q": 0.7778,
    "R": 0.7222,
    "S": 0.667,
    "T": 0.6108,
    "U": 0.7222,
    "V": 0.667,
    "W": 0.9438,
    "X": 0.667,
    "Y": 0.667,
    "Z": 0.6108,
    "[": 0.2778,
    "\\": 0.2778,
    "]": 0.2778,
    "^": 0.4692,
    "_": 0.5562,
    "`": 0.333,
    "a": 0.5562,
    "b": 0.5562,
    "c": 0.5,
    "d": 0.5562,
    "e": 0.5562,
    "f": 0.2778,
    "g": 0.5562,
    "h": 0.5562,
    "i": 0.2222,
    "j": 0.2222,
    "k": 0.5,
    "l": 0.2222,
    "m": 0.833,
    "n": 0.5562,
    "o": 0.5562,
    "p": 0.5562,
    "q": 0.5562,
    "r": 0.333,
    "s": 0.5,
    "t": 0.2778,
    "u": 0.5562,
    "v": 0.5,
    "w": 0.7222,
    "x": 0.5,
    "y": 0.5,
    "z": 0.5,
    "{": 0.334,
    "|": 0.2598,
    "}": 0.334,
    "~": 0.584,
    "·": 0.333,
    "×": 0.584,
    "→": 1.0,
    "–": 0.5562,
    "—": 1.0,
    "…": 1.0,
}
_BOLD_ADVANCES = {
    " ": 0.2778,
    "!": 0.333,
    '"': 0.4741,
    "#": 0.5562,
    "$": 0.5562,
    "%": 0.8892,
    "&": 0.7222,
    "'": 0.2378,
    "(": 0.333,
    ")": 0.333,
    "*": 0.3892,
    "+": 0.584,
    ",": 0.2778,
    "-": 0.333,
    ".": 0.2778,
    "/": 0.2778,
    "0": 0.5562,
    "1": 0.5562,
    "2": 0.5562,
    "3": 0.5562,
    "4": 0.5562,
    "5": 0.5562,
    "6": 0.5562,
    "7": 0.5562,
    "8": 0.5562,
    "9": 0.5562,
    ":": 0.333,
    ";": 0.333,
    "<": 0.584,
    "=": 0.584,
    ">": 0.584,
    "?": 0.6108,
    "@": 0.9751,
    "A": 0.7222,
    "B": 0.7222,
    "C": 0.7222,
    "D": 0.7222,
    "E": 0.667,
    "F": 0.6108,
    "G": 0.7778,
    "H": 0.7222,
    "I": 0.2778,
    "J": 0.5562,
    "K": 0.7222,
    "L": 0.6108,
    "M": 0.833,
    "N": 0.7222,
    "O": 0.7778,
    "P": 0.667,
    "Q": 0.7778,
    "R": 0.7222,
    "S": 0.667,
    "T": 0.6108,
    "U": 0.7222,
    "V": 0.667,
    "W": 0.9438,
    "X": 0.667,
    "Y": 0.667,
    "Z": 0.6108,
    "[": 0.333,
    "\\": 0.2778,
    "]": 0.333,
    "^": 0.584,
    "_": 0.5562,
    "`": 0.333,
    "a": 0.5562,
    "b": 0.6108,
    "c": 0.5562,
    "d": 0.6108,
    "e": 0.5562,
    "f": 0.333,
    "g": 0.6108,
    "h": 0.6108,
    "i": 0.2778,
    "j": 0.2778,
    "k": 0.5562,
    "l": 0.2778,
    "m": 0.8892,
    "n": 0.6108,
    "o": 0.6108,
    "p": 0.6108,
    "q": 0.6108,
    "r": 0.3892,
    "s": 0.5562,
    "t": 0.333,
    "u": 0.6108,
    "v": 0.5562,
    "w": 0.7778,
    "x": 0.5562,
    "y": 0.5562,
    "z": 0.5,
    "{": 0.3892,
    "|": 0.2798,
    "}": 0.3892,
    "~": 0.584,
    "·": 0.333,
    "×": 0.584,
    "→": 1.0,
    "–": 0.5562,
    "—": 1.0,
    "…": 1.0,
}


def tw(s, size, bold=False):
    advances = _BOLD_ADVANCES if bold else _REGULAR_ADVANCES
    return size * sum(advances.get(ch, 0.75) for ch in str(s))


def mw(s, size):
    return 0.64 * size * len(str(s))


def esc(s):
    return escape(str(s), quote=True)


OUTPUTS = {}


def write_svg(name, svg):
    OUTPUTS[name] = svg


# --------------------------------------------------------------------------- kit
def defs(cx, cy, r=520):
    return f'''<defs>
    <linearGradient id="hdr" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#9269f1"/><stop offset="1" stop-color="{VIOLETD}"/></linearGradient>
    <linearGradient id="door" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#a78bfa"/><stop offset="1" stop-color="#7c3aed"/></linearGradient>
    <linearGradient id="bed" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#271c41"/><stop offset="1" stop-color="#140e25"/></linearGradient>
    <linearGradient id="card" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#f4eeff"/></linearGradient>
    <radialGradient id="amb" cx="{cx}" cy="{cy}" r="{r}" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="{VIOLET}" stop-opacity="0.14"/><stop offset="0.6" stop-color="{INDIGO}" stop-opacity="0.05"/><stop offset="1" stop-color="{VIOLET}" stop-opacity="0"/></radialGradient>
    <pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1.5" cy="1.5" r="1.1" fill="#8b5cf6" opacity="0.05"/></pattern>
    <filter id="sh" x="-25%" y="-25%" width="150%" height="180%"><feDropShadow dx="0" dy="2.5" stdDeviation="4" flood-color="#3b1d6e" flood-opacity="0.14"/></filter>
    <marker id="arr" markerWidth="9" markerHeight="9" refX="6.2" refY="3.2" orient="auto"><path d="M0 0L7 3.2L0 6.4Z" fill="{VIOLETD}"/></marker>
    <marker id="arrb" markerWidth="9" markerHeight="9" refX="6.2" refY="3.2" orient="auto"><path d="M0 0L7 3.2L0 6.4Z" fill="{INDIGO}"/></marker>
    <marker id="arra" markerWidth="9" markerHeight="9" refX="6.2" refY="3.2" orient="auto"><path d="M0 0L7 3.2L0 6.4Z" fill="{AMBER}"/></marker>
    <g id="fly"><circle r="8.5" fill="#a78bfa" opacity="0.10"/><circle r="4.6" fill="#c4b5fd" opacity="0.22"/><circle r="2.4" fill="#ddd6fe" opacity="0.75"/><circle r="1.2" fill="#f5f3ff"/></g>
    <g id="ffly"><circle r="8.5" fill="#f6a821" opacity="0.10"/><circle r="4.6" fill="#ffc24a" opacity="0.22"/><circle r="2.4" fill="#ffd980" opacity="0.78"/><circle r="1.2" fill="#fff6e0"/></g>
  </defs>'''


def frame(w, h):
    return (
        f'<rect width="{w}" height="{h}" fill="{WHITE}"/>'
        f'<rect x="3" y="3" width="{w - 6}" height="{h - 6}" rx="18" fill="{WHITE}" stroke="{STROKE}" stroke-width="1.5"/>'
        f'<rect x="3" y="3" width="{w - 6}" height="{h - 6}" rx="18" fill="url(#grid)"/>'
        f'<rect x="3" y="3" width="{w - 6}" height="{h - 6}" rx="18" fill="url(#amb)"/>'
    )


def logo_w(h):
    return 469.0 * h / 138.0


def firefly_logo(x, cy, h=24, fill=VIOLET2, anchor="left"):
    """The real Firefly wordmark logo — the embedded 'firefly' word + the amber
    glow-dot, recolored. Vertical centre at cy; x is the left edge (anchor='left')
    or the horizontal centre (anchor='mid'). Used as the brand mark in diagrams."""
    s = h / 138.0
    w = 469.0 * s
    left = x - w / 2 if anchor == "mid" else x
    tx = left - 4.0 * s
    ty = cy - 105.45 * s  # bbox y mid = (36.5+174.4)/2
    dcx = tx + DOT_CX * s
    dcy = ty + DOT_CY * s
    return (
        f'<circle cx="{dcx:.2f}" cy="{dcy:.2f}" r="{27 * s:.2f}" fill="#f6a821" opacity="0.18"/>'
        f'<g transform="translate({tx:.2f},{ty:.2f}) scale({s:.4f})"><path d="{FIREFLY_PATH}" fill="{fill}"/></g>'
        f'<circle cx="{dcx:.2f}" cy="{dcy:.2f}" r="{15 * s:.2f}" fill="url(#dot)"/>'
    )


def icon(name, cx, cy, size, color=None):
    ic = ICONS.get(name)
    if not ic:
        return ""
    vb = [float(v) for v in ic["vb"].split()]
    vw, vh = vb[2], vb[3]
    s = size / max(vw, vh)
    return (
        f'<g transform="translate({cx:.1f},{cy:.1f}) scale({s:.4f}) translate({-vw / 2:.1f},{-vh / 2:.1f})">'
        f'<path d="{ic["d"]}" fill="{color or ic["color"]}"/></g>'
    )


def title(w, t, sub=None, repo="fireflyframework-agentic"):
    s = [
        firefly_logo(26, 31, 25),
        f'<text x="{26 + logo_w(25) + 13:.0f}" y="44" font-size="20" font-weight="800" fill="{INK}" font-family="{SANS}" letter-spacing="0.2">{esc(t)}</text>',
        f'<text x="{w - 26}" y="22" text-anchor="end" font-size="10" font-weight="600" fill="#b29ddb" font-family="{MONO}">{repo}</text>',
        f'<line x1="26" y1="62" x2="{w - 26}" y2="62" stroke="{VIOLET2}" stroke-width="1.4" opacity="0.42"/>',
    ]
    if sub:
        s.append(f'<text x="26" y="84" font-size="14" fill="{MUTED}" font-family="{SANS}">{esc(sub)}</text>')
    return "\n  ".join(s)


def svgdoc(w, h, label, body, amb=None):
    cx, cy = amb or (w - 60, 40)
    dot = (
        '<radialGradient id="dot" cx="42%" cy="34%" r="72%"><stop offset="0" stop-color="' + DOT_WARM + '"/>'
        '<stop offset="1" stop-color="' + DOT_HOT + '"/></radialGradient>'
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'role="img" aria-labelledby="diagram-title diagram-description" font-family="{SANS}">\n  '
        + f'<title id="diagram-title">{esc(label.split(". ", 1)[0])}</title><desc id="diagram-description">{esc(label)}</desc>\n  '
        + defs(cx, cy).replace("</defs>", dot + "</defs>")
        + "\n  "
        + frame(w, h)
        + "\n  "
        + body
        + "\n</svg>\n"
    )


WARN = []


def arrow(x1, y1, x2, y2, color=VIOLETD, dash=None, mk="arr", sw=1.8):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="{sw}"{d} marker-end="url(#{mk})"/>'


def spark(cx, cy, r, color):
    return (
        f'<path d="M{cx} {cy - r}L{cx + r * 0.28} {cy - r * 0.28}L{cx + r} {cy}L{cx + r * 0.28} {cy + r * 0.28}'
        f'L{cx} {cy + r}L{cx - r * 0.28} {cy + r * 0.28}L{cx - r} {cy}L{cx - r * 0.28} {cy - r * 0.28}Z" fill="{color}"/>'
    )


def check(name, rects, pad=2):
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            a, b = rects[i], rects[j]
            if a[0] < b[2] - pad and b[0] < a[2] - pad and a[1] < b[3] - pad and b[1] < a[3] - pad:
                WARN.append(f"{name}: overlap {i}&{j}")


# --------------------------------------------------------------------------- banner
def build_banner():
    W, H = 1280, 320
    wx, wy, ws = 80, 116, 0.74
    dot_x, dot_y = wx + ws * DOT_CX, wy + ws * DOT_CY
    wm_right = wx + ws * 469
    # a deliberate agent graph: input -> three agents -> two merge hubs -> output (+ 2 satellites)
    GN = [
        (726, 162, 2.0, "a"),
        (892, 98, 1.5, "v"),
        (892, 162, 1.7, "v"),
        (892, 226, 1.5, "v"),
        (1052, 126, 1.5, "a"),
        (1052, 200, 1.5, "a"),
        (1212, 162, 1.95, "v"),
        (986, 62, 0.85, "a"),
        (1150, 258, 0.85, "v"),
    ]
    GE = [(0, 1), (0, 2), (0, 3), (1, 4), (2, 4), (2, 5), (3, 5), (4, 6), (5, 6), (7, 1), (8, 5)]
    gx = lambda i: GN[i][0]
    gy = lambda i: GN[i][1]
    hero = lambda a, b: a in (0, 6) or b in (0, 6)
    node = "".join(f'<use href="#fb{k}" transform="translate({x},{y}) scale({s})"/>' for x, y, s, k in GN)
    edges = "".join(
        f'<line x1="{gx(a)}" y1="{gy(a)}" x2="{gx(b)}" y2="{gy(b)}" stroke="url(#edge)" stroke-width="{1.4 if hero(a, b) else 1.0}" opacity="{0.55 if hero(a, b) else 0.34}"/>'
        for a, b in GE
    )
    bg = [
        (700, 56, 1.1, 0.4),
        (840, 298, 0.9, 0.3),
        (1244, 84, 1.0, 0.32),
        (1176, 300, 0.9, 0.3),
        (958, 300, 0.8, 0.26),
        (1108, 40, 1.0, 0.3),
        (660, 150, 0.8, 0.3),
    ]
    motes = "".join(f'<circle cx="{x}" cy="{y}" r="{r}" opacity="{o}"/>' for x, y, r, o in bg)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="banner-title banner-description">
  <title id="banner-title">Firefly Agentic</title>
  <desc id="banner-description">Production-grade agents, reasoning and pipelines built on Pydantic AI. The violet Firefly wordmark and amber glow-dot sit beside a constellation of connected agent nodes.</desc>
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="{W}" y2="{H}" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#0a0912"/><stop offset="0.5" stop-color="#130d1f"/><stop offset="1" stop-color="#0d0a18"/></linearGradient>
    <radialGradient id="amb1" cx="320" cy="150" r="520" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#7c3aed" stop-opacity="0.30"/><stop offset="0.55" stop-color="#7c3aed" stop-opacity="0.06"/><stop offset="1" stop-color="#7c3aed" stop-opacity="0"/></radialGradient>
    <radialGradient id="amb2" cx="1040" cy="120" r="560" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#6366f1" stop-opacity="0.24"/><stop offset="0.55" stop-color="#8b5cf6" stop-opacity="0.06"/><stop offset="1" stop-color="#8b5cf6" stop-opacity="0"/></radialGradient>
    <pattern id="bgrid" width="27" height="27" patternUnits="userSpaceOnUse"><circle cx="1.5" cy="1.5" r="1" fill="#9d8bff" opacity="0.05"/></pattern>
    <linearGradient id="edge" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#a78bfa" stop-opacity="0.15"/><stop offset="0.5" stop-color="#c4b5fd" stop-opacity="0.8"/><stop offset="1" stop-color="#a78bfa" stop-opacity="0.15"/></linearGradient>
    <linearGradient id="wm" x1="0" y1="{wy + ws * 36}" x2="0" y2="{wy + ws * 174}" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#e3d8ff"/><stop offset="0.5" stop-color="#a78bfa"/><stop offset="1" stop-color="#7c3aed"/></linearGradient>
    <radialGradient id="dotg" cx="42%" cy="34%" r="72%"><stop offset="0" stop-color="{DOT_WARM}"/><stop offset="1" stop-color="{DOT_HOT}"/></radialGradient>
    <linearGradient id="agw" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#cbbcff"/><stop offset="1" stop-color="#8b5cf6"/></linearGradient>
    <g id="fbv"><circle r="14" fill="#7c5cff" opacity="0.10"/><circle r="8" fill="#a78bfa" opacity="0.20"/><circle r="3.8" fill="#cbb8ff" opacity="0.65"/><circle r="1.9" fill="#f3efff"/></g>
    <g id="fba"><circle r="14" fill="#f6a821" opacity="0.10"/><circle r="8" fill="#ffc24a" opacity="0.18"/><circle r="3.8" fill="#ffd980" opacity="0.66"/><circle r="1.9" fill="#fff6e0"/></g>
  </defs>
  <rect width="{W}" height="{H}" fill="url(#sky)"/>
  <rect width="{W}" height="{H}" fill="url(#bgrid)"/>
  <rect width="{W}" height="{H}" fill="url(#amb1)"/>
  <rect width="{W}" height="{H}" fill="url(#amb2)"/>
  <g fill="#b9a6f0">{motes}</g>
  <g>{edges}</g>
  <g fill="none" stroke-linecap="round">
    <path d="M726,162 C800,150 852,120 892,98" stroke="#b9a6ff" stroke-width="1.6" opacity="0.16"/>
    <path d="M1052,200 C1120,186 1172,172 1212,162" stroke="#ffd07a" stroke-width="1.5" opacity="0.15"/>
  </g>
  {node}
  <g transform="translate({wx},{wy}) scale({ws})" fill="url(#wm)" stroke="#2a0f57" stroke-width="5" stroke-linejoin="round" paint-order="stroke"><path d="{FIREFLY_PATH}"/></g>
  <circle cx="{dot_x:.1f}" cy="{dot_y:.1f}" r="{ws * 30:.1f}" fill="#f6a821" opacity="0.20"/>
  <circle cx="{dot_x:.1f}" cy="{dot_y:.1f}" r="{ws * DOT_R:.1f}" fill="url(#dotg)"/>
  <g transform="translate({wm_right + 30:.0f},0)">
    <line x1="0" y1="146" x2="0" y2="236" stroke="url(#agw)" stroke-width="2.4" opacity="0.7"/>
    <text x="28" y="206" font-size="56" font-weight="800" fill="url(#agw)" font-family="{SANS}" letter-spacing="-1.8">agentic</text>
  </g>
  <rect x="84" y="250" width="336" height="2.6" rx="1.3" fill="url(#agw)" opacity="0.8"/>
  <text x="84" y="281" fill="#efe6ff" font-size="22.5" font-weight="600" font-family="{SANS}">Production-grade agents, reasoning &amp; pipelines</text>
  <text x="84" y="306" fill="#a193cc" font-size="16" font-weight="500" font-family="{SANS}" letter-spacing="0.3">type-safe · model-agnostic · built on Pydantic AI · async-native</text>
  <text x="{W - 26}" y="34" text-anchor="end" font-family="{MONO}" font-size="12" fill="#8574b0" opacity="0.9" letter-spacing="0.4">fireflyframework-agentic</text>
</svg>
'''
    write_svg("banner.svg", svg)


# --------------------------------------------------------------------------- diagram kit


def text_line(x, y, value, size=14, *, bold=False, color=BODY, mono=False, anchor="start"):
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{700 if bold else 400}" '
        f'fill="{color}" font-family="{MONO if mono else SANS}" text-anchor="{anchor}">{esc(value)}</text>'
    )


def panel(x, y, w, h, header, lines=(), *, rects, dark=False, accent=False, size=14):
    """A measured card with a generous title band and 23 px body line spacing."""
    rects.append((x, y, x + w, y + h))
    if tw(header, 16, True) > w - 36:
        WARN.append(f"text does not fit panel header: {header}")
    if lines and 57 + (len(lines) - 1) * 23 + 14 > h:
        WARN.append(f"text does not fit panel height: {header}")
    fill = "url(#bed)" if dark else "url(#card)"
    band = "url(#door)" if accent else "url(#hdr)"
    out = [
        f'<g filter="url(#sh)"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{VIOLET2}" stroke-width="1.5"/></g>'
    ]
    if not dark:
        out.append(f'<path d="M{x} {y + 12}a12 12 0 0 1 12 -12h{w - 24}a12 12 0 0 1 12 12v23H{x}Z" fill="{band}"/>')
    out.append(text_line(x + 18, y + 24, header, 16, bold=True, color="#fff"))
    for i, line in enumerate(lines):
        if tw(line, size) > w - 36:
            WARN.append(f"text does not fit panel {header}: {line}")
        out.append(text_line(x + 18, y + 57 + i * 23, line, size, color="#e1d8f3" if dark else BODY))
    return "\n".join(out)


def save_diagram(name, width, height, description, body, rects):
    check(name, rects)
    write_svg(name + ".svg", svgdoc(width, height, description, "\n".join(body)))


# --------------------------------------------------------------------------- architecture


def architecture():
    w, h = 1100, 710
    r = []
    b = [
        title(
            w,
            "Architecture at a glance",
            "The application API and the capabilities you compose around it; this is not an import-dependency graph.",
        )
    ]
    b.append(
        panel(
            42,
            110,
            1016,
            94,
            "Your application: FireflyAgent or @firefly_agent",
            ["Typed inputs and outputs · run / run_sync / run_stream · configure a model once, override per run"],
            rects=r,
        )
    )
    for x in (206, 550, 894):
        b.append(arrow(x, 205, x, 234))
    cards = [
        (
            42,
            "Firefly tools",
            ["@tool · BaseTool · ToolKit", "Guards and tool-call hooks", "Adapted to the agent engine"],
        ),
        (
            386,
            "Firefly memory",
            ["MemoryManager", "Conversation + working memory", "In-memory · file · SQLite", "PostgreSQL · MongoDB"],
        ),
        (
            730,
            "Firefly model configuration",
            [
                "ModelOptions: typed run controls",
                "ModelSpec / ModelFactory",
                "Provider setup and credentials",
                "Explicit Chat / Responses routes",
            ],
        ),
    ]
    for x, header, lines in cards:
        b.append(panel(x, 236, 328, 154, header, lines, rects=r))
    b.append(
        panel(
            42,
            419,
            1016,
            106,
            "Compose what the application needs",
            [
                "Reasoning patterns · pipelines and workflows · retrieval with embeddings and vector stores",
                "Middleware · validation · observability · explainability · experiments and lab",
            ],
            rects=r,
            accent=True,
        )
    )
    b.append(arrow(550, 526, 550, 554))
    b.append(
        panel(
            42,
            556,
            1016,
            94,
            "Pydantic AI 2 engine",
            [
                "Provider clients · model/tool exchange · structured output · streaming (subject to model and API support)"
            ],
            rects=r,
            dark=True,
        )
    )
    b.append(
        text_line(
            550,
            682,
            "Configuration, storage, resilience and security support these capabilities across the framework.",
            14,
            anchor="middle",
            color=MID,
        )
    )
    save_diagram(
        "architecture",
        w,
        h,
        "Firefly Agentic architecture. Applications use FireflyAgent or the firefly_agent decorator with Firefly tools, memory, and typed ModelOptions. Optional reasoning, orchestration, retrieval, and operational modules compose around that API. Pydantic AI 2 supplies the model engine. This view groups capabilities rather than claiming a strict dependency hierarchy.",
        b,
        r,
    )


# --------------------------------------------------------------------------- protocols


def protocols():
    w, h = 1100, 680
    r = []
    b = [
        title(
            w,
            "Extension contracts",
            "Selected public protocols, grouped by responsibility; use the matching constructor, adapter or registry.",
        )
    ]
    groups = [
        ("Agents and tools", ["AgentLike · ToolProtocol", "AgentMiddleware", "GuardProtocol · ToolCallListener"]),
        ("Models and reasoning", ["CredentialResolver", "ReasoningPattern", "ValidationRule"]),
        ("Memory and content", ["MemoryStore · ContentSource", "Chunker · CompressionStrategy", "OfficeConverter"]),
        ("Retrieval", ["EmbeddingProtocol", "VectorStoreProtocol", "ScopedVectorStore"]),
        (
            "Pipelines",
            ["StepExecutor · Checkpointer", "AuditLog · QueryableAuditLog", "EventHandler", "PipelineEventHandler"],
        ),
        ("Workflows", ["AgentRunner", "StreamingAgentRunner", "JournalBackend", "ModelSelectionStrategy"]),
    ]
    for i, (header, lines) in enumerate(groups):
        x, y = 42 + (i % 3) * 344, 110 + (i // 3) * 192
        b.append(panel(x, y, 328, 164, header, lines, rects=r))
    b.append(
        panel(
            42,
            501,
            1016,
            103,
            "Protocols and base classes have different roles",
            [
                "Protocols describe structural contracts. ABCs such as BaseTool, BaseEmbedder, BaseVectorStore",
                "and StorageBackend provide explicit subclass extension points; matching a protocol does not register it.",
            ],
            rects=r,
            accent=True,
        )
    )
    b.append(
        text_line(
            550,
            644,
            "ModelOptions is a typed configuration model, not an extension protocol.",
            14,
            anchor="middle",
            color=MID,
        )
    )
    save_diagram(
        "protocols",
        w,
        h,
        "Selected Firefly extension contracts for agents, tools, models, reasoning, memory, content, retrieval, pipelines, and workflows. Protocol conformance describes a structural contract, not automatic registration. Abstract base classes provide subclass extension points. ModelOptions is typed configuration rather than a protocol.",
        b,
        r,
    )


# --------------------------------------------------------------------------- model routing


def model_routing():
    w, h = 1100, 690
    r = []
    b = [
        title(
            w,
            "One application API, explicit model routes",
            "Keep agent behavior in Firefly; select the provider and API deliberately.",
        )
    ]
    b.append(
        panel(
            170,
            110,
            760,
            84,
            "FireflyAgent / @firefly_agent",
            ["Firefly tools + MemoryManager + ModelOptions"],
            rects=r,
        )
    )
    b.append(arrow(550, 194, 550, 220))
    b.append(
        panel(
            100,
            222,
            900,
            106,
            "Resolve the effective model and validate typed options",
            [
                "Configured model or per-run override; preserve an existing model object's class and client.",
                "Merge ModelOptions, validate against the model/profile, then translate to native request settings.",
            ],
            rects=r,
        )
    )
    b.append(arrow(550, 328, 550, 353))
    b.append(f'<path d="M206 378V354H894V378 M550 354V378" fill="none" stroke="{VIOLETD}" stroke-width="1.8"/>')
    for x in (206, 550, 894):
        b.append(arrow(x, 373, x, 385))
    routes = [
        (
            42,
            "Chat Completions",
            ["openai: · openai-chat:", "azure: · azure-chat:", "Legacy aliases keep Chat", "OpenAI / Azure Chat API"],
        ),
        (
            386,
            "Responses",
            ["openai-responses:", "azure-responses:", "Explicit Responses selection", "OpenAI / Azure Responses API"],
        ),
        (
            730,
            "Other model providers",
            [
                "For example: Anthropic, Google",
                "Provider-specific adapters",
                "ModelSpec / ModelFactory",
                "support configured clients",
            ],
        ),
    ]
    for x, header, lines in routes:
        b.append(panel(x, 387, 328, 158, header, lines, rects=r, accent=True))
    b.append(
        text_line(
            550,
            585,
            "Per-run fields override agent options; explicit None clears an inherited field.",
            14,
            anchor="middle",
            color=MID,
        )
    )
    b.append(
        text_line(
            550,
            614,
            "Unsupported explicit controls fail early with ModelOptionsError. Feature support varies by model and API.",
            14,
            anchor="middle",
        )
    )
    b.append(
        text_line(
            550,
            650,
            "Advanced escape hatch: native model_settings; they do not change the selected API route.",
            14,
            anchor="middle",
            color=MID,
        )
    )
    save_diagram(
        "model-routing",
        w,
        h,
        "Model routing through FireflyAgent. Resolve the effective model, merge typed ModelOptions, validate against the model profile, and translate to native settings. Firefly preserves legacy openai and azure aliases as Chat Completions; openai-responses and azure-responses explicitly select Responses. Other providers use their own adapters. Existing model objects retain their class and client. Support depends on the selected model and API, and unsupported explicit controls raise ModelOptionsError.",
        b,
        r,
    )


# --------------------------------------------------------------------------- agent anatomy


def agent_anatomy():
    w, h = 1100, 760
    r = []
    b = [
        title(
            w,
            "Anatomy of an agent run",
            "A normal successful run through FireflyAgent; middleware can also short-circuit a request.",
        )
    ]
    stages = [
        (110, "1. Before-run middleware", ["Run configured hooks in order; a cache hit may return early."]),
        (222, "2. Load attached memory", ["MemoryManager + conversation_id inject conversation history."]),
        (334, "3. Resolve model and ModelOptions", ["Validate and translate options for the effective model and API."]),
        (446, "4. Execute with Pydantic AI 2", ["Model/tool exchange, structured output or streaming."]),
        (
            558,
            "5. Complete the run",
            [
                "Persist completed history and record enabled usage tracking.",
                "Run after-hooks in reverse order; error-hooks handle failures.",
            ],
        ),
    ]
    for i, (y, header, lines) in enumerate(stages):
        b.append(panel(42, y, 650, 88 if i < 4 else 105, header, lines, rects=r, dark=i == 3))
        if i < 4:
            b.append(arrow(367, y + 89, 367, y + 110))
    b.append(
        panel(
            730,
            110,
            328,
            155,
            "Default middleware",
            [
                "LoggingMiddleware",
                "ObservabilityMiddleware",
                "only when observability is on",
                "default_middleware=False opts out",
            ],
            rects=r,
            accent=True,
            size=13.5,
        )
    )
    b.append(
        panel(
            730,
            289,
            328,
            178,
            "Optional middleware",
            [
                "Prompt and output guards",
                "Cost, cache and prompt cache",
                "Explainability and validation",
                "Retry and circuit breaker",
                "Supply a middleware list",
            ],
            rects=r,
            size=14,
        )
    )
    b.append(
        panel(
            730,
            491,
            328,
            172,
            "Optional agent behavior",
            [
                "BaseTool / ToolKit / @tool",
                "MemoryManager",
                "Delegation and model fallback",
                "Approval / deferred tool results",
                "Enable and configure as needed",
            ],
            rects=r,
        )
    )
    b.append(
        text_line(
            550,
            707,
            "Middleware hooks wrap the run; tool guards wrap tool execution. These are separate extension points.",
            14,
            anchor="middle",
            color=MID,
        )
    )
    b.append(
        text_line(
            550,
            733,
            "Provider and API capabilities still govern tools, reasoning, sampling and streaming.",
            14,
            anchor="middle",
        )
    )
    save_diagram(
        "agent-anatomy",
        w,
        h,
        "A normal successful FireflyAgent run executes before middleware, loads attached conversation memory, resolves and validates model options, calls Pydantic AI 2, persists completed history, tracks configured usage, and executes after hooks in reverse order. Default middleware is logging plus observability when enabled; guards, caching, validation, retry, and circuit breaker middleware are optional. Error hooks run on failures. Cache middleware can return early.",
        b,
        r,
    )


# --------------------------------------------------------------------------- reasoning


def reasoning():
    w, h = 1100, 590
    r = []
    b = [
        title(
            w,
            "Six reasoning patterns, shared contracts",
            "Four patterns use the base template below; Tree of Thoughts and Goal Decomposition override execute().",
        )
    ]
    steps = ["_reason", "_act", "_observe", "_should_continue"]
    for i, step in enumerate(steps):
        x = 64 + i * 248
        b.append(panel(x, 113, 228, 61, step, rects=r))
        if i < 3:
            b.append(arrow(x + 228, 144, x + 246, 144))
    b.append(
        f'<path d="M922 175V207H178V179" fill="none" stroke="{AMBER}" stroke-width="1.8" stroke-dasharray="5 4" marker-end="url(#arra)"/>'
    )
    b.append(
        text_line(
            550,
            242,
            "Base template: ReAct · Chain of Thought · Plan-and-Execute · Reflexion",
            15,
            anchor="middle",
            color=MID,
        )
    )
    pats = [
        ("ReAct", ["Think, call a tool, observe", "Interleaved reasoning and action"]),
        ("Chain of Thought", ["Structured intermediate steps", "A final answer from those steps"]),
        ("Plan-and-Execute", ["Create a plan, execute its steps", "Replan when configured"]),
        ("Reflexion", ["Execute, critique, retry", "Use feedback on another attempt"]),
        ("Tree of Thoughts", ["Generate and evaluate branches", "Select the highest-scored branch"]),
        ("Goal Decomposition", ["Split a goal into sub-goals", "Coordinate their execution"]),
    ]
    for i, (header, lines) in enumerate(pats):
        b.append(panel(42 + (i % 3) * 344, 278 + (i // 3) * 127, 328, 103, header, lines, rects=r))
    b.append(
        text_line(
            550,
            552,
            "All return ReasoningResult with a trace; ReasoningPipeline composes patterns.",
            14,
            anchor="middle",
            color=MID,
        )
    )
    save_diagram(
        "reasoning",
        w,
        h,
        "Six reasoning patterns share result and trace contracts. ReAct, Chain of Thought, Plan-and-Execute, and Reflexion use the AbstractReasoningPattern template: reason, act, observe, and should_continue, with early stopping and iteration limits. Tree of Thoughts overrides execute to generate and score branches; Goal Decomposition overrides execute to coordinate phases and tasks. ReasoningPipeline composes patterns.",
        b,
        r,
    )


# --------------------------------------------------------------------------- pipeline


def pipeline():
    w, h = 1100, 690
    r = []
    b = [
        title(
            w,
            "Pipelines: declarative graphs and explicit state",
            "Build a DAG for parallel stages, or enable cyclic routing for iterative work.",
        )
    ]
    b.append(text_line(42, 124, "EXAMPLE: DOCUMENT PROCESSING DAG", 14, bold=True, color=MID))
    # A two-row flow keeps real API labels readable at documentation widths.
    stages = [
        (42, 151, "Ingest and split", ["BinaryNormalizer", "DocumentSplitter"]),
        (386, 151, "Classify", ["AgentStep", "Typed document category"]),
        (730, 151, "Extract in parallel", ["Send dispatches worker nodes", "Reducers merge worker results"]),
        (730, 303, "Validate", ["OutputReviewer", "Application validation rules"]),
        (386, 303, "Assemble", ["Typed application output", "Merge validated fields"]),
        (42, 303, "Explain", ["ReportBuilder", "Build the processing report"]),
    ]
    for x, y, header, lines in stages:
        b.append(panel(x, y, 328, 108, header, lines, rects=r))
    b.extend(
        [
            arrow(371, 205, 384, 205),
            arrow(715, 205, 728, 205),
            arrow(894, 260, 894, 301),
            arrow(728, 357, 715, 357),
            arrow(384, 357, 371, 357),
        ]
    )
    controls = [
        (
            42,
            "Control flow",
            ["Pause: wait for external input", "Send: dispatch worker payloads", "Cycles: opt in + visit limits"],
        ),
        (
            386,
            "Checkpointing",
            ["Checkpointer / FileCheckpointer", "Persist resumable run state", "Resume from saved checkpoints"],
        ),
        (
            730,
            "Audit and events",
            ["AuditLog records node results", "Event handlers observe progress", "Wire the sinks your app needs"],
        ),
    ]
    for x, header, lines in controls:
        b.append(panel(x, 451, 328, 132, header, lines, rects=r, accent=True))
    b.append(
        text_line(
            550,
            624,
            "PipelineBuilder + PipelineEngine · per-node conditions, retries and timeouts",
            15,
            anchor="middle",
            color=MID,
        )
    )
    b.append(
        text_line(
            550,
            655,
            "The flow above is one application design; these stages are not a required pipeline sequence.",
            14,
            anchor="middle",
        )
    )
    save_diagram(
        "pipeline",
        w,
        h,
        "An example document-processing DAG ingests and splits, classifies, extracts in parallel, validates, assembles, and explains. It illustrates an application composition rather than mandatory stages. PipelineBuilder and PipelineEngine also support explicitly enabled cycles with visit limits. Pause requests external input; Send dispatches worker payloads. Checkpointing and audit/event sinks are configurable.",
        b,
        r,
    )


# --------------------------------------------------------------------------- workflows


def workflows():
    w, h = 1100, 710
    r = []
    b = [
        title(
            w,
            "Workflows: Python control flow around your agents",
            "Use @workflow for code-defined orchestration; call run_workflow() or await the decorated workflow.",
        )
    ]
    b.append(
        panel(
            170,
            110,
            760,
            84,
            "Your async workflow function",
            ["Native conditionals and loops; subworkflow() invokes another workflow."],
            rects=r,
        )
    )
    b.append(arrow(550, 195, 550, 220))
    b.append(
        panel(
            42,
            222,
            1016,
            104,
            "Workflow primitives",
            ["agent() · parallel() · pipeline() · stream()", "phase() · human() · map_agents() · log()"],
            rects=r,
        )
    )
    b.append(arrow(550, 327, 550, 352))
    b.append(
        panel(
            42,
            354,
            1016,
            85,
            "WorkflowContext",
            ["current_workflow() carries the runner, journal, budget, arguments and events."],
            rects=r,
            dark=True,
        )
    )
    cards = [
        (
            42,
            "Runner",
            [
                "FireflyAgentRunner is the default",
                "DefaultAgentRunner is optional",
                "SmartRoutingRunner can select",
                "models through routing strategies",
            ],
        ),
        (
            386,
            "Journal",
            [
                "Completed calls can be replayed",
                "FileJournalBackend persists runs",
                "Resume uses recorded call results",
                "External side effects need care",
            ],
        ),
        (
            730,
            "WorkflowBudget",
            [
                "Concurrent and total agents",
                "Token and cost ceilings",
                "Wall-clock timeout",
                "Configure ceilings for your run",
            ],
        ),
    ]
    for x, header, lines in cards:
        b.append(arrow(x + 164, 440, x + 164, 465))
        b.append(panel(x, 467, 328, 158, header, lines, rects=r, accent=True))
    b.append(
        text_line(
            550,
            662,
            "Verification helpers: cascade · adversarial_verify · judge_panel · loop_until_dry",
            14,
            anchor="middle",
            color=MID,
        )
    )
    b.append(
        text_line(
            550,
            689,
            "Journal replay does not make fresh model calls or arbitrary Python side effects deterministic.",
            14,
            anchor="middle",
        )
    )
    save_diagram(
        "workflows",
        w,
        h,
        "Code-defined workflows use the workflow decorator and native Python control flow. subworkflow is a callable primitive, not a decorator. WorkflowContext carries a runner, journal, budget, arguments, and events. FireflyAgentRunner is the default. Journal replay can reuse completed call results but does not make new model responses or arbitrary side effects deterministic. Verification helpers can evaluate outputs.",
        b,
        r,
    )


# --------------------------------------------------------------------------- retrieval


def rag():
    w, h = 1100, 660
    r = []
    b = [
        title(
            w,
            "Retrieval: a shared API for embeddings and vector stores",
            "Select compatible embedding dimensions, provider configuration and backend behavior.",
        )
    ]
    b.append(
        panel(
            42,
            110,
            328,
            266,
            "Embedding providers",
            [
                "OpenAI · Azure OpenAI",
                "Cohere · Google",
                "Mistral · Voyage AI",
                "AWS Bedrock · Ollama",
                "",
                "EmbeddingProtocol",
                "BaseEmbedder",
            ],
            rects=r,
        )
    )
    b.append(
        panel(
            730,
            110,
            328,
            266,
            "Vector store backends",
            [
                "InMemoryVectorStore",
                "ChromaDB · Pinecone",
                "Qdrant · pgvector",
                "sqlite-vec",
                "",
                "VectorStoreProtocol",
                "BaseVectorStore",
            ],
            rects=r,
        )
    )
    b.append(panel(402, 110, 296, 88, "Index documents", ["VectorDocument -> upsert()"], rects=r))
    b.append(arrow(550, 199, 550, 226))
    b.append(panel(402, 228, 296, 88, "Search", ["search_text(query, top_k=5)"], rects=r))
    b.append(arrow(550, 317, 550, 344))
    b.append(panel(402, 346, 296, 88, "Use retrieved context", ["SearchResult -> FireflyAgent"], rects=r))
    b.append(arrow(371, 164, 400, 164, dash="4 3"))
    b.append(arrow(729, 272, 700, 272, INDIGO, dash="4 3", mk="arrb"))
    b.append(
        panel(
            42,
            473,
            1016,
            104,
            "Compose retrieval with the rest of Firefly",
            [
                "An attached embedder enables automatic document embedding and search_text().",
                "TenantScopedVectorStore scopes namespaces; EmbeddingStep and RetrievalStep integrate with pipelines.",
            ],
            rects=r,
            accent=True,
        )
    )
    b.append(
        text_line(
            550,
            618,
            "Indexing and querying must use the same embedding space. Backend filtering and persistence can differ.",
            14,
            anchor="middle",
            color=MID,
        )
    )
    save_diagram(
        "rag",
        w,
        h,
        "Firefly retrieval supports eight embedding providers and six vector-store backends behind EmbeddingProtocol and VectorStoreProtocol. Documents are upserted, text queries return SearchResult objects, and applications pass retrieved context to FireflyAgent. Automatic embedding and search_text require an attached embedder. Indexing and queries must use compatible embedding dimensions and the same embedding space; filtering and persistence vary by backend.",
        b,
        r,
    )


# --------------------------------------------------------------------------- ecosystem


def ecosystem():
    w, h = 1100, 672
    cx, cy = 550, 370
    r = []
    b = [title(w, "The Firefly family", "Related projects for application services, frontends and agentic systems.")]
    members = [
        ("Java / Spring Boot", "Application services", "springboot", 550, 140),
        (".NET", "Application services", "dotnet", 880, 217),
        ("PyFly", "Python application services", "python", 920, 408),
        ("Rust", "Async application services", "rust", 710, 568),
        ("Go", "Developer tooling", "go", 390, 568),
        ("Frontend", "Angular · flyfront", "angular", 180, 408),
        ("Agentic", "Agents · reasoning · retrieval", "__spark__", 220, 217),
    ]
    for name, meta, ic, x, y in members:
        b.append(
            f'<path d="M{cx} {cy}L{x} {y}" fill="none" stroke="{VIOLET2}" stroke-width="1.5" stroke-dasharray="4 5" opacity="0.45"/>'
        )
    b.append(f'<circle cx="{cx}" cy="{cy}" r="86" fill="{SUB}" stroke="{VIOLET2}" stroke-width="2"/>')
    b.append(firefly_logo(cx, cy - 17, 32, fill=MID, anchor="mid"))
    b.append(text_line(cx, cy + 27, "FRAMEWORK", 15, bold=True, anchor="middle", color=MID))
    for name, meta, ic, x, y in members:
        width, height = 288, 85
        left, top = x - width / 2, y - height / 2
        r.append((left, top, left + width, top + height))
        selected = name == "Agentic"
        b.append(
            f'<g filter="url(#sh)"><rect x="{left}" y="{top}" width="{width}" height="{height}" rx="13" fill="{"url(#hdr)" if selected else WHITE}" stroke="{VIOLET2}" stroke-width="{2.5 if selected else 1.5}"/></g>'
        )
        if selected:
            b.append(spark(left + 29, y - 9, 11, "#ffd07a"))
        else:
            b.append(icon(ic, left + 29, y - 9, 24))
        b.append(text_line(left + 52, y - 3, name, 17, bold=True, color="#fff" if selected else INK))
        b.append(text_line(left + 18, y + 24, meta, 14, color="#eee7ff" if selected else BODY))
    b.append(
        text_line(
            550,
            639,
            "A shared family identity; each project documents its own APIs, features and lifecycle.",
            14,
            anchor="middle",
            color=MID,
        )
    )
    save_diagram(
        "ecosystem",
        w,
        h,
        "The Firefly family includes Java and Spring Boot, .NET, Python PyFly, Rust, Go, Angular frontend, and Agentic for agents, reasoning, and retrieval. Each project has its own APIs and lifecycle; the diagram does not imply universal feature parity.",
        b,
        r,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Verify generated SVGs and their docs mirrors without writing files."
    )
    args = parser.parse_args()
    build_banner()
    for fn in (architecture, protocols, model_routing, reasoning, pipeline, workflows, rag, agent_anatomy, ecosystem):
        fn()
    if WARN:
        raise SystemExit("Diagram validation failed:\n" + "\n".join(WARN))
    drift = []
    for name, svg in OUTPUTS.items():
        for directory in (ASSETS, REPO / "docs" / "assets"):
            path = directory / name
            if args.check:
                if not path.exists() or path.read_bytes() != svg.encode("utf-8"):
                    drift.append(str(path.relative_to(REPO)))
            else:
                path.write_bytes(svg.encode("utf-8"))
    if drift:
        raise SystemExit("Generated assets differ; rerun assets/tools/build_brand_assets.py:\n" + "\n".join(drift))
    print(f"{'Verified' if args.check else 'Wrote'} {len(OUTPUTS)} SVGs and byte-identical documentation mirrors.")
    print("Geometry and measured card-text checks: passed.")


if __name__ == "__main__":
    main()
