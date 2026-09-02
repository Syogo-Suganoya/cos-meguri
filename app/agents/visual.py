"""ビジュアル生成エージェント（設計書 §11）。自律性は「提案まで」。

責務:
- 完成イメージ（ウィッグ×衣装×メイクの全部盛り予想図）の生成
- 合わせのアフタームービーの生成

どちらも生成前に二次創作ガイドライン・エンジンを通し、生成後は AI 生成物である
ことを明示する。キャラ名・作品名はプロンプトに入れない（設計書 §7-4）。
"""

from __future__ import annotations

import uuid

from app.domain import guardrails
from app.domain.models import (
    AuditAction,
    AuditLog,
    CharacterRef,
    Expedition,
    FittingKind,
    Lang,
    MediaAsset,
)
from app.ports.media import ImagePort, VideoPort
from app.ports.repository import RepositoryPort


class IpGuardBlocked(Exception):
    """権利物の合成にあたる依頼を止めたときに送出する。"""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("；".join(reasons))
        self.reasons = reasons


class VisualAgent:
    def __init__(
        self, image: ImagePort, video: VideoPort, repository: RepositoryPort
    ) -> None:
        self.image = image
        self.video = video
        self.repository = repository

    async def look_image(
        self,
        *,
        layer_id: str,
        expedition: Expedition,
        request_note: str = "",
    ) -> MediaAsset | None:
        """遠征の試着候補から完成予想図を1枚作る。

        試着（ウィッグ・衣装）を選ぶ前でも、キャラの色味だけで生成できる。
        製作・購入前の意思決定を支えるのが目的なので、早い段階で出せることを優先する。
        """
        await self._screen(layer_id, request_note)

        wig, costume = _selected_items(expedition)
        prompt = guardrails.build_look_prompt(
            expedition.character, wig=wig, costume=costume
        )
        if request_note:
            prompt = f"{prompt} 追加の要望: {request_note}"

        asset = await self.image.generate_look(prompt, lang=expedition.lang)
        if asset is not None:
            await self._log(layer_id, asset, subject_id=expedition.exp_id)
        return asset

    async def after_movie(
        self,
        *,
        layer_id: str,
        awase_id: str,
        image_urls: list[str],
        title: str,
        lang: Lang = Lang.JA,
        seconds: int = 5,
        request_note: str = "",
    ) -> MediaAsset | None:
        """合わせの撮影写真からアフタームービーを起こす。"""
        await self._screen(layer_id, request_note)

        prompt = (
            "コスプレの合わせのアフタームービー。ゆっくりとしたカメラワーク、"
            "被写体はそのまま、追加の文字やロゴは入れない。"
        )
        if request_note:
            prompt = f"{prompt} 追加の要望: {request_note}"

        asset = await self.video.generate_after_movie(
            image_urls=image_urls, prompt=prompt, seconds=seconds, lang=lang
        )
        if asset is not None:
            await self._log(layer_id, asset, subject_id=awase_id)
        return asset

    async def _screen(self, layer_id: str, request_note: str) -> None:
        if not request_note:
            return
        guard = guardrails.screen_generation_request(request_note)
        if guard.blocked:
            await self.repository.append_audit(
                AuditLog(
                    log_id=f"log_{uuid.uuid4().hex[:8]}",
                    actor="visual-agent",
                    action=AuditAction.IP_GUARD_BLOCKED,
                    subject_id=layer_id,
                    payload={"reasons": guard.reasons, "surface": "media"},
                )
            )
            raise IpGuardBlocked(guard.reasons)

    async def _log(self, layer_id: str, asset: MediaAsset, *, subject_id: str) -> None:
        await self.repository.append_audit(
            AuditLog(
                log_id=f"log_{uuid.uuid4().hex[:8]}",
                actor=layer_id,
                action=AuditAction.MEDIA_GENERATED,
                subject_id=subject_id,
                payload={
                    "kind": asset.kind.value,
                    "provider": asset.provider,
                    "watermarked": asset.watermarked,
                    "is_placeholder": asset.is_placeholder,
                    # 生成に使ったキャラ名は残さない（§7-4）
                    "expires_at": asset.expires_at.isoformat() if asset.expires_at else None,
                },
            )
        )


def _selected_items(expedition: Expedition) -> tuple[str, str]:
    """試着候補から、いちばん適合度の高いウィッグと衣装の名前を拾う。"""
    wig, costume = "キャラに合わせたウィッグ", "キャラに合わせた衣装"
    fitting = expedition.fitting
    if not fitting:
        return wig, costume

    for candidate in sorted(fitting.candidates, key=lambda c: -c.fit_score):
        if candidate.kind is FittingKind.WIG and wig.startswith("キャラ"):
            wig = candidate.label
        elif candidate.kind is FittingKind.COSTUME and costume.startswith("キャラ"):
            costume = candidate.label
    return wig, costume


def character_is_hidden(prompt: str, character: CharacterRef) -> bool:
    """生成プロンプトにキャラ名・作品名が漏れていないか（テスト・監査用）。"""
    return character.name not in prompt and character.title not in prompt
