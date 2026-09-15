"""駅すぱあと MCP アダプタの読み取り部分。

実APIを叩くテストではない（アクセスキーが要る）。公式ドキュメントに載っている
応答の形をそのまま置いて、こちらの読み取りが噛み合うかだけを見る。
契約が変わったら、ここが先に落ちてくれる。

出典:
- 応答の形 https://docs.ekispert.com/v1/api/search/course/extreme.html
- Tool 名・引数 https://github.com/ValLaboratory/ekispert-api-mcp-server-docs
"""

from __future__ import annotations

import json

from app.adapters.ekispert_transit import (
    MCP_URL,
    TOOL_SEARCH_ROUTES,
    EkispertTransit,
    _parse_routes,
    _tool_payload,
)

# ドキュメントの例に、乗換1回ぶんの2区間を足したもの
COURSE = {
    "ResultSet": {
        "Course": [
            {
                "Route": {
                    "transferCount": "1",
                    "timeOnBoard": "31",
                    "Line": [
                        {
                            "Name": "ＪＲ京浜東北線",
                            "timeOnBoard": "20",
                            "DepartureState": {"Datetime": "2026-09-06T11:21:00+09:00"},
                            "ArrivalState": {"Datetime": "2026-09-06T11:41:00+09:00"},
                        },
                        {
                            "Name": "りんかい線",
                            "DepartureState": {"Datetime": "2026-09-06T11:49:00+09:00"},
                            "ArrivalState": {"Datetime": "2026-09-06T12:00:00+09:00"},
                        },
                    ],
                    "Point": [
                        {"Station": {"Name": "横浜"}},
                        {"Station": {"Name": "新木場"}},
                        {"Station": {"Name": "国際展示場"}},
                    ],
                },
                "Price": [
                    {"kind": "Fare", "Oneway": "500"},
                    {"kind": "Charge", "Oneway": "0"},
                ],
            }
        ]
    }
}


def test_parses_the_documented_course_shape():
    routes = _parse_routes(COURSE)
    assert len(routes) == 1
    legs = routes[0]
    assert [(s.from_station, s.to_station) for s in legs] == [
        ("横浜", "新木場"),
        ("新木場", "国際展示場"),
    ]
    assert legs[0].line == "ＪＲ京浜東北線"
    assert legs[0].minutes == 20  # timeOnBoard をそのまま
    assert legs[1].minutes == 11  # 無ければ発着時刻の差から出す
    # 運賃は経路単位でしか返らないので先頭区間に寄せる（合計は変わらない）
    assert sum(s.fare_yen for s in legs) == 500


def test_single_leg_comes_back_as_an_object_not_a_list():
    """駅すぱあとは要素が1つだと配列にしない。ここで落ちると経路が0本になる。"""
    single = {
        "ResultSet": {
            "Course": {
                "Route": {
                    "Line": {"Name": "ＪＲ中央線快速", "timeOnBoard": "7"},
                    "Point": [{"Station": {"Name": "高円寺"}}, {"Station": {"Name": "新宿"}}],
                },
                "Price": {"kind": "Fare", "Oneway": "160"},
            }
        }
    }
    legs = _parse_routes(single)[0]
    assert len(legs) == 1
    assert (legs[0].from_station, legs[0].to_station) == ("高円寺", "新宿")
    assert legs[0].fare_yen == 160


def test_no_equipment_fields_are_invented():
    """EV・階段・ロッカーは API に無いので、区間にも持たせない。"""
    leg = _parse_routes(COURSE)[0][0]
    for absent in ("has_elevator", "stairs"):
        assert not hasattr(leg, absent), f"{absent} が復活している"


def test_tool_payload_reads_the_text_content_form():
    """構造化出力が無い場合、content[].text の JSON を読む。"""
    result = {"content": [{"type": "text", "text": json.dumps(COURSE)}]}
    assert _tool_payload(result) == COURSE


def test_broken_payloads_yield_no_routes_instead_of_raising():
    assert _parse_routes(None) == []
    assert _parse_routes({}) == []
    assert _parse_routes({"ResultSet": {"Course": [{"Route": {}}]}}) == []


def test_tool_name_matches_the_documentation():
    assert TOOL_SEARCH_ROUTES == "ekispert_api_search_routes"


def test_auth_header_matches_the_documentation():
    """Bearer ではなく専用ヘッダ。ここを間違えると全リクエストが弾かれる。"""
    headers = EkispertTransit("https://api-mcp.ekispert.jp/mcp", "KEY")._headers()
    assert headers["ekispert-api-access-key"] == "KEY"
    assert headers["ekispert-api-response-format"] == "json"
    assert "Authorization" not in headers
    # Streamable HTTP は SSE でも返るので、両方受けると宣言しておく
    assert "text/event-stream" in headers["Accept"]


