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
    REST_DISRUPTIONS,
    TOOL_SEARCH_ROUTES,
    EkispertTransit,
    _normalize_line,
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


# ---- 運行情報（REST。MCP に Tool が無いので直接叩く） ----

DISRUPTIONS = {
    "ResultSet": {
        "Information": [
            {
                "status": "列車遅延",
                "Line": {"code": "1", "Name": "ＪＲ京浜東北線"},
                "Title": "人身事故の影響で遅れています",
            },
            {
                "status": "平常運転",
                "Line": {"code": "2", "Name": "りんかい線"},
                "Title": "",
            },
            {
                "status": "運転見合わせ",
                "Line": {"code": "3", "Name": "無関係な線"},
                "Title": "強風のため",
            },
        ]
    }
}


def test_only_the_lines_on_my_route_are_reported(monkeypatch):
    """全国ぶんが返るので、乗る予定の路線だけに絞る。"""
    import asyncio

    adapter = EkispertTransit(MCP_URL, "KEY")

    async def fake_get(url, params):
        assert url == REST_DISRUPTIONS
        assert params["key"] == "KEY"
        return DISRUPTIONS

    monkeypatch.setattr(adapter, "_get_json", fake_get)
    found = asyncio.run(adapter.disruptions(["JR京浜東北線", "りんかい線"]))

    # 平常運転は落とし、経路に無い「無関係な線」も拾わない
    assert [d.line for d in found] == ["ＪＲ京浜東北線"]
    assert found[0].delay_minutes == 15
    assert "人身事故" in found[0].detail
    # 引けたので、画面は「乱れなし」と言い切ってよい
    assert adapter.supports_disruptions is True


def test_line_names_match_across_full_width_letters():
    """「ＪＲ」と「JR」を別物にすると、遅延を取りこぼす。"""
    assert _normalize_line("ＪＲ京浜東北線") == _normalize_line("JR京浜東北線")


def test_unavailable_disruptions_are_not_reported_as_calm(monkeypatch):
    """レスキューナウが契約外のとき、「乱れなし」と言わせない。"""
    import asyncio

    adapter = EkispertTransit(MCP_URL, "KEY")

    async def fails(url, params):
        return None

    monkeypatch.setattr(adapter, "_get_json", fails)
    assert asyncio.run(adapter.disruptions(["JR線"])) == []
    assert adapter.supports_disruptions is False


def test_station_names_drop_the_trailing_suffix():
    """利用者は「横浜駅」と書くが、マスタは「横浜」。落とさないと 400 になる。"""
    from app.adapters.ekispert_transit import _station

    assert _station("横浜駅") == "横浜"
    assert _station(" 国際展示場 ") == "国際展示場"
    assert _station("駅") == "駅"  # 1文字は削らない


def test_http_logging_never_carries_the_access_key():
    """駅すぱあとの REST はキーをクエリでしか受けない。httpx の INFO ログが
    URL を丸ごと出すので、そこを塞いでいないとキーが平文でログに残る。"""
    import logging

    import app.main  # noqa: F401  — ここで logging の設定が走る

    assert logging.getLogger("httpx").level >= logging.WARNING
