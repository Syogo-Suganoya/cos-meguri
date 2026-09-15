"""経路のポート（駅すぱあと API MCPサーバー）。

大荷物の負担は乗換の回数で測るので、区間ごとの所要・運賃・路線があれば足りる。
運行情報（遅延）は扱わない。遅延の通知ごとアプリから外した。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.domain.models import RouteSegment


class TransitPort(ABC):
    name: str = "ekispert"

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

    async def suggest_stations(self, name: str, *, limit: int = 8) -> list[str]:
        """書きかけの駅名から、経路探索にそのまま渡せる正式な駅名の候補を返す。

        「大宮」は埼玉と京都にあり、そのままでは探索できない（「大宮(埼玉県)」と書く必要がある）。
        駅名は自由入力なので、相談の画面で候補から選べるようにする。引けなければ空。
        """
        return []