def test_station_names_drop_the_trailing_suffix():
    """利用者は「横浜駅」と書くが、マスタは「横浜」。落とさないと 400 になる。"""
    from app.adapters.ekispert_transit import _station

    assert _station("横浜駅") == "横浜"
    assert _station(" 国際展示場 ") == "国際展示場"
    assert _station("駅") == "駅"  # 1文字は削らない


def test_http_logging_never_carries_the_access_key():
    """httpx の INFO ログは URL を丸ごと出す。キーをクエリで渡す API を足したとき、
    ここを塞いでいないとキーが平文でログに残る（一度そうなった）。"""
    import logging

    import app.main  # noqa: F401  — ここで logging の設定が走る

    assert logging.getLogger("httpx").level >= logging.WARNING


async def test_unfound_route_is_marked_as_an_estimate_not_passed_off_as_real(monkeypatch):
    """駅名は自由入力。打ち間違いで駅すぱあとが引けないとき、目安の経路を本物に見せない。"""
    from datetime import datetime, timezone

    from app.agents.route import RouteAgent
    from app.adapters.stub_llm import StubLlm
    from app.domain.models import LuggageMode

    transit = EkispertTransit("https://api-mcp.ekispert.jp/mcp", "KEY")

    async def nothing(tool, args):
        return None

    monkeypatch.setattr(transit, "_call", nothing)
    plan = await RouteAgent(transit, StubLlm()).plan_outbound(
        from_station="横浜",
        to_station="おおみや",
        arrive_by=datetime(2026, 8, 15, 4, 0, tzinfo=timezone.utc),
        mode=LuggageMode.CARRY,
    )
    assert plan.segments and all(seg.estimated for seg in plan.segments)
    assert "おおみや" in plan.warnings[0] and "駅名を確かめて" in plan.warnings[0]


STATIONS = {
    "ResultSet": {
        "Point": [
            {"Station": {"code": "21987", "Name": "大宮(埼玉県)", "Type": "train"}, "Prefecture": {"Name": "埼玉県"}},
            {"Station": {"code": "25616", "Name": "大宮(京都府)", "Type": "train"}, "Prefecture": {"Name": "京都府"}},
        ]
    }
}


def test_station_candidates_are_read_from_get_stations():
    from app.adapters.ekispert_transit import TOOL_GET_STATIONS, _parse_station_names

    assert TOOL_GET_STATIONS == "ekispert_api_get_stations"
    assert _parse_station_names(STATIONS) == ["大宮(埼玉県)", "大宮(京都府)"]
    # 1件だと配列ではなくオブジェクトで返る
    single = {"ResultSet": {"Point": STATIONS["ResultSet"]["Point"][0]}}
    assert _parse_station_names(single) == ["大宮(埼玉県)"]
    assert _parse_station_names(None) == []


async def test_ambiguous_station_names_its_candidates_in_the_warning(monkeypatch):
    """「大宮」は埼玉と京都にあり、駅すぱあとは探索を断る。選び直せる候補を添える。"""
    from datetime import datetime, timezone

    from app.adapters.stub_llm import StubLlm
    from app.agents.route import RouteAgent
    from app.domain.models import LuggageMode

    transit = EkispertTransit("https://api-mcp.ekispert.jp/mcp", "KEY")
    calls = []

    async def fake(tool, args):
        calls.append(tool)
        return STATIONS if tool == "ekispert_api_get_stations" else None

    monkeypatch.setattr(transit, "_call", fake)
    plan = await RouteAgent(transit, StubLlm()).plan_outbound(
        from_station="大宮",
        to_station="国際展示場",
        arrive_by=datetime(2026, 8, 15, 1, 0, tzinfo=timezone.utc),
        mode=LuggageMode.CARRY,
    )
    assert "大宮(埼玉県)・大宮(京都府)" in plan.warnings[0]
    # 候補は覚えておき、同じ名前で何度も聞かない
    before = calls.count("ekispert_api_get_stations")
    assert await transit.suggest_stations("大宮駅") == ["大宮(埼玉県)", "大宮(京都府)"]
    assert calls.count("ekispert_api_get_stations") == before


async def test_romaji_station_is_retried_with_its_only_candidate(monkeypatch):
    """英語の画面からは「Yokohama」と書かれる。探索は断られても、候補が1つなら正式名で探し直す。"""
    transit = EkispertTransit("https://api-mcp.ekispert.jp/mcp", "KEY")
    searched = []

    async def fake(tool, args):
        if tool == "ekispert_api_get_stations":
            name = {"Yokohama": "横浜"}.get(args["name"])
            return {"ResultSet": {"Point": {"Station": {"Name": name}}}} if name else {"ResultSet": {}}
        if tool == "ekispert_api_search_routes":
            searched.append(args["viaList"])
            return COURSE if args["viaList"] == "横浜:国際展示場" else None
        return None

    monkeypatch.setattr(transit, "_call", fake)
    routes = await transit.search(from_station="Yokohama", to_station="国際展示場")
    assert routes and not any(seg.estimated for seg in routes[0])
    assert searched[-1] == "横浜:国際展示場"
