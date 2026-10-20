# SPDX-License-Identifier: EUPL-1.2
"""App logo for the launchers (Windows .ico, macOS .icns, Linux .png).

The logo is drawn without extra packages: an indigo square with a violet diagonal and a
timeline of sprints: two solid blocks, then a dashed mint block for the forecast.
"""

from __future__ import annotations

import functools
import struct
import zlib
from pathlib import Path

INDIGO = (91, 91, 240)
VIOLET = (162, 77, 240)
WHITE = (255, 255, 255)
MINT = (23, 195, 160)
SIZE = 256
BAND = tuple(round(v * 0.85 + i * 0.15) for v, i in zip(VIOLET, INDIGO, strict=True))

# Geometry on a 64 x 64 grid.
_DONE = ((6, 24, 20, 40), (23, 24, 37, 40))  # finished sprints
_NEXT = (40, 24, 54, 40)  # forecast sprint (dashed outline)
_STUB = (54, 30.5, 60, 33.5)
_BLOCK_RADIUS = 3
_OUTLINE = 2.5
_DASH, _GAP = 4, 2  # dash pattern along the outline (60 units long, closes evenly)
_PHASE = 4  # centers a dash on the right side, where the stub meets it


def _inside_rounded(x: float, y: float, size: float, radius: float) -> bool:
    cx = min(max(x, radius), size - radius)
    cy = min(max(y, radius), size - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius**2


def _in_block(g: float, h: float, box: tuple[float, float, float, float], inset: float = 0) -> bool:
    x0, y0, x1, y1 = box[0] + inset, box[1] + inset, box[2] - inset, box[3] - inset
    if not (x0 <= g <= x1 and y0 <= h <= y1):
        return False
    r = max(_BLOCK_RADIUS - inset, 0)
    cx, cy = min(max(g, x0 + r), x1 - r), min(max(h, y0 + r), y1 - r)
    return (g - cx) ** 2 + (h - cy) ** 2 <= r**2


def _along_outline(g: float, h: float, box: tuple[float, float, float, float]) -> float:
    """Distance along the outline of ``box`` (clockwise from the top left) of the point nearest
    to (g, h)."""
    x0, y0, x1, y1 = box
    w, ht = x1 - x0, y1 - y0
    near = {"top": h - y0, "right": x1 - g, "bottom": y1 - h, "left": g - x0}
    side = min(near, key=lambda k: near[k])
    return {
        "top": g - x0,
        "right": w + (h - y0),
        "bottom": w + ht + (x1 - g),
        "left": 2 * w + ht + (y1 - h),
    }[side]


def _color(x: float, y: float, s: float) -> tuple[int, int, int, int]:
    """Color (RGBA) at point (x, y) in an image with edge length s."""
    if not _inside_rounded(x, y, s, s * 0.2):
        return 0, 0, 0, 0
    g, h = x / s * 64, y / s * 64
    if any(_in_block(g, h, box) for box in _DONE):
        return (*WHITE, 255)
    on_outline = _in_block(g, h, _NEXT) and not _in_block(g, h, _NEXT, _OUTLINE)
    if on_outline and (_along_outline(g, h, _NEXT) + _PHASE) % (_DASH + _GAP) < _DASH:
        return (*MINT, 255)
    if _STUB[0] <= g <= _STUB[2] and _STUB[1] <= h <= _STUB[3]:
        return (*MINT, 255)
    if g + h >= 74:  # diagonal band in the lower right corner
        return (*BAND, 255)
    return (*INDIGO, 255)


@functools.cache
def png(size: int = SIZE) -> bytes:
    """The logo as PNG (RGBA, 2×2 supersampling for smooth edges)."""
    rows = bytearray()
    offsets = (0.25, 0.75)
    for py in range(size):
        rows.append(0)  # filter "none"
        for px in range(size):
            acc = [0, 0, 0, 0]
            for oy in offsets:
                for ox in offsets:
                    r, g, b, a = _color(px + ox, py + oy, size)
                    acc[0] += r * a
                    acc[1] += g * a
                    acc[2] += b * a
                    acc[3] += a
            alpha = acc[3]
            if alpha:
                rows += bytes((acc[0] // alpha, acc[1] // alpha, acc[2] // alpha, alpha // 4))
            else:
                rows += bytes(4)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


def ico(image: bytes) -> bytes:
    """Windows icon with a 256×256 PNG (allowed since Windows Vista)."""
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(image), 22)
    return struct.pack("<HHH", 0, 1, 1) + entry + image


def icns(image: bytes) -> bytes:
    """macOS icon with a 256×256 PNG (type ic08)."""
    chunk = b"ic08" + struct.pack(">I", len(image) + 8) + image
    return b"icns" + struct.pack(">I", len(chunk) + 8) + chunk


def write_icon(folder: Path, kind: str) -> Path:
    """Write the logo as ``png``, ``ico`` or ``icns`` into ``folder``; return the path."""
    folder.mkdir(parents=True, exist_ok=True)
    image = png()
    path = folder / f"sprintforecast.{kind}"
    path.write_bytes({"png": image, "ico": ico(image), "icns": icns(image)}[kind])
    return path
