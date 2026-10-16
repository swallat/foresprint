# SPDX-License-Identifier: EUPL-1.2
"""Logo der App für die Starter (Windows .ico, macOS .icns, Linux .png).

Das Logo wird ohne Zusatzpakete gezeichnet: blaues Quadrat mit Balken und einem Punkt
auf dem höchsten Balken (Velocity-Verlauf).
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

BLUE = (42, 120, 214)
WHITE = (255, 255, 255)
ORANGE = (235, 104, 52)
SIZE = 256


def _inside_rounded(x: float, y: float, size: float, radius: float) -> bool:
    cx = min(max(x, radius), size - radius)
    cy = min(max(y, radius), size - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius**2


def _color(x: float, y: float, s: float) -> tuple[int, int, int, int]:
    """Farbe (RGBA) am Punkt (x, y) in einem Bild der Kantenlänge s."""
    if not _inside_rounded(x, y, s, s * 0.2):
        return 0, 0, 0, 0
    u, v = x / s, y / s
    for left, top in ((0.2, 0.55), (0.42, 0.4), (0.64, 0.22)):
        if left <= u <= left + 0.16 and top <= v <= 0.8:
            return (*WHITE, 255)
    if (u - 0.72) ** 2 + (v - 0.17) ** 2 <= 0.07**2:
        return (*ORANGE, 255)
    return (*BLUE, 255)


def png(size: int = SIZE) -> bytes:
    """Das Logo als PNG (RGBA, 2×2-Überabtastung für glatte Kanten)."""
    rows = bytearray()
    offsets = (0.25, 0.75)
    for py in range(size):
        rows.append(0)  # Filter „none“
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
    """Windows-Symbol mit einem 256×256-PNG (seit Windows Vista erlaubt)."""
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(image), 22)
    return struct.pack("<HHH", 0, 1, 1) + entry + image


def icns(image: bytes) -> bytes:
    """macOS-Symbol mit einem 256×256-PNG (Typ ic08)."""
    chunk = b"ic08" + struct.pack(">I", len(image) + 8) + image
    return b"icns" + struct.pack(">I", len(chunk) + 8) + chunk


def write_icon(folder: Path, kind: str) -> Path:
    """Schreibt das Logo als ``png``, ``ico`` oder ``icns`` in ``folder``; liefert den Pfad."""
    folder.mkdir(parents=True, exist_ok=True)
    image = png()
    path = folder / f"sprintforecast.{kind}"
    path.write_bytes({"png": image, "ico": ico(image), "icns": icns(image)}[kind])
    return path
