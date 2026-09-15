"""動線エージェント（設計書 §4）。

一般の経路案内との違いは、候補の選び方にある。所要時間の最短ではなく
「体感時間（乗換ぶんを足したもの） → 乗換 → 運賃」の順で選ぶ（大荷物ユーザーの実際の負担順）。
"""

from __future__ import annotations

from datetime import datetime

from app.domain import luggage
from app.domain.models import Lang, LuggageMode, RoutePlan
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
        lang: Lang = Lang.JA,
    ) -> RoutePlan:
        raw_routes = await self.transit.search(
            from_station=from_station, to_station=to_station, arrive_by=arrive_by
        )
        plans = [
            luggage.build_plan(segments, direction="outbound", mode=mode, arrive_by=arrive_by, lang=lang)
            for segments in raw_routes
        ]
        if not plans:
            return _empty("outbound", mode, lang)
        return await self._mark_estimated(luggage.prefer_easiest(plans)[0], from_station, to_station, lang)

    async def plan_return(
        self,
        *,
        from_station: str,
        to_station: str,
        depart_at: datetime,
        mode: LuggageMode,
        lang: Lang = Lang.JA,
    ) -> RoutePlan:
        raw_routes = await self.transit.search(
            from_station=from_station, to_station=to_station, depart_at=depart_at
        )
        plans = [
            luggage.build_plan(segments, direction="return", mode=mode, depart_at=depart_at, lang=lang)
            for segments in raw_routes
        ]
        if not plans:
            return _empty("return", mode, lang)
        return await self._mark_estimated(luggage.prefer_easiest(plans)[0], from_station, to_station, lang)

    async def _mark_estimated(
        self, plan: RoutePlan, from_station: str, to_station: str, lang: Lang = Lang.JA
    ) -> RoutePlan:
        """駅すぱあとで引けず目安に落ちた経路には、駅名を確かめるよう添える。

        駅名が曖昧（「大宮」）なら正式な候補も添える。候補から選び直せば本物の経路が引ける。
        """
        if not any(seg.estimated for seg in plan.segments):
            return plan
        ja = lang is Lang.JA
        hints = []
        for station in dict.fromkeys((from_station, to_station)):
            candidates = await self.transit.suggest_stations(station, limit=4)
            if candidates and station not in candidates:
                hints.append(
                    f"「{station}」は {'・'.join(candidates)} のどれかを選んでください"
                    if ja
                    else f'For "{station}", pick one of: {", ".join(candidates)}'
                )
        if ja:
            message = (
                f"「{from_station}」→「{to_station}」の経路を駅すぱあとで引けませんでした。"
                + ("。".join(hints) if hints else "駅名を確かめてください")
                + "（ここに出ているのは目安の経路です）。"
            )
        else:
            message = (
                f'Couldn\'t find a route from "{from_station}" to "{to_station}" on Ekispert. '
                + (". ".join(hints) if hints else "Check the station names")
                + " (the route shown is only an estimate)."
            )
        plan.warnings.insert(0, message)
        return plan

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


def _empty(direction: str, mode: LuggageMode, lang: Lang = Lang.JA) -> RoutePlan:
    return RoutePlan(
        direction=direction,  # type: ignore[arg-type]
        luggage_mode=mode,
        warnings=["経路が取得できませんでした" if lang is Lang.JA else "Couldn't get a route"],
    )
