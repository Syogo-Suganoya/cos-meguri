"""駅すぱあと API（MCPサーバー）実装。

公式ドキュメント: https://github.com/ValLaboratory/ekispert-api-mcp-server-docs

接続の要点（ドキュメントに合わせてある。勝手な推測で書かない）:
- エンドポイントは固定のホスト型 `https://api-mcp.ekispert.jp/mcp`
- 認証は `ekispert-api-access-key` ヘッダ。Bearer ではない
- `ekispert-api-response-format: json` を付けないと XML が返る
- 通信方式は Streamable HTTP。`tools/call` の前に `initialize` と
  `notifications/initialized` が要り、以降は `Mcp-Session-Id` を付け回す
- 応答は JSON のことも SSE（`text/event-stream`）のこともある

**使っていないもの**:
- 運行情報（遅延）: MCP に Tool が無い。遅延の通知ごとアプリから外したので、
  REST も叩かない
- 駅設備（エレベータ・階段・コインロッカー）: **API 自体に無い**ので、
  アプリからも扱わない（捏造して大荷物の利用者を危険側に倒さない）
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import httpx

from app.adapters.mock_transit import MockTransit
from app.domain.models import RouteSegment
from app.ports.transit import TransitPort

logger = logging.getLogger(__name__)

MCP_URL = "https://api-mcp.ekispert.jp/mcp"
PROTOCOL_VERSION = "2025-06-18"

# ドキュメント「利用可能な機能一覧」の Tool 名
TOOL_SEARCH_ROUTES = "ekispert_api_search_routes"
TOOL_GENERATE_CONDITION = "ekispert_api_generate_condition"
TOOL_GET_STATIONS = "ekispert_api_get_stations"


class EkispertTransit(TransitPort):
    name = "ekispert:live"

    def __init__(self, mcp_url: str, api_key: str = "", timeout: float = 20.0) -> None:
        self.mcp_url = (mcp_url or MCP_URL).rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        # 経路が引けなかったときだけ、静的グラフで画面を止めない
        self._fallback = MockTransit()
        self._station_cache: dict[str, list[str]] = {}
        self._request_id = 0
        self._session_id: str | None = None
        self._condition: str | None = None
        # ダイヤ探索（departure/arrival）は時刻情報ライセンス側の機能。
        # 使えないキーだと searchType ごと弾かれるので、一度断られたら諦める
        self._timetable = True

    # ---- MCP の下回り ------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            # Streamable HTTP はどちらの形でも返しうるので、両方受ける
            "Accept": "application/json, text/event-stream",
            "ekispert-api-response-format": "json",
        }
        if self.api_key:
            headers["ekispert-api-access-key"] = self.api_key
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    @staticmethod
    def _unwrap(res: httpx.Response) -> dict | None:
        """JSON でも SSE でも、JSON-RPC の1件を取り出す。"""
        content_type = res.headers.get("content-type", "")
        if "text/event-stream" not in content_type:
            return res.json()
        # SSE: `data: {...}` の行を拾う。最後の1件が応答
        payload = None
        for line in res.text.splitlines():
            if line.startswith("data:"):
                try:
                    payload = json.loads(line[5:].strip())
                except ValueError:
                    continue
        return payload

    async def _ensure_session(self, client: httpx.AsyncClient) -> bool:
        """initialize → notifications/initialized。以後はセッションを使い回す。"""
        if self._session_id:
            return True
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "cos-meguri", "version": "0.1.0"},
            },
        }
        res = await client.post(self.mcp_url, json=body, headers=self._headers())
        res.raise_for_status()
        # セッションIDはヘッダで返る。返らないサーバーもあるので必須にはしない
        self._session_id = res.headers.get("mcp-session-id") or self._session_id
        data = self._unwrap(res)
        if not data or "error" in data:
            logger.warning("ekispert mcp initialize failed: %s", data)
            return False
        await client.post(
            self.mcp_url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=self._headers(),
        )
        return True

    async def _call(self, tool: str, arguments: dict) -> dict | None:
        """tools/call を1回。失敗は例外にせず None を返す。"""
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if not await self._ensure_session(client):
                    return None
                res = await client.post(self.mcp_url, json=body, headers=self._headers())
                res.raise_for_status()
                data = self._unwrap(res)
            if not data:
                return None
            if "error" in data:
                logger.warning("ekispert mcp error on %s: %s", tool, data["error"])
                return None
            result = data.get("result") or {}
            if result.get("isError"):
                logger.warning("ekispert tool %s returned isError: %s", tool, result)
                return None
            return _tool_payload(result)
        except (httpx.HTTPError, ValueError) as exc:
            # セッションが切れている可能性があるので、次回は張り直す
            self._session_id = None
            logger.warning("ekispert mcp call %s failed: %s", tool, exc)
            return None

    # ---- 経路探索 ----------------------------------------------------

    async def _luggage_condition(self) -> str | None:
        """大荷物向けの探索条件。`conditionDetail` に渡す文字列を作る。

        エレベータ有無は API に無いので指定できない。代わりに、実際に効く
        レバーとして「乗換時間の余裕を最大」「徒歩は少なめ」を指定する。
        条件文字列はセッション中に変わらないので1回だけ作る。
        """
        if self._condition is not None:
            return self._condition or None
        payload = await self._call(
            TOOL_GENERATE_CONDITION, {"transferTime": "mostMargin", "walk": "little"}
        )
        found = _find_condition(payload)
        self._condition = found or ""
        return found

    async def _search_with_timetable(
        self, args: dict, arrive_by: datetime | None, moment: datetime | None
    ) -> list[list[RouteSegment]]:
        """ダイヤ探索を試し、キーが対応していなければ平均待ち時間探索に落とす。

        `plain`（既定）は時刻表を見ないので `time` を送れない。到着時刻からの
        逆算はこちら側（luggage.build_plan）が所要時間から行うので、
        `plain` でも一日ぶんの組み立ては成立する。
        """
        if self._timetable and moment:
            timed = dict(args)
            timed["searchType"] = "arrival" if arrive_by else "departure"
            timed["time"] = moment.strftime("%H%M")
            payload = await self._call(TOOL_SEARCH_ROUTES, timed)
            if payload is not None:
                return _parse_routes(payload)
            # ダイヤ探索が使えないキーだった。以降は聞かない
            self._timetable = False
            logger.info("ekispert: ダイヤ探索が使えないので平均待ち時間探索に切り替える")
        return _parse_routes(await self._call(TOOL_SEARCH_ROUTES, args))

    async def search(
        self,
        *,
        from_station: str,
        to_station: str,
        arrive_by: datetime | None = None,
        depart_at: datetime | None = None,
        max_routes: int = 3,
    ) -> list[list[RouteSegment]]:
        # viaList は「出発:経由:目的」をコロンで繋いだ1本の文字列
        args: dict[str, Any] = {
            "viaList": f"{_station(from_station)}:{_station(to_station)}",
            "answerCount": max(1, min(max_routes, 20)),
        }
        moment = arrive_by or depart_at
        if moment:
            args["date"] = int(moment.strftime("%Y%m%d"))

        condition = await self._luggage_condition()
        if condition:
            args["conditionDetail"] = condition

        routes = await self._search_with_timetable(args, arrive_by, moment)
        if routes:
            return routes[:max_routes]

        # 駅名は自由入力。ローマ字（Yokohama）や読みで書かれると探索は断るが、駅の検索なら引ける。
        # 候補が1つに絞れる駅だけ正式名に置き換えて探し直す（「大宮」のように割れる駅は勝手に選ばない）
        resolved = [await self._only_candidate(name) for name in (from_station, to_station)]
        if any(resolved):
            from_name, to_name = (r or n for r, n in zip(resolved, (from_station, to_station)))
            retry = {**args, "viaList": f"{_station(from_name)}:{_station(to_name)}"}
            routes = await self._search_with_timetable(retry, arrive_by, moment)
            if routes:
                return routes[:max_routes]

        logger.warning("ekispert: 経路を引けなかったので静的グラフに落とす")
        fallback = await self._fallback.search(
            from_station=from_station,
            to_station=to_station,
            arrive_by=arrive_by,
            depart_at=depart_at,
            max_routes=max_routes,
        )
        # 目安の印を付ける。駅名は自由入力なので、打ち間違いを本物の経路に見せない
        return [[seg.model_copy(update={"estimated": True}) for seg in route] for route in fallback]

    # ---- 駅名の候補 --------------------------------------------------

    async def _only_candidate(self, name: str) -> str | None:
        """書かれた駅名と違う正式名が、ただ1つだけ見つかればそれを返す。"""
        candidates = await self.suggest_stations(name, limit=2)
        if len(candidates) == 1 and candidates[0] != _station(name):
            return candidates[0]
        return None

    async def suggest_stations(self, name: str, *, limit: int = 8) -> list[str]:
        wanted = _station(name)
        if not wanted:
            return []
        if wanted not in self._station_cache:
            payload = await self._call(TOOL_GET_STATIONS, {"name": wanted, "type": "train"})
            if payload is None:
                return []  # 引けなかったことは覚えない（通信の一時的な失敗かもしれない）
            # 入力のたびに聞くので、同じ名前は覚えておく。際限なく増えないよう古いものから捨てる
            if len(self._station_cache) >= 256:
                self._station_cache.pop(next(iter(self._station_cache)))
            self._station_cache[wanted] = _parse_station_names(payload)
        return self._station_cache[wanted][:limit]


# ---- 応答の読み取り --------------------------------------------------


def _tool_payload(result: dict) -> dict | None:
    """tools/call の result から、駅すぱあと API の JSON を取り出す。

    構造化出力があればそれを、無ければ content[].text を JSON として読む。
    """
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            try:
                parsed = json.loads(item.get("text") or "")
            except ValueError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def _parse_station_names(payload: dict | None) -> list[str]:
    """get_stations の応答から駅名だけを取り出す。「大宮(埼玉県)」のように探索にそのまま渡せる形。"""
    if not isinstance(payload, dict):
        return []
    names: list[str] = []
    for point in _listify((payload.get("ResultSet") or {}).get("Point")):
        name = ((point or {}).get("Station") or {}).get("Name") if isinstance(point, dict) else None
        if isinstance(name, str) and name and name not in names:
            names.append(name)
    return names


def _listify(value: Any) -> list:
    """駅すぱあとは要素が1つだと配列にせずオブジェクトで返す。"""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _find_condition(payload: dict | None) -> str | None:
    """探索条件生成の応答から `T...:F...:A...:` 形式の文字列を拾う。"""
    if not payload:
        return None
    result_set = payload.get("ResultSet") or payload
    for key in ("Condition", "condition", "conditionDetail"):
        found = result_set.get(key)
        if isinstance(found, str) and found:
            return found
    return None


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _parse_routes(payload: dict | None) -> list[list[RouteSegment]]:
    """ResultSet.Course[].Route を区間列に落とす。

    Course.Route.Line[i] が i 番目の乗車区間、Point[i] と Point[i+1] が
    その両端の駅。運賃は Course.Price の合計しか無いので、区間には配らず
    先頭区間に寄せる（画面は経路単位の合計しか出さない）。
    """
    if not payload:
        return []
    courses = _listify((payload.get("ResultSet") or payload).get("Course"))

    routes: list[list[RouteSegment]] = []
    for course in courses:
        if not isinstance(course, dict):
            continue
        route = course.get("Route") or {}
        lines = _listify(route.get("Line"))
        points = _listify(route.get("Point"))
        if not lines or len(points) < 2:
            continue

        fare = _fare_yen(course)
        segments: list[RouteSegment] = []
        for i, line in enumerate(lines):
            if not isinstance(line, dict) or i + 1 >= len(points):
                break
            segments.append(
                RouteSegment(
                    from_station=_station_name(points[i]),
                    to_station=_station_name(points[i + 1]),
                    line=str(line.get("Name") or "在来線"),
                    minutes=_leg_minutes(line),
                    fare_yen=fare if i == 0 else 0,
                )
            )
        if segments:
            routes.append(segments)
    return routes


def _station_name(point: Any) -> str:
    if isinstance(point, dict):
        station = point.get("Station")
        if isinstance(station, dict):
            return str(station.get("Name") or "")
        return str(point.get("Name") or "")
    return ""


def _fare_yen(course: dict) -> int:
    for price in _listify(course.get("Price")):
        if isinstance(price, dict) and price.get("kind") == "Fare":
            return _int(price.get("Oneway"))
    return 0


def _leg_minutes(line: dict) -> int:
    """乗車時間。timeOnBoard が無ければ発着時刻の差から出す。"""
    minutes = _int(line.get("timeOnBoard"), 0)
    if minutes:
        return minutes
    depart = _datetime(line.get("DepartureState"))
    arrive = _datetime(line.get("ArrivalState"))
    if depart and arrive:
        return max(0, int((arrive - depart).total_seconds() // 60))
    return 0


def _datetime(state: Any) -> datetime | None:
    if not isinstance(state, dict):
        return None
    raw = state.get("Datetime")
    if isinstance(raw, dict):
        raw = raw.get("text") or raw.get("$")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _station(name: str) -> str:
    """駅すぱあとのマスタに合わせる。

    利用者は「横浜駅から」と書くが、マスタは「横浜」で持っているため、
    末尾の「駅」を落とさないと 400「駅名が見つかりません。(横浜駅)」になる。
    """
    trimmed = name.strip()
    return trimmed[:-1] if len(trimmed) > 1 and trimmed.endswith("駅") else trimmed
