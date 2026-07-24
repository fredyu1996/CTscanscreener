#!/usr/bin/env python3
"""Render a frame's annotations as a self-contained SVG.

Two modes, chosen automatically:

  overlay    the frame's image exists on disk — it is embedded and the markers
             are drawn on top of the real pixels.
  schematic  the image is not in the repo (screenshots that arrived as chat
             attachments never touch disk). A stylised axial chest is drawn
             instead, with the markers at the same fractional coordinates and a
             banner saying so. Useful as a search guide; it is not the scan.

Marker kinds carry meaning and are drawn differently: 'confirmed' is a solid
circle, 'candidate' is dashed, 'search_zone' is a soft translucent patch.

Standard library only.
"""

from __future__ import annotations

import base64
import html
import mimetypes
from pathlib import Path

KIND_STYLE = {
    "confirmed": {"stroke": "#e8483f", "dash": "none", "fill": "none", "opacity": "1"},
    "candidate": {"stroke": "#f0a202", "dash": "7 5", "fill": "none", "opacity": "1"},
    "search_zone": {"stroke": "#3d8bd4", "dash": "3 4", "fill": "#3d8bd4", "opacity": "0.13"},
}
KIND_LEGEND = {
    "confirmed": "confirmed — this is the finding",
    "candidate": "candidate — one of several possibilities",
    "search_zone": "search zone — look here, no claim about what is there",
}

CANVAS = 900          # SVG viewport is square; images are letterboxed into it
MARGIN_TOP = 62       # room for the title bar
LEGEND_ROW = 26


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _schematic_chest(x: float, y: float, w: float, h: float) -> str:
    """A stylised axial thorax, drawn to fill the given box."""
    def px(fx: float) -> float: return x + fx * w
    def py(fy: float) -> float: return y + fy * h
    return f"""
  <ellipse cx="{px(0.5):.1f}" cy="{py(0.52):.1f}" rx="{0.44 * w:.1f}" ry="{0.34 * h:.1f}"
           fill="#d9d5cf" stroke="#a9a49c" stroke-width="2"/>
  <ellipse cx="{px(0.31):.1f}" cy="{py(0.50):.1f}" rx="{0.155 * w:.1f}" ry="{0.235 * h:.1f}"
           fill="#4a4a4a" stroke="#6f6f6f" stroke-width="1.5"/>
  <ellipse cx="{px(0.69):.1f}" cy="{py(0.50):.1f}" rx="{0.155 * w:.1f}" ry="{0.235 * h:.1f}"
           fill="#4a4a4a" stroke="#6f6f6f" stroke-width="1.5"/>
  <ellipse cx="{px(0.5):.1f}" cy="{py(0.50):.1f}" rx="{0.085 * w:.1f}" ry="{0.20 * h:.1f}"
           fill="#cfcac3" stroke="#a9a49c" stroke-width="1.5"/>
  <circle cx="{px(0.5):.1f}" cy="{py(0.72):.1f}" r="{0.048 * w:.1f}"
          fill="#eae6e0" stroke="#a9a49c" stroke-width="1.5"/>
  <rect x="{px(0.455):.1f}" y="{py(0.175):.1f}" width="{0.09 * w:.1f}" height="{0.022 * h:.1f}"
        rx="3" fill="#eae6e0" stroke="#a9a49c" stroke-width="1.5"/>
  <text x="{px(0.31):.1f}" y="{py(0.845):.1f}" text-anchor="middle"
        font-size="15" fill="#8d8880">RIGHT lung</text>
  <text x="{px(0.69):.1f}" y="{py(0.845):.1f}" text-anchor="middle"
        font-size="15" fill="#8d8880">LEFT lung</text>
  <text x="{px(0.5):.1f}" y="{py(0.125):.1f}" text-anchor="middle"
        font-size="13" fill="#8d8880">anterior</text>
  <text x="{px(0.5):.1f}" y="{py(0.925):.1f}" text-anchor="middle"
        font-size="13" fill="#8d8880">posterior</text>"""


