"""駅すぱあと MCP の代役。

デモで使う主要駅だけを静的グラフで持ち、経路候補を2〜3本作る。
本物との違いは経路の出どころだけで、返す RouteSegment の形は同じ。
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from app.domain.models import RouteSegment
from app.ports.transit import TransitPort

# 会場最寄り駅と、その手前の乗換駅（デモ用の最小グラフ）
_HUBS: dict[str, list[tuple[str, str]]] = {
    "国際展示場": [("新木場", "りんかい線"), ("豊洲", "ゆりかもめ")],
    "上前津": [("金山", "名城線"), ("栄", "名城線")],
    "栄": [("金山", "名城線"), ("名古屋", "東山線")],
    "池袋": [("新宿", "埼京線"), ("赤羽", "埼京線")],
}

# 大型ロッカーのある駅


def _seed(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


class MockTransit(TransitPort):
    name = "ekispert:mock"

    async def suggest_stations(self, name: str, *, limit: int = 8) -> list[str]:
        """静的グラフに載っている駅から、書きかけの名前を含むものを返す。"""
        wanted = name.strip().removesuffix("駅")
        if not wanted:
            return []
        known = sorted({*_HUBS, *(hub for hubs in _HUBS.values() for hub, _ in hubs)})
        return [station for station in known if wanted in station][:limit]

    async def search(
        self,
        *,
        from_station: str,
        to_station: str,
        arrive_by: datetime | None = None,
        depart_at: datetime | None = None,
        max_routes: int = 3,
    ) -> list[list[RouteSegment]]:
        seed = _seed(from_station, to_station)
        hubs = _HUBS.get(to_station, [("乗換駅", "在来線")])

        routes: list[list[RouteSegment]] = []

        # 候補1: 乗換1回・EVあり（大荷物向き）
        hub, line = hubs[0]
        routes.append(
            [
                RouteSegment(
                    from_station=from_station,
                    to_station=hub,
                    line="JR線",
                    minutes=18 + seed % 12,
                    fare_yen=220 + (seed % 5) * 30,
                ),
                RouteSegment(
                    from_station=hub,
                    to_station=to_station,
                    line=line,
                    minutes=9 + seed % 6,
                    fare_yen=180 + (seed % 4) * 20,
                ),
            ]
        )

        # 候補2: 直通で速いが乗換なし・割高
        routes.append(
            [
                RouteSegment(
                    from_station=from_station,
                    to_station=to_station,
                    line="地下鉄直通",
                    minutes=24 + seed % 8,
                    fare_yen=320 + (seed % 3) * 40,
                )
            ]
        )

        # 候補3: 乗換2回・安い
        if len(hubs) > 1 and max_routes >= 3:
            hub2, line2 = hubs[1]
            routes.append(
                [
                    RouteSegment(
                        from_station=from_station,
                        to_station=hub2,
                        line="私鉄線",
                        minutes=15 + seed % 10,
                        fare_yen=190,
                    ),
                    RouteSegment(
                        from_station=hub2,
                        to_station=hubs[0][0],
                        line=line2,
                        minutes=7,
                        fare_yen=160,
                    ),
                    RouteSegment(
                        from_station=hubs[0][0],
                        to_station=to_station,
                        line=hubs[0][1],
                        minutes=8,
                        fare_yen=150,
                    ),
                ]
            )

        return routes[:max_routes]
