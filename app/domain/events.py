"""初期収載イベントのマスタ（設計書 §3「対応イベント」）。

外部データ連携は MVP スコープ外のため、まずは静的マスタで持つ。
更衣室の収容・開場時間は混雑予測モデルの入力になる。
"""

from __future__ import annotations

from app.domain.models import EventMaster

EVENTS: dict[str, EventMaster] = {
    "wcs": EventMaster(
        event_id="wcs",
        name="世界コスプレサミット",
        name_en="World Cosplay Summit",
        venue="名古屋・大須",
        station="上前津",
        scale="large",
        style="street",
        dressing_rooms=3,
        dressing_capacity=90,
        opens_at_hour=9,
        closes_at_hour=18,
        notes_ja="市街地回遊型。会場間の移動が多く、更衣室は分散配置。海外参加者が多い。",
        notes_en=(
            "Street-style event across the Osu district. Changing rooms are split "
            "across venues; expect walking between spots in costume."
        ),
    ),
    "acosta": EventMaster(
        event_id="acosta",
        name="acosta!",
        name_en="acosta!",
        venue="池袋・ハレザ",
        station="池袋",
        scale="medium",
        style="street",
        dressing_rooms=2,
        dressing_capacity=70,
        opens_at_hour=10,
        closes_at_hour=17,
        notes_ja="高頻度開催。街歩き撮影が中心で、更衣室枠は午前に集中する。",
        notes_en="Frequent event. Street shooting; changing-room demand peaks in the morning.",
    ),
    "comiket": EventMaster(
        event_id="comiket",
        name="コミックマーケット",
        name_en="Comic Market",
        venue="東京ビッグサイト",
        station="国際展示場",
        scale="mega",
        style="hall",
        dressing_rooms=6,
        dressing_capacity=200,
        opens_at_hour=10,
        closes_at_hour=16,
        notes_ja="最大規模。更衣室は当日券＋行列。帰路も混雑するため撤収時刻の設計が要る。",
        notes_en=(
            "Largest scale. Changing rooms are same-day tickets with long queues; "
            "plan your exit time as carefully as your entry."
        ),
    ),
    "hokokos": EventMaster(
        event_id="hokokos",
        name="ホココス",
        name_en="Hokokos (Sakae street cosplay)",
        venue="名古屋・栄",
        station="栄",
        scale="medium",
        style="street",
        dressing_rooms=2,
        dressing_capacity=60,
        opens_at_hour=11,
        closes_at_hour=17,
        notes_ja="道路開放型。ロッカーが少なく、荷物預けの事前計画が効く。",
        notes_en="Open-road event. Few lockers — plan luggage drop-off in advance.",
    ),
}


def get_event(event_id: str) -> EventMaster | None:
    return EVENTS.get(event_id)


def list_events() -> list[EventMaster]:
    return list(EVENTS.values())
