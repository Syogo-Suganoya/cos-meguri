"""apple-touch-icon.png を web/icon.svg と同じ絵から起こす。

iOS のホーム画面だけは SVG を受け取らないので、ここだけラスタが要る。
Pillow も cairosvg も入れずに済ませたいので、菱形は式で塗る（標準ライブラリのみ）。
絵を変えたら web/icon.svg と一緒にここも直して、

    docker compose --profile test run --rm test python tools/make_icons.py

で焼き直す。出力はリポジトリに入れる（CI やデプロイで生成しない）。
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "web" / "apple-touch-icon.png"

SIZE = 180
SS = 4  # スーパーサンプリング。菱形の斜辺のギザギザを均す

INK = (0x0B, 0x0B, 0x10)
ACID = (0xD9, 0xFF, 0x00)
MAGENTA = (0xFF, 0x00, 0x60)

# icon.svg と同じ座標系（512）で持ち、描くときに縮める
VIEW = 512.0
CENTER = 256.0
ARM = 140.0  # 印の対角の半分
SHADOW = 24.0  # 版ズレの量
HOLE = 54.0  # 中央に開ける穴


def color_at(x: float, y: float) -> tuple[int, int, int]:
    """512 座標系の1点の色。上に乗るものから順に確かめる。"""
    dx, dy = abs(x - CENTER), abs(y - CENTER)
    if dx + dy <= HOLE:
        return INK
    if dx + dy <= ARM:
        return ACID
    if abs(x - CENTER - SHADOW) + abs(y - CENTER - SHADOW) <= ARM:
        return MAGENTA
    return INK


def render() -> bytes:
    scale = VIEW / (SIZE * SS)
    rows = bytearray()
    for py in range(SIZE):
        rows.append(0)  # PNG のフィルタ種別（なし）
        for px in range(SIZE):
            r = g = b = 0
            for sy in range(SS):
                for sx in range(SS):
                    c = color_at((px * SS + sx + 0.5) * scale, (py * SS + sy + 0.5) * scale)
                    r += c[0]
                    g += c[1]
                    b += c[2]
            n = SS * SS
            rows += bytes((r // n, g // n, b // n))
    return bytes(rows)


def chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))


def main() -> None:
    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0)  # 8bit RGB
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(render(), 9))
        + chunk(b"IEND", b"")
    )
    OUT.write_bytes(png)
    print(f"{OUT} ({len(png)} bytes)")


if __name__ == "__main__":
    main()
