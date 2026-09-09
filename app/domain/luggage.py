"""大荷物制約の経路評価（設計書 §4 動線エージェント）。

一般の経路案内は「身軽な人」を前提にしている。ここでは乗換の回数を体感時間へ
引き直す。外部APIには依存しない純粋関数群。

**駅設備（エレベータ・階段・コインロッカー）は扱わない。** 駅すぱあと API に
そのデータが無く、こちら側で捏造すると大荷物の利用者を危険側に倒すため。
段差の代わりに「乗換のたびに何分かかる体感か」だけで測る。
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
    """乗換のペナルティを積んだ体感所要時間。"""
    base = sum(s.minutes for s in segments)
    transfers = max(len(segments) - 1, 0)
    return base + transfers * mode.transfer_penalty_minutes


def build_plan(
    segments: list[RouteSegment],
    *,
    direction: Literal["outbound", "return"],
    mode: LuggageMode,
    arrive_by: datetime | None = None,
    depart_at: datetime | None = None,
) -> RoutePlan:
    """区間列から大荷物モードの経路プランを組む。

    arrive_by を渡すと逆算して出発時刻を、depart_at を渡すと到着時刻を埋める。
    """
    base = sum(s.minutes for s in segments)
    eff = effective_minutes(segments, mode)
    transfers = max(len(segments) - 1, 0)

    plan = RoutePlan(
        direction=direction,
        segments=segments,
        luggage_mode=mode,
        base_minutes=base,
        effective_minutes=eff,
        fare_yen=sum(s.fare_yen for s in segments),
        transfers=transfers,
    )

    if arrive_by is not None:
        plan.arrive_at = arrive_by
        plan.depart_at = arrive_by - timedelta(minutes=eff)
    elif depart_at is not None:
        plan.depart_at = depart_at
        plan.arrive_at = depart_at + timedelta(minutes=eff)

    plan.warnings = _warnings(mode, transfers)
    return plan


def _warnings(mode: LuggageMode, transfers: int) -> list[str]:
    out: list[str] = []
    if mode is LuggageMode.LIGHT or not transfers:
        return out
    out.append(
        f"乗換が{transfers}回。大荷物ぶんで+{transfers * mode.transfer_penalty_minutes}分見込み"
    )
    return out


def prefer_easiest(candidates: list[RoutePlan]) -> list[RoutePlan]:
    """大荷物での体感時間が短い順に並べる。

    以前は EV 被覆を第一の軸にしていたが、駅すぱあと API に設備データが無く
    実データで裏付けられないため取り下げた。

    「乗換の少ない順」にはしない。直通60分と乗換2回30分なら後者を選ぶべきで、
    乗換の重さは effective_minutes に積んだペナルティで表現されている。
    こうしておくと、荷物が増えるほど自然に乗換の少ない経路へ寄る。
    """
    return sorted(
        candidates,
        key=lambda p: (p.effective_minutes, p.transfers, p.fare_yen),
    )


def apply_disruptions(
    plan: RoutePlan, disruptions: list[ServiceDisruption]
) -> tuple[RoutePlan, int]:
    """運行障害を経路に反映し、(更新後プラン, 追加遅延分) を返す。

    当日モードを進めるたびにこれを通し、遅延が出ていれば経路を組み直す。
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
