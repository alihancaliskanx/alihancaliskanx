#!/usr/bin/env python3
"""Render the profile card into dark_mode.svg / light_mode.svg.

Layout notes
------------
The card is pure monospace text, so every position is derived from one
character-cell width. To make that width the same on every machine, the
@font-face below pulls Consolas in at 109%: Consolas advances 0.55em per
character, the common Linux/Mac fallback (DejaVu Sans Mono) advances
0.602em, and 0.55 * 1.09 = 0.5995. Without this the card renders ~10%
narrower on Windows and the columns drift.

Card width is computed from the content, never hardcoded, so a long value
can widen the card but can never overflow it.
"""
from xml.sax.saxutils import escape
from pathlib import Path

HERE = Path(__file__).parent
ART = (HERE / "ascii-art.txt").read_text().rstrip("\n").split("\n")

FS, LH, PAD, GAP = 16, 20, 26, 4      # font size, line height, padding, art→text gap (chars)
CW = FS * 0.602                       # character cell width after the size-adjust trick

# GitHub's own syntax palette, one set per theme.
THEMES = {
    "dark":  dict(bg="#161b22", fg="#c9d1d9", key="#ffa657",
                  val="#a5d6ff", cc="#616e7f", add="#3fb950", dele="#f85149"),
    "light": dict(bg="#f6f8fa", fg="#24292f", key="#953800",
                  val="#0a3069", cc="#c2cfde", add="#1a7f37", dele="#cf222e"),
}

# ("hdr"|"rule"|"gap"|"kv", data) — placeholder values until the list is filled in.
ROWS = [
    ("hdr",  "alihan@caliskan"),
    ("rule", ""),
    ("kv",   ("OS",       "CachyOS, Windows 11, Android 15")),
    ("kv",   ("Uptime",   "3 years, 2 months, 14 days")),
    ("kv",   ("Host",     "Kocaeli University")),
    ("kv",   ("Shell",    "zsh, fish")),
    ("kv",   ("WM",       "Hyprland, niri, KDE Plasma")),
    ("kv",   ("Terminal", "kitty, alacritty, ghostty")),
    ("kv",   ("Editor",   "Neovim (LazyVim), Vim, VSCode")),
    ("gap",  ""),
    ("kv",   ("Code",     "C, C++, Python, Go, Lua, Bash")),
    ("kv",   ("Spoken",   "<to be filled in>")),
    ("gap",  ""),
    ("kv",   ("Hobby.SW", "<to be filled in>")),
    ("kv",   ("Hobby.HW", "STM32, Raspberry Pi")),
    ("gap",  ""),
    ("kv",   ("Field",    "communication, autonomous systems")),
    ("kv",   ("Email",    "alihancaliskan@mail.com")),
    ("kv",   ("Work",     "alihancaliskan@workmail.com")),
    ("gap",  ""),
    ("hdr",  "- GitHub Stats -"),
    ("kv",   ("Repos",    "12 {Contributed: 4} | Stars: 37")),
    ("kv",   ("Commits",  "1,204 | Followers: 18")),
    ("kv",   ("Lines",    "84,213 (121,004++, 36,791--)")),
]

KV = [d for k, d in ROWS if k == "kv"]
KEYW = max(len(k) for k, _ in KV)
DOTSW = KEYW + 2 + 8                                  # key + space + dot run
TEXT_COLS = max([DOTSW + 1 + len(v) for _, v in KV] +
                [len(d) for k, d in ROWS if k == "hdr"] + [34])
ART_COLS = max(len(l) for l in ART)

WIDTH = round(PAD * 2 + (ART_COLS + GAP + TEXT_COLS) * CW)
HEIGHT = round(PAD * 2 + max(len(ART), len(ROWS)) * LH)
TEXT_X = round(PAD + (ART_COLS + GAP) * CW)


def render(theme: str) -> str:
    c = THEMES[theme]
    o = ['<?xml version="1.0" encoding="UTF-8"?>',
         f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}px" height="{HEIGHT}px" '
         f'font-family="ConsolasFallback,Consolas,\'DejaVu Sans Mono\',monospace" font-size="{FS}px">',
         '<style>',
         "@font-face {src: local('Consolas'); font-family: 'ConsolasFallback';"
         " font-display: swap; size-adjust: 109%;}",
         f'.key{{fill:{c["key"]}}} .val{{fill:{c["val"]}}} .cc{{fill:{c["cc"]}}}',
         f'.add{{fill:{c["add"]}}} .del{{fill:{c["dele"]}}}',
         'text, tspan {white-space: pre;}',
         '</style>',
         f'<rect width="{WIDTH}px" height="{HEIGHT}px" rx="15" fill="{c["bg"]}"/>']

    # xml:space="preserve" as an attribute, not only the CSS `white-space: pre`
    # above: librsvg (and other non-browser renderers) ignore the CSS rule and
    # collapse the leading spaces, which shifts every art line left and wrecks
    # the picture. Browsers honour either one, so both are set.
    y = PAD + FS
    for line in ART:
        o.append(f'<text x="{PAD}" y="{y}" fill="{c["fg"]}" xml:space="preserve">{escape(line)}</text>')
        y += LH

    y = PAD + FS
    for kind, d in ROWS:
        if kind == "hdr":
            o.append(f'<text x="{TEXT_X}" y="{y}" fill="{c["fg"]}" font-weight="bold">{escape(d)}</text>')
        elif kind == "rule":
            o.append(f'<text x="{TEXT_X}" y="{y}" class="cc">{"-" * TEXT_COLS}</text>')
        elif kind == "kv":
            k, v = d
            dots = "." * (DOTSW - len(k) - 1)
            o.append(f'<text x="{TEXT_X}" y="{y}" fill="{c["fg"]}" xml:space="preserve">'
                     f'<tspan class="key">{escape(k)}</tspan> '
                     f'<tspan class="cc">{dots}</tspan> '
                     f'<tspan class="val">{escape(v)}</tspan></text>')
        y += LH

    o.append('</svg>')
    return "\n".join(o)


for theme, name in (("dark", "dark_mode.svg"), ("light", "light_mode.svg")):
    (HERE / name).write_text(render(theme))
    print(f"  {name}  {WIDTH}x{HEIGHT}px")
print(f"  art {ART_COLS} cols | text {TEXT_COLS} cols | cell {CW:.2f}px")
