"""大荷物制約の経路評価（設計書 §4 動線エージェント）。

一般の経路案内は「身軽な人」を前提にしている。ここでは駅すぱあとから得た
区間情報に、階段・乗換・エレベータ有無を掛けて体感時間へ引き直す。
外部APIには依存しない純粋関数群。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from app.domain.models import (
    LuggageMode,
    RoutePlan,
    RouteSegment,
    ServiceDisruption,
)


def effective_minutes(segments: list[RouteSegment], mode: LuggageMode) -> int:
    """階段・乗換のペナルティを積んだ体感所要時間。"""
    base = sum(s.minutes for s in segments)
    stairs = sum(s.stairs for s in segments)
    transfers = max(len(segments) - 1, 0)
    return (
        base
        + stairs * mode.stair_penalty_minutes
        + transfers * mode.transfer_penalty_minutes
    )


def elevator_coverage(segments: list[RouteSegment]) -> float:
    """EV でたどれる区間の割合。1.0 なら段差なしで通せる。"""
    if not segments:
        return 1.0
    return sum(1 for s in segments if s.has_elevator) / len(segments)


def build_plan(
    segments: list[RouteSegment],
    *,
    direction: Literal["outbound", "return"],
    mode: LuggageMode,
    arrive_by: datetime | None = None,
    depart_at: datetime | None = None,
    locker_station: str | None = None,
) -> RoutePlan:
    """区間列から大荷物モードの経路プランを組む。

    arrive_by を渡すと逆算して出発時刻を、depart_at を渡すと到着時刻を埋める。
    """
    base = sum(s.minutes for s in segments)
    eff = effective_minutes(segments, mode)
    coverage = elevator_coverage(segments)
    transfers = max(len(segments) - 1, 0)

    plan = RoutePlan(
        direction=direction,
        segments=segments,
        luggage_mode=mode,
        base_minutes=base,
        effective_minutes=eff,
        fare_yen=sum(s.fare_yen for s in segments),
        transfers=transfers,
        elevator_coverage=round(coverage, 2),
    )

    if arrive_by is not None:
        plan.arrive_at = arrive_by
        plan.depart_at = arrive_by - timedelta(minutes=eff)
    elif depart_at is not None:
        plan.depart_at = depart_at
        plan.arrive_at = depart_at + timedelta(minutes=eff)

    plan.warnings = _warnings(segments, mode, coverage)
    if mode.needs_locker and locker_station:
        plan.locker_suggestion = (
            f"{locker_station}のコインロッカーに大型荷物を預けると、"
            f"以降の乗換ペナルティが約{transfers * mode.transfer_penalty_minutes}分減ります"
        )
    return plan


def _warnings(
    segments: list[RouteSegment], mode: LuggageMode, coverage: float
) -> list[str]:
    out: list[str] = []
    if mode is LuggageMode.LIGHT:
        return out
    no_ev = [s for s in segments if not s.has_elevator]
    if no_ev:
        names = "・".join(f"{s.from_station}→{s.to_station}" for s in no_ev)
        out.append(f"エレベータのない乗換があります（{names}）")
    stairs = sum(s.stairs for s in segments)
    if stairs:
        out.append(f"階段が{stairs}箇所。キャリーの持ち上げで+{stairs * mode.stair_penalty_minutes}分見込み")
    if coverage < 0.6:
        out.append("EV被覆率が低い経路です。1本後でもEV経路を優先することを推奨します")
    return out


def prefer_step_free(candidates: list[RoutePlan]) -> list[RoutePlan]:
    """EV被覆を優先し、同点は体感時間で並べる（設計書 §4「EV優先」）。"""
    return sorted(
        candidates,
        key=lambda p: (-p.elevator_coverage, p.effective_minutes, p.fare_yen),
    )


def apply_disruptions(
    plan: RoutePlan, disruptions: list[ServiceDisruption]
) -> tuple[RoutePlan, int]:
    """運行障害を経路に反映し、(更新後プラン, 追加遅延分) を返す。

    当日モードではこれを Cloud Scheduler 起点で回し、遅延が出たら再計算する。
    """
    lines = {s.line for s in plan.segments}
    hit = [d for d in disruptions if d.line in lines]
    if not hit:
        return plan, 0

    delay = sum(d.delay_minutes for d in hit)
    updated = plan.model_copy(deep=True)
    updated.effective_minutes += delay
    if updated.arrive_at and updated.depart_at:
        # 到着時刻を守る前提なら出発を前倒しする
        updated.depart_at = updated.arrive_at - timedelta(minutes=updated.effective_minutes)
    for d in hit:
        updated.warnings.append(f"{d.line}: {d.status}（+{d.delay_minutes}分）{d.detail}")
    return updated, delay
