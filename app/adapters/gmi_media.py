"""GMI Cloud 実装（設計書 §11）。

画像・動画・音声のどれも同じリクエストキューに投げ、request_id をポーリングして
`outcome.media_urls` を受け取る。だから HTTP の面倒はこのモジュール1つに閉じ、
3つのポートはモデルIDとペイロードの違いだけになる。

モデルIDは提供側の表記ゆれ（大文字小文字）があるため定数に集約し、環境変数でも
上書きできるようにしている。生成は数十秒かかることがあるので、待ち時間の上限を
超えたら諦めて None を返す（生成物は遠征プランの成立条件ではない）。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta

import httpx

from app.domain.models import Lang, MediaAsset, MediaKind, utcnow
from app.ports.media import ImagePort, SpeechPort, VideoPort

logger = logging.getLogger(__name__)

BASE_URL = "https://console.gmicloud.ai/api/v1/ie/requestqueue/apikey"
SUBMIT_PATH = "/requests"
STATUS_PATH = "/requests/{request_id}"

# 既定のモデル。console の表記に合わせて上書きできる
DEFAULT_IMAGE_MODEL = "seedream-5-0-pro"
DEFAULT_VIDEO_MODEL = "Kling-Image2Video-V2.1-Pro"
DEFAULT_SPEECH_MODEL = "minimax-tts-speech-2.8-hd"

# 言語ごとの声。ボイスクローンは使わず、提供元の既製ボイスから選ぶ（設計書 §11）
VOICE_BY_LANG = {
    "ja": "Japanese_calm_narrator",
    "en": "English_expressive_narrator",
    "zh": "Chinese_calm_narrator",
    "ko": "Korean_calm_narrator",
}

MEDIA_TTL_HOURS = 24
POLL_INTERVAL_SECONDS = 2.0
DONE_STATUSES = {"success", "succeeded", "completed", "done"}
FAILED_STATUSES = {"failed", "error", "cancelled", "canceled"}


class GmiClient:
    """リクエストキューへの投入とポーリング。3つのポートで共有する。"""

    def __init__(self, api_key: str, *, timeout: float = 30.0, max_wait: float = 120.0) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.max_wait = max_wait

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def run(self, model: str, payload: dict) -> list[str]:
        """生成を投げて、完了したら media_urls を返す。失敗・時間切れは空配列。"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout, base_url=BASE_URL) as client:
                res = await client.post(
                    SUBMIT_PATH,
                    headers=self._headers(),
                    json={"model": model, "payload": payload},
                )
                res.raise_for_status()
                submitted = res.json()
                request_id = submitted.get("request_id") or submitted.get("id")
                if not request_id:
                    logger.warning("gmi: request_id が無い応答 (%s)", model)
                    return []
                return await self._poll(client, request_id, model)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("gmi submit failed (%s): %s", model, exc)
            return []

    async def _poll(self, client: httpx.AsyncClient, request_id: str, model: str) -> list[str]:
        waited = 0.0
        while waited < self.max_wait:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            waited += POLL_INTERVAL_SECONDS
            try:
                res = await client.get(
                    STATUS_PATH.format(request_id=request_id), headers=self._headers()
                )
                res.raise_for_status()
                body = res.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("gmi poll failed (%s): %s", model, exc)
                return []

            status = str(body.get("status", "")).lower()
            if status in FAILED_STATUSES:
                logger.warning("gmi generation failed (%s): %s", model, body.get("error"))
                return []
            if status in DONE_STATUSES:
                return _media_urls(body)

        logger.warning("gmi generation timed out (%s) after %ss", model, self.max_wait)
        return []


def _media_urls(body: dict) -> list[str]:
    outcome = body.get("outcome") or body.get("result") or {}
    items = outcome.get("media_urls") or []
    urls = [item.get("url") for item in items if isinstance(item, dict) and item.get("url")]
    return [str(u) for u in urls]


def _expiry():
    return utcnow() + timedelta(hours=MEDIA_TTL_HOURS)


class GmiImage(ImagePort):
    name = "image:gmi"

    def __init__(self, client: GmiClient, model: str = DEFAULT_IMAGE_MODEL) -> None:
        self.client = client
        self.model = model

    async def generate_look(self, prompt: str, *, lang: Lang = Lang.JA) -> MediaAsset | None:
        urls = await self.client.run(
            self.model,
            {
                "prompt": prompt,
                # 権利物の混入と実在人物の再現を、生成側でも抑える
                "negative_prompt": "logo, watermark of a brand, official artwork, real person, text",
                "size": "1024x1536",
            },
        )
        if not urls:
            return None
        return MediaAsset(
            media_id=f"med_{uuid.uuid4().hex[:8]}",
            kind=MediaKind.LOOK_IMAGE,
            url=urls[0],
            mime_type="image/png",
            lang=lang,
            provider=self.name,
            expires_at=_expiry(),
        )


class GmiVideo(VideoPort):
    name = "video:gmi"

    def __init__(self, client: GmiClient, model: str = DEFAULT_VIDEO_MODEL) -> None:
        self.client = client
        self.model = model

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
        urls = await self.client.run(
            self.model,
            {
                # image-to-video は起点の1枚を取る。複数枚の編集は今後の課題
                "image": image_urls[0],
                "prompt": prompt,
                "duration": "10" if seconds > 5 else "5",
                "negative_prompt": "blurry, distorted, logo, text",
            },
        )
        if not urls:
            return None
        return MediaAsset(
            media_id=f"med_{uuid.uuid4().hex[:8]}",
            kind=MediaKind.AFTER_MOVIE,
            url=urls[0],
            mime_type="video/mp4",
            lang=lang,
            seconds=float(seconds),
            provider=self.name,
            expires_at=_expiry(),
        )


class GmiSpeech(SpeechPort):
    name = "speech:gmi"

    def __init__(self, client: GmiClient, model: str = DEFAULT_SPEECH_MODEL) -> None:
        self.client = client
        self.model = model

    async def synthesize(self, text: str, *, lang: Lang = Lang.JA) -> MediaAsset | None:
        if not text.strip():
            return None
        urls = await self.client.run(
            self.model,
            {
                "text": text[:4000],
                # 既製ボイスのIDのみ。参照音声は渡さない（ボイスクローン不使用）
                "voice_id": VOICE_BY_LANG.get(lang.value, VOICE_BY_LANG["en"]),
                "language_boost": lang.value,
                "format": "mp3",
            },
        )
        if not urls:
            return None
        return MediaAsset(
            media_id=f"med_{uuid.uuid4().hex[:8]}",
            kind=MediaKind.VOICE_GUIDE,
            url=urls[0],
            mime_type="audio/mpeg",
            lang=lang,
            provider=self.name,
            expires_at=_expiry(),
        )
