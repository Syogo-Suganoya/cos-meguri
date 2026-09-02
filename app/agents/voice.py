"""音声ガイドエージェント（設計書 §11）。

移動中とメイク中は画面を見られない。メイク工程と動線を母語で読み上げる。
台本づくりはここが持ち、TTS はポートに投げる。台本を自前で組むのは、
読み上げに向く言い回し（記号を読ませない・番号を明示する）が要るため。

**ボイスクローンは使わない**（設計書 §11）。参照音声を受け取る経路を持たず、
依頼文にクローンを求める表現があれば止める。
"""

from __future__ import annotations

import uuid

from app.domain import guardrails
from app.domain.models import (
    AuditAction,
    AuditLog,
    Expedition,
    Lang,
    MediaAsset,
    jst_hm,
)
from app.ports.media import SpeechPort
from app.ports.repository import RepositoryPort

# 読み上げる区間
SECTION_MAKEUP = "makeup"
SECTION_ROUTE = "route"


class VoiceCloneBlocked(Exception):
    """ボイスクローンの依頼を止めたときに送出する。"""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("；".join(reasons))
        self.reasons = reasons


class VoiceAgent:
    def __init__(self, speech: SpeechPort, repository: RepositoryPort) -> None:
        self.speech = speech
        self.repository = repository

    def build_script(self, expedition: Expedition, section: str) -> str:
        """読み上げ用の台本を組む。画面表示と違い、記号を減らして文にする。"""
        lang = expedition.lang
        if section == SECTION_MAKEUP:
            return _makeup_script(expedition, lang)
        if section == SECTION_ROUTE:
            return _route_script(expedition, lang)
        raise ValueError(f"unknown section: {section}")

    async def guide(
        self,
        *,
        layer_id: str,
        expedition: Expedition,
        section: str,
        request_note: str = "",
    ) -> tuple[MediaAsset | None, str]:
        """区間の音声ガイドを作る。戻り値は (音声, 台本)。"""
        if request_note:
            guard = guardrails.screen_voice_request(request_note)
            if guard.blocked:
                await self.repository.append_audit(
                    AuditLog(
                        log_id=f"log_{uuid.uuid4().hex[:8]}",
                        actor="voice-agent",
                        action=AuditAction.VOICE_CLONE_BLOCKED,
                        subject_id=layer_id,
                        payload={"reasons": guard.reasons},
                    )
                )
                raise VoiceCloneBlocked(guard.reasons)

        script = self.build_script(expedition, section)
        asset = await self.speech.synthesize(script, lang=expedition.lang)
        if asset is not None:
            await self.repository.append_audit(
                AuditLog(
                    log_id=f"log_{uuid.uuid4().hex[:8]}",
                    actor=layer_id,
                    action=AuditAction.MEDIA_GENERATED,
                    subject_id=expedition.exp_id,
                    payload={
                        "kind": asset.kind.value,
                        "section": section,
                        "provider": asset.provider,
                        "voice_cloned": False,
                    },
                )
            )
        return asset, script


# ---------------------------------------------------------------- 台本


def _makeup_script(expedition: Expedition, lang: Lang) -> str:
    plan = expedition.makeup
    if plan is None or not plan.steps:
        return "メイク工程がまだありません。" if lang is Lang.JA else "No makeup steps yet."

    if lang is Lang.JA:
        lines = [f"メイクは全部で{len(plan.steps)}工程、目安は{plan.total_minutes}分です。"]
        for step in plan.steps:
            lines.append(
                f"{step.order}番目、{step.area.label_ja}。{step.minutes}分。{step.instruction}"
            )
        lines.append("以上です。焦らず、乾く前に次へ進んでください。")
        return "".join(lines)

    lines = [
        f"You have {len(plan.steps)} makeup steps, about {plan.total_minutes} minutes in total."
    ]
    for step in plan.steps:
        lines.append(
            f"Step {step.order}, {step.area.label_en}. {step.minutes} minutes. {step.instruction}"
        )
    lines.append("That's everything. Take your time, and move on before each layer dries.")
    return " ".join(lines)


def _route_script(expedition: Expedition, lang: Lang) -> str:
    route = expedition.routes.get("outbound")
    if route is None or not route.segments:
        return "動線がまだありません。" if lang is Lang.JA else "No route yet."

    depart = jst_hm(route.depart_at) if route.depart_at else None
    if lang is Lang.JA:
        lines = []
        if depart:
            lines.append(f"出発は{depart}です。")
        lines.append(f"体感の所要は{route.effective_minutes}分、乗り換えは{route.transfers}回です。")
        for i, seg in enumerate(route.segments, start=1):
            stairs = "階段があります。" if seg.stairs else "エレベーターで通れます。"
            lines.append(
                f"{i}区間目、{seg.from_station}から{seg.to_station}まで{seg.line}で{seg.minutes}分。{stairs}"
            )
        if route.locker_suggestion:
            lines.append(route.locker_suggestion + "。")
        for warning in route.warnings:
            lines.append(warning + "。")
        return "".join(lines)

    lines = []
    if depart:
        lines.append(f"Leave at {depart}.")
    lines.append(
        f"About {route.effective_minutes} minutes door to door, with {route.transfers} transfers."
    )
    for i, seg in enumerate(route.segments, start=1):
        stairs = "There are stairs." if seg.stairs else "Step-free with a lift."
        lines.append(
            f"Leg {i}: {seg.from_station} to {seg.to_station} on the {seg.line}, "
            f"{seg.minutes} minutes. {stairs}"
        )
    return " ".join(lines)
