"""YouCam API 実装（Skin Type / Face Attributes / VTO）。

エンドポイントとレスポンスの細部は契約時に確定するため、パス・キー名は
モジュール先頭の定数に集約してある。実 API が応答しない・形が違う場合は
MockVto にフォールバックし、当日デモが止まらないようにする。

設計書 §7-1 の要求どおり、この層でも画像は保持しない:
- ローカルに書かない
- 例外メッセージに載せない
- 呼び出し後に参照を落とす
"""

from __future__ import annotations

import logging

import httpx

from app.adapters.mock_vto import MockVto
from app.domain.models import (
    CharacterRef,
    FaceAttributes,
    FaceProfile,
    FittingCandidate,
    FittingKind,
    FitzpatrickType,
)
from app.ports.vto import VtoPort

logger = logging.getLogger(__name__)

BASE_URL = "https://yce-api-01.perfectcorp.com/s2s/v1.0"
PATH_SKIN_TYPE = "/task/skin-type"
PATH_FACE_ATTRIBUTES = "/task/face-attribute"
PATH_HAIR_VTO = "/task/hair-style"
PATH_CLOTHES_VTO = "/task/clothes-try-on"

# YouCam の属性名 → ドメインの FaceAttributes フィールド名
_ATTRIBUTE_MAP = {
    "brow_ridge_depth": "brow_depth",
    "nose_bridge_height": "nose_bridge",
    "eye_distance_ratio": "eye_distance",
    "eye_roundness": "eye_roundness",
    "face_length_ratio": "face_length",
    "lip_thickness": "lip_fullness",
    "jaw_width_ratio": "jaw_width",
}


class YouCamVto(VtoPort):
    name = "youcam:live"

    def __init__(self, api_key: str, secret_key: str = "", timeout: float = 30.0) -> None:
        self.api_key = api_key
        self.secret_key = secret_key
        self.timeout = timeout
        self._fallback = MockVto()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}

    async def _post_image(self, path: str, image_bytes: bytes, data: dict | None = None) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, base_url=BASE_URL) as client:
                res = await client.post(
                    path,
                    headers=self._headers(),
                    files={"file": ("input.jpg", image_bytes, "image/jpeg")},
                    data=data or {},
                )
                res.raise_for_status()
                return res.json()
        except httpx.HTTPStatusError as exc:
            # 画像そのものはログに出さない（設計書 §7-1）。本文は原因の特定に要る
            logger.warning(
                "youcam %s: %s %s", path, exc.response.status_code, exc.response.text[:300]
            )
            return None
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("youcam %s failed: %s", path, type(exc).__name__)
            return None

    async def analyze_face(self, image_bytes: bytes) -> FaceProfile:
        skin = await self._post_image(PATH_SKIN_TYPE, image_bytes)
        attrs = await self._post_image(PATH_FACE_ATTRIBUTES, image_bytes)
        if not skin and not attrs:
            profile = await self._fallback.analyze_face(image_bytes)
            del image_bytes
            return profile

        fitz = _parse_fitzpatrick(skin)
        profile = FaceProfile(
            # 片方でも実応答が返っていればここに来る。どちらが欠けたかは
            # ログに出ているので、名前としては live を刻んでよい
            analyzed_by=self.name,
            fitzpatrick_type=fitz,
            attributes=_parse_attributes(attrs),
            source_image_discarded=True,
        )
        del image_bytes  # 解析が終わった時点で破棄する
        return profile

    async def try_on(
        self,
        *,
        image_bytes: bytes | None,
        kind: FittingKind,
        character: CharacterRef,
        limit: int = 3,
    ) -> list[FittingCandidate]:
        if image_bytes is None:
            return await self._fallback.try_on(
                image_bytes=None, kind=kind, character=character, limit=limit
            )

        path = PATH_HAIR_VTO if kind is FittingKind.WIG else PATH_CLOTHES_VTO
        payload = {"color": character.hair_color or "", "count": str(limit)}
        result = await self._post_image(path, image_bytes, payload)
        del image_bytes  # 試着に使った画像も保持しない

        if not result:
            return await self._fallback.try_on(
                image_bytes=None, kind=kind, character=character, limit=limit
            )

        items = result.get("results") or result.get("data") or []
        out: list[FittingCandidate] = []
        for i, item in enumerate(items[:limit]):
            out.append(
                FittingCandidate(
                    candidate_id=str(item.get("id") or f"{kind.value}_{i}"),
                    kind=kind,
                    label=str(item.get("style_name") or item.get("name") or f"候補{i + 1}"),
                    color=item.get("color") or character.hair_color,
                    preview_url=item.get("output_url") or item.get("url"),
                    fit_score=float(item.get("score") or 0.0),
                )
            )
        return out or await self._fallback.try_on(
            image_bytes=None, kind=kind, character=character, limit=limit
        )


def _parse_fitzpatrick(payload: dict | None) -> FitzpatrickType:
    """"III" / "type_iii" / 3 のいずれの形でも受ける。"""
    if not payload:
        return FitzpatrickType.III
    raw = payload.get("fitzpatrick_type") or payload.get("skin_type") or payload.get("result")
    if isinstance(raw, dict):
        raw = raw.get("fitzpatrick_type") or raw.get("skin_type")
    if isinstance(raw, int) and 1 <= raw <= 6:
        return list(FitzpatrickType)[raw - 1]
    if isinstance(raw, str):
        token = raw.strip().upper().replace("TYPE_", "").replace("TYPE", "").strip()
        try:
            return FitzpatrickType(token)
        except ValueError:
            if token.isdigit() and 1 <= int(token) <= 6:
                return list(FitzpatrickType)[int(token) - 1]
    logger.warning("unrecognised fitzpatrick payload shape; defaulting to III")
    return FitzpatrickType.III


def _parse_attributes(payload: dict | None) -> FaceAttributes:
    """未知のキーは無視し、欠けた項目は 0.5（中庸）のまま残す。"""
    if not payload:
        return FaceAttributes()
    source = payload.get("attributes") or payload.get("result") or payload
    values: dict[str, float] = {}
    for api_key, field in _ATTRIBUTE_MAP.items():
        raw = source.get(api_key)
        if raw is None:
            continue
        try:
            values[field] = max(0.0, min(1.0, float(raw)))
        except (TypeError, ValueError):
            continue
    return FaceAttributes(**values)
