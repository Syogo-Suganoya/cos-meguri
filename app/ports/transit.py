"""経路・運行実況のポート（駅すぱあと API MCPサーバー）。

大荷物制約の評価に必要なのは所要・運賃だけでなく、階段の数と
エレベータ有無。RouteSegment にその設備情報を載せて返す。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.domain.models import RouteSegment, ServiceDisruption


class TransitPort(ABC):
    name: str = "transit"

    @abstractmethod
    async def search(
        self,
        *,
        from_station: str,
        to_station: str,
        arrive_by: datetime | None = None,
        depart_at: datetime | None = None,
        max_routes: int = 3,
    ) -> list[list[RouteSegment]]:
        """複数の経路候補を、区間列のリストとして返す。"""

    @abstractmethod
    async def disruptions(self, lines: list[str]) -> list[ServiceDisruption]:
        """当日の運行障害を返す。"""

    @abstractmethod
    async def locker_station(self, near_station: str) -> str | None:
        """大型ロッカーのある最寄り駅を返す。無ければ None。"""
