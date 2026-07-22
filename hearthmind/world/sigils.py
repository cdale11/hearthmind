"""Vision doc item 4.3, docs/VISION-2026-07-22-LIVINGTERRARIUM.md
("Generative assets bound to emergent entities"): when the world
names a new composite entity (item 4.1), give it a small visual
representation too — parameterized SVG, not a generative model. Fully
deterministic (same name+category always produces the same sigil, no
RNG state, no LLM call): the entity's own name and category are hashed
into a small palette/shape/motif choice, same "cheap, deterministic,
on-brand" path the vision doc itself recommends starting with."""
from __future__ import annotations

import hashlib
import math

_PALETTES: tuple[tuple[str, str], ...] = (
    ("#8a6d3b", "#f4e9d8"),  # earth / parchment
    ("#3b5a8a", "#e8eef8"),  # dusk blue / pale sky
    ("#6d3b5a", "#f8e8ef"),  # rose / faded pink
    ("#3b6d4d", "#e8f4ec"),  # moss / pale green
    ("#8a3b3b", "#f4e0e0"),  # ember / clay
    ("#5a5a3b", "#f0f0e0"),  # dry grass / straw
)
_MOTIFS = ("circle", "triangle", "diamond", "cross", "arc")


def _seed_int(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


def generate_sigil_svg(name: str, category: str, size: int = 64) -> str:
    """A small (~600-900 byte) inline SVG sigil, deterministic from
    `name`+`category` alone — the same composite entity always draws
    the same sigil, and no two differently-named entities collide
    except by genuine hash coincidence. Three motif shapes layered at
    hash-derived rotations/offsets read as "a mark," not a literal
    icon — appropriate for a village-invented symbol, not a photo."""
    seed = _seed_int(f"{name}|{category}")
    fg, bg = _PALETTES[seed % len(_PALETTES)]
    motif = _MOTIFS[(seed >> 8) % len(_MOTIFS)]
    rotation = (seed >> 16) % 360
    cx, cy = size / 2, size / 2
    r = size * 0.32

    if motif == "circle":
        shape = f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="none" stroke="{fg}" stroke-width="3"/>'
    elif motif == "triangle":
        pts = " ".join(
            f"{cx + r * math.cos(math.radians(a)):.1f},{cy + r * math.sin(math.radians(a)):.1f}"
            for a in (90, 210, 330)
        )
        shape = f'<polygon points="{pts}" fill="none" stroke="{fg}" stroke-width="3"/>'
    elif motif == "diamond":
        shape = (
            f'<polygon points="{cx},{cy - r:.1f} {cx + r:.1f},{cy} {cx},{cy + r:.1f} {cx - r:.1f},{cy}" '
            f'fill="none" stroke="{fg}" stroke-width="3"/>'
        )
    elif motif == "cross":
        shape = (
            f'<line x1="{cx - r:.1f}" y1="{cy}" x2="{cx + r:.1f}" y2="{cy}" stroke="{fg}" stroke-width="3"/>'
            f'<line x1="{cx}" y1="{cy - r:.1f}" x2="{cx}" y2="{cy + r:.1f}" stroke="{fg}" stroke-width="3"/>'
        )
    else:  # arc
        shape = f'<path d="M {cx - r:.1f} {cy} A {r:.1f} {r:.1f} 0 0 1 {cx + r:.1f} {cy}" fill="none" stroke="{fg}" stroke-width="3"/>'

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">'
        f'<rect width="{size}" height="{size}" rx="{size * 0.12:.1f}" fill="{bg}"/>'
        f'<g transform="rotate({rotation} {cx} {cy})">{shape}</g>'
        f'<circle cx="{cx}" cy="{cy}" r="{r * 0.18:.1f}" fill="{fg}"/>'
        f'</svg>'
    )
