"""動線エージェント（設計書 §4）。再計算・通知は自律。

一般の経路案内との違いは、候補の選び方にある。所要時間の最短ではなく
「EV被覆 → 体感時間 → 運賃」の順で選ぶ（大荷物ユーザーの実際の負担順）。
"""

from __future__ import annotations

from datetime import datetime

from app.domain import luggage
from app.domain.models import LuggageMode, RoutePlan, jst_hm
from app.ports.llm import LlmPort
from app.ports.transit import TransitPort


class RouteAgent:
    def __init__(self, transit: TransitPort, llm: LlmPort) -> None:
        self.transit = transit
        self.llm = llm

    async def plan_outbound(
        self,
        *,
        from_station: str,
        to_station: str,
        arrive_by: datetime,
        mode: LuggageMode,
    ) -> RoutePlan:
        raw_routes = await self.transit.search(
            from_station=from_station, to_station=to_station, arrive_by=arrive_by
        )
        plans = [
            luggage.build_plan(segments, direction="outbound", mode=mode, arrive_by=arrive_by)
            for segments in raw_routes
        ]
        return luggage.prefer_easiest(plans)[0] if plans else _empty("outbound", mode)

    async def plan_return(
        self,
        *,
        from_station: str,
        to_station: str,
        depart_at: datetime,
        mode: LuggageMode,
    ) -> RoutePlan:
        raw_routes = await self.transit.search(
            from_station=from_station, to_station=to_station, depart_at=depart_at
        )
        plans = [
            luggage.build_plan(segments, direction="return", mode=mode, depart_at=depart_at)
            for segments in raw_routes
        ]
        return luggage.prefer_easiest(plans)[0] if plans else _empty("return", mode)

    async def alternatives(
        self,
        *,
        from_station: str,
        to_station: str,
        arrive_by: datetime,
        mode: LuggageMode,
    ) -> list[RoutePlan]:
        """候補を並べて比較できる形で返す（UI の説明用）。"""
        raw_routes = await self.transit.search(
            from_station=from_station, to_station=to_station, arrive_by=arrive_by
        )
        plans = [
            luggage.build_plan(s, direction="outbound", mode=mode, arrive_by=arrive_by)
            for s in raw_routes
        ]
        return luggage.prefer_easiest(plans)

    async def recheck(self, plan: RoutePlan) -> tuple[RoutePlan, int, str | None]:
        """当日モードの自律再計算。(更新後, 追加遅延, 通知文) を返す。

        遅延が無ければ通知文は None（無用な通知を飛ばさない）。
        """
        # 引けるかどうかは叩いてみないと分からない（契約に含まれないことがある）。
        # 呼んだあとに supports_disruptions を見て、当日ページの文面を分ける
        lines = sorted({s.line for s in plan.segments})
        disruptions = await self.transit.disruptions(lines)
        updated, delay = luggage.apply_disruptions(plan, disruptions)
        if delay <= 0:
            return updated, 0, None

        fallback = (
            f"{'・'.join(d.line for d in disruptions)}の遅延で+{delay}分。"
            + (
                f"出発を{jst_hm(updated.depart_at)}に前倒ししてください。"
                if updated.depart_at
                else "出発を前倒ししてください。"
            )
        )
        message = await self.llm.explain(
            "大荷物のコスプレイヤー向けに、次の遅延情報を1〜2文で伝えてください。"
            f"遅延: {[d.model_dump() for d in disruptions]} / 追加所要: {delay}分",
            fallback=fallback,
        )
        return updated, delay, message


def _empty(direction: str, mode: LuggageMode) -> RoutePlan:
    return RoutePlan(
        direction=direction,  # type: ignore[arg-type]
        luggage_mode=mode,
        warnings=["経路が取得できませんでした"],
    )
