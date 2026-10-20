# SPDX-License-Identifier: EUPL-1.2
"""App logo for the launchers (Windows .ico, macOS .icns, Linux .png).

The logo is drawn without extra packages: indigo square with a trend line that fans out into
a cone (the spread of the forecast) and a mint dot where the forecast starts.
"""

from __future__ import annotations

import functools
import math
import struct
import zlib
from pathlib import Path

INDIGO = (91, 91, 240)
WHITE = (255, 255, 255)
MINT = (23, 195, 160)
CONE_ALPHA = 0.32
SIZE = 256

_START = (0.47, 0.58)  # where the forecast begins
_TREND_FROM = (0.14, 0.72)
_CONE = ((0.47, 0.58), (0.86, 0.2), (0.86, 0.83))


def _inside_rounded(x: float, y: float, size: float, radius: float) -> bool:
    cx = min(max(x, radius), size - radius)
    cy = min(max(y, radius), size - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius**2


def _near_segment(u: float, v: float, a: tuple[float, float], b: tuple[float, float], w: float):
    """Whether (u, v) is within distance ``w`` of the segment a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((u - a[0]) * dx + (v - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(u - (a[0] + t * dx), v - (a[1] + t * dy)) <= w


def _in_triangle(u: float, v: float, tri: tuple[tuple[float, float], ...]) -> bool:
    signs = []
    for i in range(3):
        (x1, y1), (x2, y2) = tri[i], tri[(i + 1) % 3]
        signs.append((x2 - x1) * (v - y1) - (y2 - y1) * (u - x1) >= 0)
    return all(signs) or not any(signs)


def _color(x: float, y: float, s: float) -> tuple[int, int, int, int]:
    """Color (RGBA) at point (x, y) in an image with edge length s."""
    if not _inside_rounded(x, y, s, s * 0.2):
        return 0, 0, 0, 0
    u, v = x / s, y / s
    if math.hypot(u - _START[0], v - _START[1]) <= 0.065:
        return (*MINT, 255)
    for step in (1, 2, 3):  # dotted median of the cone
        cx = _START[0] + step * 0.11
        cy = _START[1] + (0.515 - _START[1]) * step / 3.5
        if math.hypot(u - cx, v - cy) <= 0.03:
            return (*MINT, 255)
    if _near_segment(u, v, _TREND_FROM, _START, 0.028):
        return (*WHITE, 255)
    if _in_triangle(u, v, _CONE):
        mixed = tuple(
            round(w * CONE_ALPHA + b * (1 - CONE_ALPHA)) for w, b in zip(WHITE, INDIGO, strict=True)
        )
        return (*mixed, 255)
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
