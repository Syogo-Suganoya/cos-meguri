"""試着・顔解析のポート（YouCam API）。

Hair Style/Color VTO・Clothes VTO・AI Makeup/Look VTO に加えて、
Fitzpatrick Skin Type Analysis と Face Attributes & Ratio Analyzer を扱う。

設計書 §7-1 の要求から、実装は必ず次を守る:
- 受け取った顔画像は解析後に破棄し、数値スコアだけを返す
- 破棄した事実を呼び出し側が監査ログに残せるよう、discarded を真で返す
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.models import CharacterRef, FaceProfile, FittingCandidate, FittingKind


class VtoPort(ABC):
    name: str = "youcam"

    @abstractmethod
    async def analyze_face(self, image_bytes: bytes) -> FaceProfile:
        """肌タイプと顔属性を数値化する。画像は解析後に破棄すること。"""

    @abstractmethod
    async def try_on(
        self,
        *,
        image_bytes: bytes | None,
        kind: FittingKind,
        character: CharacterRef,
        limit: int = 3,
    ) -> list[FittingCandidate]:
        """ウィッグ／衣装の試着候補を返す。プレビューは一時URLで期限付き。"""
