"""初期収載イベントのマスタ（設計書 §3「対応イベント」）。

外部データ連携は MVP スコープ外のため、まずは静的マスタで持つ。
マスタは「相談の欄を自動で埋める」ためのもので、ここに無いイベント（ローカルイベントなど）も
目的地（最寄り駅）と開始・終了を入れれば組める。
"""

from __future__ import annotations

import unicodedata

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


def event_defaults(event: EventMaster) -> dict[str, str]:
    """相談の欄に自動で入れる、目的地（最寄り駅）と開始・終了（HH:MM）。"""
    return {
        "destination_station": event.station,
        "starts_time": f"{event.opens_at_hour:02d}:00",
        "ends_time": f"{event.closes_at_hour:02d}:00",
    }


# 呼ばれ方。イベント名は自由に書いてもらい、ここで収載イベントに引き当てる。
# 正式名称・英語名・ID も同じように引けるので、ここには略称や通称だけを書く
_ALIASES: dict[str, list[str]] = {
    "comiket": ["コミケ", "comike", "ビッグサイト"],
    "acosta": ["アコスタ", "ハレザ"],
    "wcs": ["コスサミ", "wcs", "世界コスサミ"],
    "hokokos": ["ほこコス", "hokokos"],
}


def _normalize(text: str) -> str:
    """全角・半角と大文字・小文字、空白と記号の違いを均す。「ＡＣＯＳＴＡ！」も「acosta」になる。"""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in folded if ch.isalnum())


def find_event(text: str) -> EventMaster | None:
    """書かれたイベント名を収載イベントに引き当てる。当たらなければ None。

    まず呼び名と丸ごと一致するものを探し、無ければ「呼び名を含む」もので探す
    （「コミケ105」「acosta!池袋」のような書き方を拾うため）。
    """
    wanted = _normalize(text)
    if not wanted:
        return None

    names: list[tuple[str, EventMaster]] = []
    for event in EVENTS.values():
        for name in (event.name, event.name_en, event.event_id, *_ALIASES.get(event.event_id, [])):
            key = _normalize(name)
            if key:
                names.append((key, event))

    for key, event in names:
        if key == wanted:
            return event
    # 長い呼び名から試す。短い呼び名が別のイベント名の一部に紛れ込むのを避ける
    for key, event in sorted(names, key=lambda pair: len(pair[0]), reverse=True):
        if len(key) >= 3 and key in wanted:
            return event
    return None
