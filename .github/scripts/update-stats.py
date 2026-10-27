#!/usr/bin/env python3
"""Draws the container pulls card for the README.

Reads the projects in .github/stats.txt, adds up the pulls of their Docker Hub
and GHCR images and writes stats-light.svg and stats-dark.svg into the folder
given as argument (default: dist).

If a single link cannot be read, nothing is written and the script exits with
an error, so the published card stays as it is and the failed run shows up in
GitHub Actions.
"""

import datetime
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "stats.txt"
REGISTRIES = ("Docker Hub", "GHCR")

# GitHub's own surfaces and text colors; bar colors are a color-blind safe pair
THEMES = {
    "light": dict(bg="#ffffff", border="#d0d7de", text="#1f2328", muted="#59636e",
                  bars=("#2a78d6", "#eb6834")),
    "dark":  dict(bg="#0d1117", border="#3d444d", text="#f0f6fc", muted="#9198a1",
                  bars=("#3987e5", "#d95926")),
}
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (stats-card)"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode()
        except OSError:
            if attempt == 2:
                raise
            time.sleep(5)


# Docker Hub: "pull_count" from the Hub API
def dockerhub(repo):
    return json.loads(get(f"https://hub.docker.com/v2/repositories/{repo}/"))["pull_count"]


# GHCR: "Total downloads" from the package page (GitHub has no API for this number)
def ghcr(url):
    match = re.search(r'Total downloads.{0,300}?title="([0-9,]+)"', get(url), re.S)
    return int(match[1].replace(",", ""))


# (registry, pulls) of one link
def pulls(link):
    path = re.sub(r"^https?://", "", link)
    host, _, ref = path.partition("/")
    image = ref.split(":")[0]
    if host == "hub.docker.com" and ref.startswith("r/"):
        return "Docker Hub", dockerhub("/".join(ref.split("/")[1:3]))
    if host == "docker.io":
        return "Docker Hub", dockerhub(image)
    if host == "github.com" and "/packages/container/" in ref:
        return "GHCR", ghcr(f"https://{path}")
    if host == "ghcr.io":
        user, _, name = image.partition("/")
        return "GHCR", ghcr(f"https://github.com/users/{user}/packages/container/package/{name}")
    raise ValueError("unknown link format")


# {project: [link, ...]} in the order of the config file
def projects():
    result, current = {}, None
    for line in CONFIG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip()
            result[current] = []
        elif current is None:
            sys.exit(f"{CONFIG.name}: link before the first [project]: {line}")
        else:
            result[current].append(line)
    return result


# Rough text width in px for the system sans; errs on the wide side
def width(text, size):
    return len(text) * size * 0.58


# Bar segment growing from the left; only the data end gets rounded
def segment(x, y, w, h, color, rounded):
    if not rounded:
        return f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{h}" fill="{color}"/>'
    r = min(4, w, h / 2)
    return (f'<path d="M{x:.1f},{y}h{w - r:.1f}a{r:.1f},{r:.1f} 0 0 1 {r:.1f},{r:.1f}'
            f'v{h - 2 * r:.1f}a{r:.1f},{r:.1f} 0 0 1 {-r:.1f},{r:.1f}h{r - w:.1f}z" fill="{color}"/>')


def card(counts, theme, updated):
    t = THEMES[theme]
    totals = {name: sum(c.values()) for name, c in counts.items()}
    total = sum(totals.values())
    per_registry = {reg: sum(c.get(reg, 0) for c in counts.values()) for reg in REGISTRIES}

    w, pad, row_h, bar_h, gap = 480, 24, 28, 8, 2
    bar_x = pad + max(96, max(width(n, 14) for n in counts) + 16)
    bar_max = w - pad - max(width(f"{n:,}", 14) for n in totals.values()) - 16 - bar_x
    rows_y = 124
    legend_y = rows_y + len(counts) * row_h + 22
    h = legend_y + 22
    largest = max(totals.values()) or 1

    summary = "; ".join(f"{n} {v:,}" for n, v in totals.items())
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'role="img" aria-labelledby="title" font-family="{FONT}">',
        f'<title id="title">Container image pulls: {total:,} in total ({html.escape(summary)})</title>',
        f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="6" fill="{t["bg"]}" stroke="{t["border"]}"/>',
        f'<text x="{pad}" y="40" font-size="14" fill="{t["muted"]}">Container image pulls</text>',
        f'<text x="{pad - 2}" y="94" font-size="48" font-weight="600" fill="{t["text"]}">{total:,}</text>',
    ]

    for i, (name, c) in enumerate(counts.items()):
        mid = rows_y + i * row_h + row_h / 2
        out.append(f'<text x="{pad}" y="{mid + 5:.1f}" font-size="14" fill="{t["text"]}">{html.escape(name)}</text>')
        out.append(f'<text x="{w - pad}" y="{mid + 5:.1f}" font-size="14" fill="{t["text"]}" text-anchor="end" '
                   f'style="font-variant-numeric:tabular-nums">{totals[name]:,}</text>')

        # Stacked bar scaled to the largest project; segments below 1px are left out
        bar_w = max(2, totals[name] / largest * bar_max) if totals[name] else 0
        parts = [(c.get(reg, 0), color) for reg, color in zip(REGISTRIES, t["bars"])]
        parts = [(n, color) for n, color in parts if totals[name] and n / totals[name] * bar_w >= 1]
        free = bar_w - gap * (len(parts) - 1)
        x, y = bar_x, mid - bar_h / 2
        for j, (n, color) in enumerate(parts):
            seg_w = n / sum(p for p, _ in parts) * free
            out.append(segment(x, y, seg_w, bar_h, color, j == len(parts) - 1))
            x += seg_w + gap

    x = pad
    for reg, color in zip(REGISTRIES, t["bars"]):
        value = f"{per_registry[reg]:,}"
        out.append(f'<rect x="{x}" y="{legend_y - 9}" width="10" height="10" rx="2" fill="{color}"/>')
        out.append(f'<text x="{x + 16}" y="{legend_y}" font-size="13" fill="{t["muted"]}">{reg} '
                   f'<tspan fill="{t["text"]}" font-weight="600">{value}</tspan></text>')
        x += 16 + width(f"{reg} {value}", 13) + 12
    out.append(f'<text x="{w - pad}" y="{legend_y}" font-size="12" fill="{t["muted"]}" text-anchor="end">'
               f'Updated {updated.day} {updated:%b %Y}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main():
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    counts, failed = {}, False

    for name, links in projects().items():
        print(f"{name}:")
        counts[name] = {}
        for link in links:
            try:
                registry, n = pulls(link)
            except Exception as error:
                print(f"  FAILED  {link}  ({error})", file=sys.stderr)
                failed = True
                continue
            print(f"  {n:10d}  {link}")
            counts[name][registry] = counts[name].get(registry, 0) + n

    if failed:
        sys.exit("card not updated")

    out_dir.mkdir(parents=True, exist_ok=True)
    updated = datetime.datetime.now(datetime.timezone.utc)
    for theme in THEMES:
        (out_dir / f"stats-{theme}.svg").write_text(card(counts, theme, updated), encoding="utf-8")
    print(f"= {sum(sum(c.values()) for c in counts.values()):,} -> {out_dir}")


if __name__ == "__main__":
    main()
