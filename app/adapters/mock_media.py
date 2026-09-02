"""GMI Cloud の代役。キーが無くても画面まで通せるようにする。

「生成できませんでした」を返すのではなく、**実際に表示・再生できる代替物**を返す。
デモで動線が途切れないこと、UI側の実装（img / audio / video）が検証できることを狙う。
本物の生成結果ではないので is_placeholder=True を立て、UI にもその旨を出す。
"""

from __future__ import annotations

import base64
import hashlib
import math
import struct
import uuid
from datetime import timedelta

from app.domain.models import Lang, MediaAsset, MediaKind, utcnow
from app.ports.media import ImagePort, SpeechPort, VideoPort

# 生成物の参照を保持する時間。設計書 §7-1 の一時画像と同じ扱い
MEDIA_TTL_HOURS = 24

_PALETTE = ["#ff5fa2", "#7c6cff", "#3ecf9a", "#ffb457", "#6cc7ff", "#ff6b6b"]


def _digest(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


def _svg_data_uri(svg: str) -> str:
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _expiry():
    return utcnow() + timedelta(hours=MEDIA_TTL_HOURS)


def _wav_data_uri(seconds: float, hz: int = 440) -> tuple[str, float]:
    """短い WAV を組み立てて data URI で返す。

    再生できる本物の音声にしておくと、UI のプレーヤーまで通しで確認できる。
    合成音声の代役なので内容は単音のフェード。
    """
    rate = 8000
    frames = int(rate * seconds)
    samples = bytearray()
    for i in range(frames):
        # 端をフェードさせて、耳障りなクリック音を出さない
        fade = min(1.0, i / (rate * 0.05), (frames - i) / (rate * 0.05))
        value = int(8000 * fade * math.sin(2 * math.pi * hz * i / rate))
        samples += struct.pack("<h", value)

    data = bytes(samples)
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(data))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", len(data))
    )
    encoded = base64.b64encode(header + data).decode("ascii")
    return f"data:audio/wav;base64,{encoded}", seconds


class MockImage(ImagePort):
    name = "image:mock"

    async def generate_look(self, prompt: str, *, lang: Lang = Lang.JA) -> MediaAsset | None:
        seed = _digest(prompt)
        primary = _PALETTE[seed % len(_PALETTE)]
        secondary = _PALETTE[(seed // 7) % len(_PALETTE)]
        label = "完成イメージ（モック）" if lang is Lang.JA else "Look preview (mock)"
        note = "AI生成" if lang is Lang.JA else "AI-generated"

        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 768">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{primary}"/><stop offset="1" stop-color="{secondary}"/>
  </linearGradient></defs>
  <rect width="512" height="768" fill="#141220"/>
  <circle cx="256" cy="240" r="110" fill="url(#g)" opacity="0.85"/>
  <rect x="146" y="360" width="220" height="300" rx="28" fill="url(#g)" opacity="0.55"/>
  <text x="256" y="700" fill="#ece9f6" font-size="26" text-anchor="middle"
        font-family="sans-serif">{label}</text>
  <text x="256" y="736" fill="#a49ec2" font-size="18" text-anchor="middle"
        font-family="sans-serif">{note}</text>
</svg>"""

        return MediaAsset(
            media_id=f"med_{uuid.uuid4().hex[:8]}",
            kind=MediaKind.LOOK_IMAGE,
            url=_svg_data_uri(svg),
            mime_type="image/svg+xml",
            lang=lang,
            provider=self.name,
            is_placeholder=True,
            expires_at=_expiry(),
        )


class MockVideo(VideoPort):
    name = "video:mock"

    async def generate_after_movie(
        self,
        *,
        image_urls: list[str],
        prompt: str,
        seconds: int = 5,
        lang: Lang = Lang.JA,
    ) -> MediaAsset | None:
        if not image_urls:
            return None

        # 動画そのものは作れないので、構成（何枚をどう繋ぐか）を絵にして返す
        count = len(image_urls)
        label = (
            f"アフタームービー構成案（{count}枚 / {seconds}秒）"
            if lang is Lang.JA
            else f"After-movie storyboard ({count} shots / {seconds}s)"
        )
        note = (
            "モック。本番は Kling Image2Video で生成"
            if lang is Lang.JA
            else "Mock. Generated with Kling Image2Video in production"
        )
        cells = "".join(
            f'<rect x="{40 + i * 150}" y="150" width="130" height="180" rx="14" '
            f'fill="{_PALETTE[(_digest(url) + i) % len(_PALETTE)]}" opacity="0.7"/>'
            for i, url in enumerate(image_urls[:4])
        )
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 480">
  <rect width="640" height="480" fill="#141220"/>
  {cells}
  <text x="320" y="400" fill="#ece9f6" font-size="24" text-anchor="middle"
        font-family="sans-serif">{label}</text>
  <text x="320" y="436" fill="#a49ec2" font-size="17" text-anchor="middle"
        font-family="sans-serif">{note}</text>
</svg>"""

        return MediaAsset(
            media_id=f"med_{uuid.uuid4().hex[:8]}",
            kind=MediaKind.AFTER_MOVIE,
            url=_svg_data_uri(svg),
            mime_type="image/svg+xml",  # 動画ではないので、正直に画像として返す
            lang=lang,
            seconds=float(seconds),
            provider=self.name,
            is_placeholder=True,
            expires_at=_expiry(),
        )


class MockSpeech(SpeechPort):
    name = "speech:mock"

    async def synthesize(self, text: str, *, lang: Lang = Lang.JA) -> MediaAsset | None:
        if not text.strip():
            return None
        # 実際に再生できる音を返す。長さは1秒固定で、読み上げ内容は含まれない
        url, seconds = _wav_data_uri(1.0, hz=520 if lang is Lang.JA else 440)
        return MediaAsset(
            media_id=f"med_{uuid.uuid4().hex[:8]}",
            kind=MediaKind.VOICE_GUIDE,
            url=url,
            mime_type="audio/wav",
            lang=lang,
            seconds=seconds,
            provider=self.name,
            is_placeholder=True,
            expires_at=_expiry(),
        )
