"""駅すぱあと API（MCPサーバー経由）実装。

MCP サーバーに JSON-RPC で問い合わせ、区間を RouteSegment に落とす。
設備情報（EV・階段）が応答に無い場合は「不明」ではなく保守的な既定
（EVなし・階段1）を置く。大荷物ユーザーには楽観的な既定のほうが危険なため。
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from app.adapters.mock_transit import MockTransit
from app.domain.models import RouteSegment, ServiceDisruption
from app.ports.transit import TransitPort

logger = logging.getLogger(__name__)


class EkispertTransit(TransitPort):
    name = "transit:ekispert"

    def __init__(self, mcp_url: str, api_key: str = "", timeout: float = 20.0) -> None:
        self.mcp_url = mcp_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._fallback = MockTransit()
        self._request_id = 0

    async def _call(self, tool: str, arguments: dict) -> dict | None:
        """MCP の tools/call を叩く。"""
        self._request_id += 1
        body = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(self.mcp_url, json=body, headers=headers)
                res.raise_for_status()
                data = res.json()
            if "error" in data:
                logger.warning("ekispert mcp error on %s: %s", tool, data["error"])
                return None
            return data.get("result")
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("ekispert mcp call %s failed: %s", tool, exc)
            return None

    async def search(
        self,
        *,
        from_station: str,
        to_station: str,
        arrive_by: datetime | None = None,
        depart_at: datetime | None = None,
        max_routes: int = 3,
    ) -> list[list[RouteSegment]]:
        args: dict = {"from": from_station, "to": to_station, "answerCount": max_routes}
        if arrive_by:
            args["date"] = arrive_by.strftime("%Y%m%d")
            args["time"] = arrive_by.strftime("%H%M")
            args["searchType"] = "arrival"
        elif depart_at:
            args["date"] = depart_at.strftime("%Y%m%d")
            args["time"] = depart_at.strftime("%H%M")
            args["searchType"] = "departure"

        result = await self._call("search_course_extreme", args)
        routes = _parse_routes(result)
        if routes:
            return routes[:max_routes]
        return await self._fallback.search(
            from_station=from_station,
            to_station=to_station,
            arrive_by=arrive_by,
            depart_at=depart_at,
            max_routes=max_routes,
        )

    async def disruptions(self, lines: list[str]) -> list[ServiceDisruption]:
        result = await self._call("get_operation_line", {"lines": lines})
        if not result:
            return []
        out: list[ServiceDisruption] = []
        for item in _rows(result):
            status = str(item.get("status") or item.get("Status") or "")
            if not status or status in {"平常運転", "normal"}:
                continue
            out.append(
                ServiceDisruption(
                    line=str(item.get("line") or item.get("Line") or ""),
                    status=status,
                    delay_minutes=int(item.get("delayMinutes") or 10),
                    detail=str(item.get("detail") or ""),
                )
            )
        return out

    async def locker_station(self, near_station: str) -> str | None:
        result = await self._call("search_station_facility", {"station": near_station, "facility": "locker"})
        rows = _rows(result)
        if rows:
            return str(rows[0].get("station") or near_station)
        return await self._fallback.locker_station(near_station)


def _rows(result: dict | None) -> list[dict]:
    """MCP 応答から行の配列を取り出す。形が違えば空配列。"""
    if not result:
        return []
    payload = result.get("structuredContent") or result
    for key in ("Course", "courses", "routes", "items", "rows", "results"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
        if isinstance(rows, dict):
            return [rows]
    return []


def _parse_routes(result: dict | None) -> list[list[RouteSegment]]:
    routes: list[list[RouteSegment]] = []
    for course in _rows(result):
        legs = course.get("Route", {}).get("Line") if isinstance(course.get("Route"), dict) else None
        legs = legs or course.get("legs") or course.get("segments") or []
        if isinstance(legs, dict):
            legs = [legs]
        segments: list[RouteSegment] = []
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            segments.append(
                RouteSegment(
                    from_station=str(leg.get("from") or leg.get("departureStation") or ""),
                    to_station=str(leg.get("to") or leg.get("arrivalStation") or ""),
                    line=str(leg.get("Name") or leg.get("line") or "在来線"),
                    minutes=int(leg.get("timeOnBoard") or leg.get("minutes") or 0),
                    fare_yen=int(leg.get("fare") or 0),
                    # 設備情報が無ければ保守的に倒す（大荷物ユーザーの安全側）
                    has_elevator=bool(leg.get("hasElevator", False)),
                    stairs=int(leg.get("stairs", 1)),
                )
            )
        if segments:
            routes.append(segments)
    return routes
