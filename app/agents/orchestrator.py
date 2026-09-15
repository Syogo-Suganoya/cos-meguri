"""Orchestrator（設計書 §4）。遠征計画の受付。

条件を受け取り、各サブエージェントの結果を Expedition に束ねて保存する。
当日モード（遅延の再計算・撤収の通知・合わせの到着監視）は取り下げた。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.agents.i18n import I18nAgent
from app.agents.makeup import MakeupAgent
from app.agents.route import RouteAgent
from app.domain.events import get_event
from app.domain.models import (
    CUSTOM_EVENT_ID,
    CharacterRef,
    EventRef,
    Expedition,
    ExpeditionStatus,
    Lang,
    LuggageMode,
    event_day,
)
from app.ports.repository import RepositoryPort

logger = logging.getLogger(__name__)

class PlanError(ValueError):
    """条件が組めない形をしている（終了が開始より前など）。field はどの欄の誤りか。

    code は画面が自分の言語で言い直すための印（ends_before_starts / bad_time）。
    """

    def __init__(self, message: str, field: str, code: str) -> None:
        super().__init__(message)
        self.field = field
        self.code = code


@dataclass
class PlanRequest:
    """組む条件。イベントは名前・目的地（最寄り駅）・開始・終了（HH:MM、JST）で受ける。

    収載イベントかどうかは問わない（event_id は当たったときの控え）。
    """

    layer_id: str
    event_name: str
    destination_station: str
    starts_time: str
    ends_time: str
    day: datetime
    character: CharacterRef
    origin_station: str
    event_id: str | None = None
    luggage_mode: LuggageMode = LuggageMode.CARRY
    lang: Lang = Lang.JA


def _at(day: datetime, hhmm: str, field: str) -> datetime:
    try:
        hour, minute = (int(x) for x in hhmm.split(":"))
        return day.replace(hour=hour, minute=minute)
    except ValueError as exc:
        raise PlanError("時刻は HH:MM の形で入れてください。", field, "bad_time") from exc


class Orchestrator:
    def __init__(
        self,
        *,
        makeup: MakeupAgent,
        route: RouteAgent,
        i18n: I18nAgent,
        repository: RepositoryPort,
    ) -> None:
        self.makeup = makeup
        self.route = route
        self.i18n = i18n
        self.repository = repository

    # -- 計画フェーズ -----------------------------------------------------
    async def plan(self, req: PlanRequest) -> tuple[Expedition, dict]:
        """遠征プランを一括で組む。戻り値は (Expedition, 補足情報)。"""
        layer = await self.repository.get_layer(req.layer_id)
        if layer is None:
            raise KeyError(f"unknown layer: {req.layer_id}")

        day = event_day(req.day)  # 開場・閉場は JST 基準で組み立てる
        starts_at = _at(day, req.starts_time, "starts_time")
        ends_at = _at(day, req.ends_time, "ends_time")
        if ends_at <= starts_at:
            raise PlanError("終了は開始より後の時刻にしてください。", "ends_time", "ends_before_starts")
        event_ref = EventRef(
            event_id=req.event_id or CUSTOM_EVENT_ID,
            name=req.event_name,
            # 収載イベントなら会場名、それ以外は目的地の駅名で呼ぶ
            venue=master.venue if (master := get_event(req.event_id or "")) else req.destination_station,
            station=req.destination_station,
            starts_at=starts_at,
            ends_at=ends_at,
        )

        # 1. 大荷物制約の動線。開場に着くように行き、閉場で帰る
        #    （更衣室の混雑予測は取り下げた。実データの裏付けが無い推奨時刻で動線を決めない）
        outbound = await self.route.plan_outbound(
            from_station=req.origin_station,
            to_station=req.destination_station,
            arrive_by=starts_at,
            mode=req.luggage_mode,
            lang=req.lang,
        )
        inbound = await self.route.plan_return(
            from_station=req.destination_station,
            to_station=req.origin_station,
            depart_at=ends_at,
            mode=req.luggage_mode,
            lang=req.lang,
        )

        # 2. メイク工程（キャラの色味・造形から、母語で出力）
        makeup_plan = await self.makeup.build(req.character, lang=req.lang)

        exp = Expedition(
            exp_id=f"exp_{uuid.uuid4().hex[:8]}",
            layer_id=req.layer_id,
            status=ExpeditionStatus.PLANNED,
            lang=req.lang,
            event=event_ref,
            event_date=event_ref.date_key,
            character=req.character,
            luggage_mode=req.luggage_mode,
            origin_station=req.origin_station,
            makeup=makeup_plan,
            routes={"outbound": outbound, "return": inbound},
        )
        await self.repository.save_expedition(exp)

        extras = {
            "cultural_note": await self.i18n.cultural_note(req.event_name, req.lang),
            "ui": self.i18n.ui_strings(req.lang),
            "makeup_coverage": self.makeup.coverage(makeup_plan),
            "leave_home_at": outbound.depart_at.isoformat() if outbound.depart_at else None,
            "wake_up_hint": _wake_up_hint(outbound.depart_at, makeup_plan.total_minutes),
        }
        return exp, extras


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
