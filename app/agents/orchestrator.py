"""Orchestrator（設計書 §4）。遠征計画の受付と、当日モードの進行管理。

計画フェーズは対話（ユーザーの確定を待つ）、当日フェーズは自律進行。
各サブエージェントの結果を Expedition に束ね、Firestore に保存する。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.agents.awase import AwaseAgent
from app.agents.dressing import DressingAgent
from app.agents.fitting import FittingAgent
from app.agents.i18n import I18nAgent
from app.agents.makeup import MakeupAgent
from app.agents.route import RouteAgent
from app.domain.events import get_event
from app.domain.models import (
    JST,
    CharacterRef,
    EventRef,
    Expedition,
    ExpeditionStatus,
    FaceProfile,
    FittingKind,
    FitzpatrickType,
    Lang,
    Layer,
    LuggageMode,
    NotificationKind,
    event_day,
)
from app.ports.notifier import NotifierPort
from app.ports.repository import RepositoryPort

logger = logging.getLogger(__name__)

# 会場到着から撮影開始までに要る余裕（着替え＋メイク直し）
VENUE_BUFFER_MINUTES = 30


@dataclass
class PlanRequest:
    layer_id: str
    event_id: str
    day: datetime
    character: CharacterRef
    origin_station: str
    luggage_mode: LuggageMode = LuggageMode.CARRY
    lang: Lang = Lang.JA
    face_image: bytes | None = None
    include_fitting: bool = True
    attendance_factor: float = 1.0


@dataclass
class DayOfUpdate:
    """当日モードの1回分の実行結果。"""

    exp_id: str
    route_delay_minutes: int = 0
    route_message: str | None = None
    dressing_alert: str | None = None
    proposals: list[str] = None  # proposal_id の配列
    notified: int = 0

    def __post_init__(self) -> None:
        if self.proposals is None:
            self.proposals = []


class Orchestrator:
    def __init__(
        self,
        *,
        fitting: FittingAgent,
        makeup: MakeupAgent,
        route: RouteAgent,
        dressing: DressingAgent,
        awase: AwaseAgent,
        i18n: I18nAgent,
        repository: RepositoryPort,
        notifier: NotifierPort,
    ) -> None:
        self.fitting = fitting
        self.makeup = makeup
        self.route = route
        self.dressing = dressing
        self.awase = awase
        self.i18n = i18n
        self.repository = repository
        self.notifier = notifier

    # -- 計画フェーズ -----------------------------------------------------
    async def plan(self, req: PlanRequest) -> tuple[Expedition, dict]:
        """遠征プランを一括で組む。戻り値は (Expedition, 補足情報)。"""
        event_master = get_event(req.event_id)
        if event_master is None:
            raise KeyError(f"unknown event: {req.event_id}")

        layer = await self.repository.get_layer(req.layer_id)
        if layer is None:
            raise KeyError(f"unknown layer: {req.layer_id}")

        day = event_day(req.day)  # 開場・閉場は JST 基準で組み立てる
        starts_at = day.replace(hour=event_master.opens_at_hour)
        ends_at = day.replace(hour=event_master.closes_at_hour)
        event_ref = EventRef(
            event_id=event_master.event_id,
            name=event_master.name,
            venue=event_master.venue,
            starts_at=starts_at,
            ends_at=ends_at,
        )

        # 1. 顔プロファイル（画像は解析後に破棄）
        profile = await self._ensure_profile(layer, req.face_image)

        # 2. 更衣室の混雑予測 → 入場・撤収の推奨
        dressing_plan = await self.dressing.plan(
            event_master,
            day,
            attendance_factor=req.attendance_factor,
        )
        arrive_by = (dressing_plan.recommended_entry or starts_at) - timedelta(
            minutes=VENUE_BUFFER_MINUTES
        )
        leave_at = dressing_plan.recommended_exit or ends_at

        # 3. 大荷物制約の動線（行き・帰り）
        outbound = await self.route.plan_outbound(
            from_station=req.origin_station,
            to_station=event_master.station,
            arrive_by=arrive_by,
            mode=req.luggage_mode,
        )
        inbound = await self.route.plan_return(
            from_station=event_master.station,
            to_station=req.origin_station,
            depart_at=leave_at,
            mode=req.luggage_mode,
        )

        # 4. メイク工程（肌タイプ×顔属性×キャラ、母語で出力）
        makeup_plan = await self.makeup.build(profile, req.character, lang=req.lang)

        # 5. 試着候補（提案まで）
        fitting_result = None
        if req.include_fitting:
            fitting_result = await self.fitting.propose(
                layer_id=req.layer_id,
                character=await self.makeup.enrich_character(req.character, lang=req.lang),
                image_bytes=req.face_image,
                kinds=[FittingKind.WIG, FittingKind.COSTUME],
            )

        exp = Expedition(
            exp_id=f"exp_{uuid.uuid4().hex[:8]}",
            layer_id=req.layer_id,
            status=ExpeditionStatus.PLANNED,
            lang=req.lang,
            event=event_ref,
            event_date=event_ref.date_key,  # 当日バッチの絞り込みキー
            character=req.character,
            luggage_mode=req.luggage_mode,
            origin_station=req.origin_station,
            fitting=fitting_result,
            makeup=makeup_plan,
            routes={"outbound": outbound, "return": inbound},
            dressing=dressing_plan,
        )
        await self.repository.save_expedition(exp)

        extras = {
            "cultural_note": await self.i18n.cultural_note(event_master.name, req.lang),
            "ui": self.i18n.ui_strings(req.lang),
            "makeup_coverage": self.makeup.coverage(makeup_plan),
            "leave_home_at": outbound.depart_at.isoformat() if outbound.depart_at else None,
            "wake_up_hint": _wake_up_hint(outbound.depart_at, makeup_plan.total_minutes),
        }
        return exp, extras

    async def _ensure_profile(self, layer: Layer, image: bytes | None) -> FaceProfile:
        """画像があれば解析し直し、無ければ保存済みプロファイルを使う。"""
        if image is not None:
            profile = await self.fitting.analyze_face(layer.layer_id, image)
            layer.face_profile = profile
            await self.repository.save_layer(layer)
            return profile
        if layer.face_profile is not None:
            return layer.face_profile
        # 未解析でも工程は出す。中庸の既定値であることは UI 側で明示する
        return FaceProfile(fitzpatrick_type=FitzpatrickType.III)

    # -- 当日モード -------------------------------------------------------
    async def run_day_of(self, exp_id: str, *, now: datetime | None = None) -> DayOfUpdate:
        """Cloud Scheduler から定期起動する自律進行。

        1. 経路の運行実況を見て再計算し、遅延があれば本人に通知
        2. 撤収アラートの時刻に達していれば通知
        3. 合わせに紐づくなら到着監視とリスケ起案（確定はしない）
        """
        exp = await self.repository.get_expedition(exp_id)
        if exp is None:
            raise KeyError(f"unknown expedition: {exp_id}")
        now = now or datetime.now(exp.event.starts_at.tzinfo)

        update = DayOfUpdate(exp_id=exp_id)
        exp.status = ExpeditionStatus.DAY_OF

        # 1. 動線の再計算
        outbound = exp.routes.get("outbound")
        if outbound:
            updated_route, delay, message = await self.route.recheck(outbound)
            exp.routes["outbound"] = updated_route
            update.route_delay_minutes = delay
            update.route_message = message
            if message:
                await self.notifier.push(
                    layer_id=exp.layer_id,
                    message=message,
                    kind=NotificationKind.ROUTE_DELAY,
                    lang=exp.lang,
                    exp_id=exp.exp_id,
                )
                update.notified += 1

        # 2. 撤収アラート
        if exp.dressing and exp.dressing.teardown_alert_at:
            if now >= exp.dressing.teardown_alert_at:
                alert = self.dressing.teardown_alert(exp.dressing)
                if alert:
                    update.dressing_alert = alert
                    await self.notifier.push(
                        layer_id=exp.layer_id,
                        message=alert,
                        kind=NotificationKind.TEARDOWN,
                        lang=exp.lang,
                        exp_id=exp.exp_id,
                    )
                    update.notified += 1

        await self.repository.save_expedition(exp)

        # 3. 合わせの到着監視
        if exp.awase_id:
            awase = await self.repository.get_awase(exp.awase_id)
            if awase:
                proposals = await self.awase.monitor(awase, now=now)
                update.proposals = [p.proposal_id for p in proposals]

        return update

    async def run_day_of_batch(self, *, now: datetime | None = None) -> list[DayOfUpdate]:
        """その日の遠征をまとめて1回進める。Cloud Scheduler から定期起動する。

        1件ずつの `run_day_of` は利用者の操作にも使うが、こちらは無人で回る入口。
        1件が落ちても残りを進める（1人の遠征の失敗で全員の通知が止まらないように）。
        """
        now = now or datetime.now(JST)
        today = now.astimezone(JST).strftime("%Y-%m-%d")

        updates: list[DayOfUpdate] = []
        for exp in await self.repository.list_expeditions_on(today):
            try:
                updates.append(await self.run_day_of(exp.exp_id, now=now))
            except Exception:  # noqa: BLE001 — 1件の失敗で全体を止めない
                logger.exception("day-of batch failed for %s", exp.exp_id)
        return updates


def _wake_up_hint(depart_at: datetime | None, makeup_minutes: int) -> str | None:
    """出発時刻とメイク所要から、起床の目安を出す。"""
    if depart_at is None:
        return None
    # メイク＋着替え＋支度の余白
    ready_at = depart_at - timedelta(minutes=makeup_minutes + 30)
    return (
        f"メイクに約{makeup_minutes}分。支度込みで{ready_at:%H:%M}には起きておくと"
        f"{depart_at:%H:%M}の出発に間に合います。"
    )
