"""試着エージェント（設計書 §4）。自律性は「提案まで」。

責務:
- 顔画像を解析して数値プロファイルにし、画像を破棄して証跡を残す
- キャラからウィッグ・衣装の候補を出す
- 出力前に二次創作ガイドライン・エンジンを通す
"""

from __future__ import annotations

import uuid

from app.domain import guardrails
from app.domain.models import (
    AuditAction,
    AuditLog,
    CharacterRef,
    FaceProfile,
    FittingKind,
    FittingResult,
)
from app.ports.repository import RepositoryPort
from app.ports.vto import VtoPort


class IpGuardBlocked(Exception):
    """権利物の合成にあたる依頼を止めたときに送出する。"""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("；".join(reasons))
        self.reasons = reasons


class FittingAgent:
    def __init__(self, vto: VtoPort, repository: RepositoryPort) -> None:
        self.vto = vto
        self.repository = repository

    async def analyze_face(self, layer_id: str, image_bytes: bytes) -> FaceProfile:
        """設計書 §7-1: 解析後に画像を破棄し、破棄証跡を audit に残す。"""
        profile = await self.vto.analyze_face(image_bytes)
        del image_bytes
        await self.repository.append_audit(
            AuditLog(
                log_id=f"log_{uuid.uuid4().hex[:8]}",
                actor="fitting-agent",
                action=AuditAction.FACE_IMAGE_DISCARDED,
                subject_id=layer_id,
                payload={
                    "provider": self.vto.name,
                    "retained": ["fitzpatrick_type", "face_attributes"],
                    "image_retained": False,
                },
            )
        )
        return profile

    async def propose(
        self,
        *,
        layer_id: str,
        character: CharacterRef,
        image_bytes: bytes | None = None,
        kinds: list[FittingKind] | None = None,
        limit: int = 3,
        request_note: str = "",
    ) -> FittingResult:
        """ウィッグ・衣装の試着候補を提案する。確定はユーザーが行う。"""
        if request_note:
            guard = guardrails.screen_generation_request(request_note)
            if guard.blocked:
                await self.repository.append_audit(
                    AuditLog(
                        log_id=f"log_{uuid.uuid4().hex[:8]}",
                        actor="fitting-agent",
                        action=AuditAction.IP_GUARD_BLOCKED,
                        subject_id=layer_id,
                        payload={"reasons": guard.reasons},
                    )
                )
                raise IpGuardBlocked(guard.reasons)

        kinds = kinds or [FittingKind.WIG, FittingKind.COSTUME]
        candidates = []
        for kind in kinds:
            candidates.extend(
                await self.vto.try_on(
                    image_bytes=image_bytes,
                    kind=kind,
                    character=character,
                    limit=limit,
                )
            )
        del image_bytes

        if candidates:
            await self.repository.append_audit(
                AuditLog(
                    log_id=f"log_{uuid.uuid4().hex[:8]}",
                    actor="fitting-agent",
                    action=AuditAction.FITTING_IMAGE_DISCARDED,
                    subject_id=layer_id,
                    payload={"provider": self.vto.name, "candidates": len(candidates)},
                )
            )

        return FittingResult(
            # 内部入力に限定。共有テキストにはこの値を出さない（§7-4）
            character_hint=f"{character.title}/{character.name}",
            candidates=sorted(candidates, key=lambda c: -c.fit_score),
        )
