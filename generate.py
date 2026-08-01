#!/usr/bin/env python3
"""Build dark_mode.svg / light_mode.svg for the profile README.

Static rows come from PROFILE below. The "GitHub Stats" block is fetched live:
repository, star and follower counts through GraphQL, all-time commits by
walking contributionsCollection year by year, and lines of code through the
REST contributor-stats endpoint.

Needs ACCESS_TOKEN in the environment (a repo secret in CI). Without it the
static half still renders and the stats rows are dropped, so a token problem
degrades the card instead of breaking the build.

Layout notes
------------
The card is pure monospace text, so every position derives from one character
cell. To keep that cell identical everywhere, the @font-face pulls Consolas in
at 109%: Consolas advances 0.55em per character, the usual Linux/Mac fallback
(DejaVu Sans Mono) advances 0.602em, and 0.55 * 1.09 = 0.5995. Without it the
dotted columns drift by ~10% between platforms.

Card width is computed from the content, so a long value widens the card
instead of overflowing it.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).parent
USER = "alihancaliskanx"
TOKEN = os.environ.get("ACCESS_TOKEN", "")
CACHE = HERE / "cache" / "loc.json"

# ── static rows ──────────────────────────────────────────────────────────────
HEADER = "alihan@caliskan"
PROFILE = [
    ("OS",        "CachyOS (Arch Linux), Windows 11"),
    ("Kernel",    "Linux 7.1.4-cachyos"),
    ("Host",      "Kocaeli University"),
    ("Shell",     "zsh, fish"),
    ("WM",        "Hyprland, niri, KDE Plasma"),
    ("Terminal",  "kitty, alacritty, ghostty"),
    ("Editor",    "Neovim (LazyVim), Vim, VSCode"),
    (),
    ("Code",      "C, C++, Python, Go, Lua, Bash"),
    ("Spoken",    "Turkish, English"),
    (),
    ("Team",      "AURA Team"),
    ("Field",     "communication, autonomous system design"),
    ("Hobby.SW",  "autonomous systems, dotfiles"),
    ("Hobby.HW",  "STM32, Raspberry Pi"),
    (),
    ("Email",     "alihancaliskan@mail.com"),
    ("Work",      "alihancaliskan@workmail.com"),
    ("LinkedIn",  "alihan-caliskan"),
    ("X",         "AlihanCaliskanx"),
    ("Discord",   "370240411395948546"),
]

# ── rendering constants ──────────────────────────────────────────────────────
FS, LH, PAD, GAP = 16, 20, 26, 4
CW = FS * 0.602

THEMES = {
    "dark":  dict(bg="#161b22", fg="#c9d1d9", key="#ffa657",
                  val="#a5d6ff", cc="#616e7f", add="#3fb950", dele="#f85149"),
    "light": dict(bg="#f6f8fa", fg="#24292f", key="#953800",
                  val="#0a3069", cc="#c2cfde", add="#1a7f37", dele="#cf222e"),
}


# ── GitHub API ───────────────────────────────────────────────────────────────
def _request(url: str, data: dict | None = None, retries: int = 4):
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method="POST" if data else "GET")
    req.add_header("Authorization", f"bearer {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", f"{USER}-profile-card")
    if body:
        req.add_header("Content-Type", "application/json")

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                # The contributor-stats endpoint answers 202 while GitHub builds
                # the numbers; the correct response is to wait and ask again.
                if r.status == 202:
                    time.sleep(3 * (attempt + 1))
                    continue
                raw = r.read().decode()
                # An empty repository gets 204 No Content with an empty body,
                # which is a success status, so it never raises HTTPError and
                # json.loads("") blows up instead. Treat it as "no data".
                if not raw.strip():
                    return None
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code in (403, 502, 503) and attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise
    return None


def graphql(query: str, **variables):
    out = _request("https://api.github.com/graphql",
                   {"query": query, "variables": variables})
    if out and "errors" in out:
        raise RuntimeError(out["errors"])
    return out["data"] if out else None


def fetch_basics():
    q = """
    query($login: String!) {
      user(login: $login) {
        createdAt
        followers { totalCount }
        repositoriesContributedTo(
          contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY]
          first: 1
        ) { totalCount }
        repositories(first: 100, ownerAffiliations: OWNER, isFork: false,
                     orderBy: {field: PUSHED_AT, direction: DESC}) {
          totalCount
          nodes { name stargazerCount pushedAt isPrivate }
        }
      }
    }"""
    return graphql(q, login=USER)["user"]


def fetch_commits(created_at: str) -> int:
    """All-time commits: contributionsCollection only covers one year per call,
    so walk from the account's first year to now."""
    q = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          restrictedContributionsCount
        }
      }
    }"""
    start = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    total = 0
    for year in range(start.year, now.year + 1):
        frm = max(start, datetime(year, 1, 1, tzinfo=timezone.utc))
        to = min(now, datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc))
        if frm >= to:
            continue
        c = graphql(q, login=USER,
                    **{"from": frm.isoformat(), "to": to.isoformat()})
        cc = c["user"]["contributionsCollection"]
        total += cc["totalCommitContributions"] + cc["restrictedContributionsCount"]
    return total


def fetch_loc(repos) -> tuple[int, int]:
    """Additions/deletions authored by USER, summed over own repos.

    Cached per repo and keyed on pushedAt: an untouched repo is never fetched
    twice, which keeps this well inside the rate limit as the repo count grows.
    """
    cache = {}
    if CACHE.exists():
        try:
            cache = json.loads(CACHE.read_text())
        except json.JSONDecodeError:
            cache = {}

    add = dele = 0
    for repo in repos:
        name, pushed = repo["name"], repo["pushedAt"]
        hit = cache.get(name)
        if hit and hit.get("pushedAt") == pushed:
            add += hit["add"]
            dele += hit["del"]
            continue
        try:
            stats = _request(
                f"https://api.github.com/repos/{USER}/{name}/stats/contributors")
        except (urllib.error.HTTPError, json.JSONDecodeError) as e:
            print(f"  ! {name}: {e}, skipped", file=sys.stderr)
            continue
        if not stats:
            # Empty repo (204) or stats still being computed after the retries.
            print(f"  ! {name}: no contributor stats, skipped", file=sys.stderr)
            cache[name] = {"pushedAt": pushed, "add": 0, "del": 0}
            continue
        ra = rd = 0
        for contributor in stats:
            if (contributor.get("author") or {}).get("login") != USER:
                continue
            for week in contributor["weeks"]:
                ra += week["a"]
                rd += week["d"]
        cache[name] = {"pushedAt": pushed, "add": ra, "del": rd}
        add += ra
        dele += rd

    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))
    return add, dele


def human_age(created_at: str) -> str:
    start = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    years = now.year - start.year
    months = now.month - start.month
    days = now.day - start.day
    if days < 0:
        months -= 1
        days += 30
    if months < 0:
        years -= 1
        months += 12
    parts = [(years, "year"), (months, "month"), (days, "day")]
    return ", ".join(f"{n} {w}{'s' if n != 1 else ''}" for n, w in parts if n)


# ── build the row list ───────────────────────────────────────────────────────
def build_rows():
    rows = [("hdr", HEADER), ("rule", "")]
    stats = None

    if TOKEN:
        try:
            u = fetch_basics()
            repos = u["repositories"]["nodes"]
            add, dele = fetch_loc(repos)
            stats = dict(
                uptime=human_age(u["createdAt"]),
                repos=u["repositories"]["totalCount"],
                contributed=u["repositoriesContributedTo"]["totalCount"],
                stars=sum(r["stargazerCount"] for r in repos),
                followers=u["followers"]["totalCount"],
                commits=fetch_commits(u["createdAt"]),
                add=add, dele=dele,
            )
        except Exception as e:                      # noqa: BLE001
            # Locally a failed fetch should still give you a card to look at.
            # In CI it must not: a swallowed error there publishes half a card
            # and the run still goes green.
            if os.environ.get("GITHUB_ACTIONS"):
                import traceback
                print(f"::error::stats fetch failed: {type(e).__name__}: {e}")
                traceback.print_exc()
                raise
            print(f"  ! stats unavailable: {e}", file=sys.stderr)
    else:
        print("  ! ACCESS_TOKEN not set, rendering without stats", file=sys.stderr)

    if stats:
        rows.append(("kv", ("Uptime", stats["uptime"])))

    for row in PROFILE:
        rows.append(("gap", "") if not row else ("kv", row))

    if stats:
        rows += [
            ("gap", ""),
            ("hdr", "- GitHub Stats -"),
            ("kv", ("Repos", f"{stats['repos']:,} "
                             f"{{Contributed: {stats['contributed']:,}}}")),
            ("kv", ("Stars", f"{stats['stars']:,} | Followers: "
                             f"{stats['followers']:,}")),
            ("kv", ("Commits", f"{stats['commits']:,}")),
            ("kv", ("Lines", ("LOC", stats["add"], stats["dele"]))),
        ]
    return rows


# ── SVG ──────────────────────────────────────────────────────────────────────
def render(rows, art, theme: str) -> str:
    c = THEMES[theme]
    kv = [d for k, d in rows if k == "kv"]
    keyw = max(len(k) for k, _ in kv)
    dotsw = keyw + 2 + 8

    def plain(v):
        if isinstance(v, tuple):
            _, a, d = v
            return f"{a - d:,} ({a:,}++, {d:,}--)"
        return v

    text_cols = max([dotsw + 1 + len(plain(v)) for _, v in kv] +
                    [len(d) for k, d in rows if k == "hdr"] + [34])
    art_cols = max(len(l) for l in art)

    width = round(PAD * 2 + (art_cols + GAP + text_cols) * CW)
    height = round(PAD * 2 + max(len(art), len(rows)) * LH)
    text_x = round(PAD + (art_cols + GAP) * CW)

    o = ['<?xml version="1.0" encoding="UTF-8"?>',
         f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}px" '
         f'height="{height}px" font-family="ConsolasFallback,Consolas,'
         f'\'DejaVu Sans Mono\',monospace" font-size="{FS}px">',
         '<style>',
         "@font-face {src: local('Consolas'); font-family: 'ConsolasFallback';"
         " font-display: swap; size-adjust: 109%;}",
         f'.key{{fill:{c["key"]}}} .val{{fill:{c["val"]}}} .cc{{fill:{c["cc"]}}}',
         f'.add{{fill:{c["add"]}}} .del{{fill:{c["dele"]}}}',
         'text, tspan {white-space: pre;}',
         '</style>',
         f'<rect width="{width}px" height="{height}px" rx="15" fill="{c["bg"]}"/>']

    # xml:space as an attribute, not only the CSS above: non-browser renderers
    # ignore `white-space: pre` and collapse the leading spaces, which shifts
    # every art line left and wrecks the picture.
    y = PAD + FS
    for line in art:
        o.append(f'<text x="{PAD}" y="{y}" fill="{c["fg"]}" '
                 f'xml:space="preserve">{escape(line)}</text>')
        y += LH

    y = PAD + FS
    for kind, d in rows:
        if kind == "hdr":
            o.append(f'<text x="{text_x}" y="{y}" fill="{c["fg"]}" '
                     f'font-weight="bold">{escape(d)}</text>')
        elif kind == "rule":
            o.append(f'<text x="{text_x}" y="{y}" class="cc">{"-" * text_cols}</text>')
        elif kind == "kv":
            k, v = d
            dots = "." * (dotsw - len(k) - 1)
            if isinstance(v, tuple):
                _, a, dl = v
                val = (f'<tspan class="val">{a - dl:,}</tspan> '
                       f'<tspan class="cc">(</tspan>'
                       f'<tspan class="add">{a:,}++</tspan>'
                       f'<tspan class="cc">, </tspan>'
                       f'<tspan class="del">{dl:,}--</tspan>'
                       f'<tspan class="cc">)</tspan>')
            else:
                val = f'<tspan class="val">{escape(v)}</tspan>'
            o.append(f'<text x="{text_x}" y="{y}" fill="{c["fg"]}" xml:space="preserve">'
                     f'<tspan class="key">{escape(k)}</tspan> '
                     f'<tspan class="cc">{dots}</tspan> {val}</text>')
        y += LH

    o.append('</svg>')
    return "\n".join(o)


def main():
    art = (HERE / "ascii-art.txt").read_text().rstrip("\n").split("\n")
    rows = build_rows()
    for theme, name in (("dark", "dark_mode.svg"), ("light", "light_mode.svg")):
        (HERE / name).write_text(render(rows, art, theme))
        print(f"  wrote {name}")


if __name__ == "__main__":
    main()