def render_frame(frame: dict, case_id: str, root: Path, title_extra: str = "") -> str:
    """Build the SVG document for one frame."""
    annotations = frame.get("annotations", [])
    image = frame.get("image")
    image_path = (root / image) if image else None
    have_image = bool(image_path and image_path.exists())

    kinds_used = []
    for a in annotations:
        k = a.get("kind") or "confirmed"
        if k not in kinds_used:
            kinds_used.append(k)
    legend_h = LEGEND_ROW * (len(kinds_used) + (0 if have_image else 1)) + 14
    box = CANVAS - MARGIN_TOP - legend_h
    ox, oy = (CANVAS - box) / 2, MARGIN_TOP

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS}" height="{CANVAS}" '
        f'viewBox="0 0 {CANVAS} {CANVAS}" font-family="-apple-system,BlinkMacSystemFont,'
        f'\'Segoe UI\',Roboto,sans-serif">',
        f'<rect width="{CANVAS}" height="{CANVAS}" fill="#14161a"/>',
        f'<text x="26" y="32" font-size="19" fill="#f0ede8" font-weight="600">'
        f'{html.escape(case_id)} · {html.escape(frame["id"])}</text>',
    ]
    subtitle = html.escape(frame.get("slice_level") or "")
    if title_extra:
        subtitle = (subtitle + "  " + title_extra).strip()
    if subtitle:
        parts.append(f'<text x="26" y="52" font-size="13" fill="#9a978f">'
                     f'{subtitle[:130]}</text>')

    if have_image:
        parts.append(f'<image x="{ox:.1f}" y="{oy:.1f}" width="{box}" height="{box}" '
                     f'preserveAspectRatio="xMidYMid meet" '
                     f'href="{_data_uri(image_path)}"/>')
    else:
        parts.append(_schematic_chest(ox, oy, box, box))

    for a in annotations:
        style = KIND_STYLE[a.get("kind") or "confirmed"]
        cx = ox + a["x"] * box
        cy = oy + a["y"] * box
        r = (a.get("r") or 0.05) * box
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{style["fill"]}" '
            f'fill-opacity="{style["opacity"]}" stroke="{style["stroke"]}" stroke-width="2.5" '
            f'stroke-dasharray="{style["dash"]}"/>')
        # Label outside the circle, flipped to whichever side has room.
        left = cx > CANVAS / 2
        lx = cx - r - 9 if left else cx + r + 9
        parts.append(
            f'<text x="{lx:.1f}" y="{cy + 5:.1f}" font-size="15" font-weight="600" '
            f'fill="{style["stroke"]}" text-anchor="{"end" if left else "start"}" '
            f'paint-order="stroke" stroke="#14161a" stroke-width="4">'
            f'{html.escape(a["label"])}</text>')

    ly = CANVAS - legend_h + 4
    if not have_image:
        parts.append(f'<text x="26" y="{ly}" font-size="14" fill="#d99b7a" font-weight="600">'
                     f'SCHEMATIC — source pixels are not in this repo. Positions are '
                     f'approximate; this is a search guide, not the scan.</text>')
        ly += LEGEND_ROW
    for k in kinds_used:
        style = KIND_STYLE[k]
        parts.append(
            f'<circle cx="34" cy="{ly - 5}" r="8" fill="{style["fill"]}" '
            f'fill-opacity="{style["opacity"]}" stroke="{style["stroke"]}" stroke-width="2.5" '
            f'stroke-dasharray="{style["dash"]}"/>')
        parts.append(f'<text x="52" y="{ly}" font-size="14" fill="#9a978f">'
                     f'{html.escape(KIND_LEGEND[k])}</text>')
        ly += LEGEND_ROW

    parts.append("</svg>")
    return "\n".join(parts)
