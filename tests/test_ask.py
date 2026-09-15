"""「相談」ページの検証。欄を埋めていくとプランが立ち上がるまでを見る。"""

from __future__ import annotations

from datetime import datetime

from app.domain.models import JST
from tests.conftest import DAY

FULL = {
    "event_id": "comiket",
    "day": DAY.isoformat(),
    "title": "作品A",
    "character": "キャラB",
    "origin_station": "横浜",
    "luggage_mode": "heavy",
}


def test_missing_fields_are_named_until_everything_is_filled(user):
    res = user.patch("/api/chat/slots", json={"event_id": "comiket", "origin_station": "横浜"})
    assert res.status_code == 200
    body = res.json()
    assert body["is_complete"] is False
    assert body["missing"] == ["day", "title", "character"]  # 荷物は既定で埋まっている
    assert body["exp_id"] is None
    assert "expedition" not in body


def test_filling_the_last_field_builds_the_plan(user):
    user.patch("/api/chat/slots", json={k: v for k, v in FULL.items() if k != "character"})
    body = user.patch("/api/chat/slots", json={"character": "キャラB"}).json()

    assert body["is_complete"] is True
    assert body["exp_id"]
    assert body["expedition"]["exp_id"] == body["exp_id"]
    assert body["expedition"]["makeup"]["steps"]
    # 設計書 §7-4: キャラ情報は外向き応答に出さない
    assert "character" not in body["expedition"]

    # ページを開き直しても、同じ条件とプランが戻ってくる
    again = user.get("/api/chat").json()
    assert again["exp_id"] == body["exp_id"]
    assert again["is_complete"] is True


def test_plan_matches_the_event_calendar(user):
    """開場・閉場は JST。UTC の日付を送っても会場の日付がずれない。"""
    exp = user.patch("/api/chat/slots", json=FULL).json()["expedition"]
    assert exp["event_date"] == "2026-08-15"


def test_clearing_a_field_makes_it_missing_again(user):
    user.patch("/api/chat/slots", json=FULL)
    body = user.patch("/api/chat/slots", json={"origin_station": ""}).json()
    assert body["is_complete"] is False
    assert body["missing"] == ["origin_station"]


def test_conditions_are_private_to_each_layer(user, login):
    user.patch("/api/chat/slots", json=FULL)
    stranger = login("別の人")
    theirs = stranger.get("/api/chat").json()
    assert theirs["slots"]["event_id"] is None
    assert theirs["exp_id"] is None


def test_free_text_entry_is_gone(user):
    """自由文の入口は取り下げた。残っていると、画面に無い経路で条件が変わる。"""
    assert user.post("/api/chat", json={"message": "コミケに行きます"}).status_code == 405
    assert user.post("/api/chat/reset", json={}).status_code == 404


def test_event_can_be_written_by_its_common_name(user):
    """イベント名は自由入力。略称・全角・余計な語がついていても収載イベントに当たる。"""
    for text, expected in [("コミケ", "comiket"), ("ＡＣＯＳＴＡ！", "acosta"), ("コミケ105", "comiket"), ("コスサミ", "wcs")]:
        body = user.patch("/api/chat/slots", json={"event_name": text}).json()
        assert body["slots"]["event_id"] == expected, text


LOCAL = {
    "event_name": "地元の撮影会",
    "day": DAY.isoformat(),
    "destination_station": "大宮",
    "starts_time": "13:00",
    "ends_time": "17:00",
    "title": "作品A",
    "character": "キャラB",
    "origin_station": "横浜",
    "luggage_mode": "carry",
}


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_local_event_not_in_the_master_can_be_planned(user):
    """収載に無いイベントも、目的地と開始・終了を入れれば組める。"""
    body = user.patch("/api/chat/slots", json=LOCAL).json()
    assert body["is_complete"] is True
    assert body["slots"]["event_id"] is None

    exp = body["expedition"]
    assert exp["event"]["name"] == "地元の撮影会"
    assert exp["event"]["event_id"] == "custom"
    assert exp["event"]["station"] == "大宮"
    starts, ends = _dt(exp["event"]["starts_at"]), _dt(exp["event"]["ends_at"])
    assert (starts.astimezone(JST).hour, ends.astimezone(JST).hour) == (13, 17)

    outbound, inbound = exp["routes"]["outbound"], exp["routes"]["return"]
    assert outbound["segments"][-1]["to_station"] == "大宮"
    assert inbound["segments"][0]["from_station"] == "大宮"
    assert _dt(outbound["arrive_at"]) <= starts
    assert _dt(inbound["depart_at"]) >= ends


def test_destination_and_times_are_required(user):
    body = user.patch("/api/chat/slots", json={"event_name": "地元の撮影会"}).json()
    assert body["missing"][:5] == ["day", "destination_station", "starts_time", "ends_time", "title"]


def test_known_event_fills_destination_and_times(user):
    body = user.patch("/api/chat/slots", json={"event_name": "コミケ"}).json()
    s = body["slots"]
    assert (s["event_id"], s["event_name"]) == ("comiket", "コミケ")
    assert (s["destination_station"], s["starts_time"], s["ends_time"]) == ("国際展示場", "10:00", "16:00")


def test_times_written_on_the_screen_win_over_the_master(user):
    """コミケでも日によって時刻が違う。欄に書いた値を優先する。"""
    body = user.patch("/api/chat/slots", json={**FULL, "event_id": None, "event_name": "コミケ", "starts_time": "11:00", "ends_time": ""}).json()
    s = body["slots"]
    assert (s["starts_time"], s["ends_time"]) == ("11:00", "16:00")  # 空で送った欄だけ埋まる
    assert _dt(body["expedition"]["routes"]["outbound"]["arrive_at"]).astimezone(JST).hour <= 11


def test_switching_to_another_known_event_swaps_destination_and_times(user):
    user.patch("/api/chat/slots", json={"event_name": "コミケ"})
    s = user.patch("/api/chat/slots", json={"event_name": "acosta!"}).json()["slots"]
    assert (s["event_id"], s["destination_station"], s["starts_time"], s["ends_time"]) == ("acosta", "池袋", "10:00", "17:00")


def test_end_before_start_is_refused_on_the_end_field(user):
    user.patch("/api/chat/slots", json={**LOCAL, "ends_time": "17:00"})
    res = user.patch("/api/chat/slots", json={"starts_time": "18:00"})
    assert res.status_code == 422
    assert res.json()["detail"]["field"] == "ends_time"
    # 誤った時刻は保存しない
    assert user.get("/api/chat").json()["slots"]["starts_time"] == "13:00"


def test_times_must_be_hh_mm(user):
    assert user.patch("/api/chat/slots", json={"starts_time": "9時"}).status_code == 422
    assert user.patch("/api/chat/slots", json={"starts_time": ""}).status_code == 200


def test_clearing_the_event_name_clears_the_event(user):
    user.patch("/api/chat/slots", json={"event_name": "コミケ"})
    body = user.patch("/api/chat/slots", json={"event_name": ""}).json()
    assert body["slots"]["event_id"] is None
    assert "event_name" in body["missing"]
