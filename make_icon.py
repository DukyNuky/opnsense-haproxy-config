#!/usr/bin/env python3
"""Draw the program icon: icon.png for Linux and icon.ico for Windows.

The mark is one request arriving on the left and being handed to one of three
hosts on the right -- what a reverse proxy does, in the fewest lines that still
read as that at 16 pixels.

Every shape is described by its distance to the nearest edge instead of being
painted. That distance also gives the anti-aliasing for free (a pixel half a
unit inside the edge is half covered), so one sample per pixel is enough and no
imaging library is needed.
"""

import math
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))

SIZE = 256                       # the coordinate system every shape lives in
BACKGROUND = (0x35, 0x63, 0xE9)  # the accent blue of the window
FOREGROUND = (0xFF, 0xFF, 0xFF)

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

STROKE = 7
NODE = (70, 128, 16)                 # the incoming request
TRUNK = (70, 128, 125, 128)          # ... reaching the proxy
SPINE = (125, 70, 125, 186)          # ... which fans out
BRANCHES = [(125, y, 167, y) for y in (70, 128, 186)]
HOSTS = [(185, y, 17, 5) for y in (70, 128, 186)]  # centre, half size, radius


def rounded_box(px, py, cx, cy, half_w, half_h, radius):
    """Distance to a rounded rectangle: negative inside, positive outside."""
    dx = abs(px - cx) - (half_w - radius)
    dy = abs(py - cy) - (half_h - radius)
    return (math.hypot(max(dx, 0.0), max(dy, 0.0))
            + min(max(dx, dy), 0.0) - radius)


def capsule(px, py, ax, ay, bx, by, radius):
    """Distance to a line segment grown by `radius` -- a stroke with round caps."""
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    length = vx * vx + vy * vy
    along = 0.0 if length == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / length))
    return math.hypot(wx - along * vx, wy - along * vy) - radius


def glyph_distance(px, py):
    return min(
        capsule(px, py, NODE[0], NODE[1], NODE[0], NODE[1], NODE[2]),
        capsule(px, py, *TRUNK, STROKE),
        capsule(px, py, *SPINE, STROKE),
        min(capsule(px, py, *branch, STROKE) for branch in BRANCHES),
        min(rounded_box(px, py, cx, cy, half, half, radius)
            for cx, cy, half, radius in HOSTS),
    )


def coverage(distance):
    """How much of a pixel a shape covers, from its distance to the edge."""
    return max(0.0, min(1.0, 0.5 - distance))


def render(size):
    """One RGBA image of the icon, as a list of rows of bytes."""
    step = SIZE / size
    rows = []
    for y in range(size):
        py = (y + 0.5) * step
        row = bytearray()
        for x in range(size):
            px = (x + 0.5) * step
            # everything is scaled to the icon, so a thin stroke stays visible
            alpha = coverage(rounded_box(px, py, 128, 128, 128, 128, 56) / step)
            if alpha <= 0:
                row += b"\0\0\0\0"
                continue
            ink = coverage(glyph_distance(px, py) / step)
            for background, foreground in zip(BACKGROUND, FOREGROUND):
                row.append(round(background + (foreground - background) * ink))
            row.append(round(alpha * 255))
        rows.append(bytes(row))
    return rows


def png(rows):
    """A PNG file for the rendered rows -- RGBA, one filter byte per row."""
    height = len(rows)
    width = len(rows[0]) // 4

    def chunk(kind, payload):
        body = kind + payload
        return (struct.pack(">I", len(payload)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b"".join(b"\0" + row for row in rows)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def ico(images):
    """A Windows icon holding the given (size, png bytes) pairs.

    The entries carry PNG data rather than bitmaps, which Windows has read
    since Vista and which keeps the 256 pixel image from dominating the file.
    """
    offset = 6 + 16 * len(images)
    directory, blobs = [], []
    for size, data in images:
        directory.append(struct.pack("<BBBBHHII",
                                     size if size < 256 else 0,
                                     size if size < 256 else 0,
                                     0, 0, 1, 32, len(data), offset))
        blobs.append(data)
        offset += len(data)
    return (struct.pack("<HHH", 0, 1, len(images))
            + b"".join(directory) + b"".join(blobs))


def build():
    written = []
    images = []
    for size in sorted(set(ICO_SIZES) | {SIZE}):
        images.append((size, png(render(size))))

    master = dict(images)[SIZE]
    for name, data in (("icon.png", master),
                       ("icon.ico", ico([(s, d) for s, d in images
                                         if s in ICO_SIZES]))):
        path = os.path.join(HERE, name)
        with open(path, "wb") as handle:
            handle.write(data)
        written.append(path)
        print(f"{path}  ({len(data)} bytes)")
    return written


if __name__ == "__main__":
    sys.exit(0 if build() else 1)
