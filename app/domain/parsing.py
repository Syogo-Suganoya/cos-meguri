"""チャットの自由文から遠征の条件を読み取る（LLM を使わない実装）。

Gemini が使えるときは LLM 側の抽出を優先するが、落ちても会話が止まらないよう
ここで最低限を埋める。逆に言うと、ここで拾える範囲は「イベント名・日付・
出発駅・荷物量・作品/キャラ」に限る。凝った言い回しは LLM に任せる。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from app.domain.models import JST, LuggageMode, event_day

# イベントIDごとの呼ばれ方（正式名称はマスタ側から渡ってくる）
_EVENT_ALIASES: dict[str, list[str]] = {
    "comiket": ["コミケ", "コミックマーケット", "comiket", "c105", "ビッグサイト"],
    "acosta": ["アコスタ", "acosta", "池袋", "ハレザ"],
    "wcs": ["世界コスプレサミット", "コスサミ", "wcs", "world cosplay summit", "大須"],
    "hokokos": ["ホココス", "hokokos", "栄"],
}

_LUGGAGE_ALIASES: list[tuple[LuggageMode, list[str]]] = [
    (LuggageMode.HEAVY, ["大荷物", "大道具", "ウィッグケース", "キャリー2", "たくさん", "heavy"]),
    (LuggageMode.CARRY, ["キャリー", "スーツケース", "carry"]),
    (LuggageMode.LIGHT, ["手ぶら", "手荷物", "身軽", "light"]),
]

# 「〜から」「〜駅から」の直前を出発駅とみなす。
# 駅名の文字種からひらがなを外しているのは、直前の助詞（「〜に」「〜の」）まで
# 巻き込んで拾ってしまうため。「つくば」のような平仮名だけの駅名は拾えないが、
# そこは LLM 側の抽出に任せる。
_STATION = r"[一-龥ァ-ヶA-Za-z0-9ー]{2,10}"
_ORIGIN_PATTERNS = [
    re.compile(rf"({_STATION})駅(?:から|より|発)"),
    re.compile(rf"({_STATION})から(?:行|出発|向か)"),
    re.compile(rf"出発(?:駅|地)?は({_STATION})"),
]

# 「作品名の キャラ名」「作品名:〜 キャラ:〜」
_CHARACTER_PATTERNS = [
    re.compile(r"作品[名:：]?\s*(?:は)?\s*([^\s、。,]+).{0,8}?キャラ(?:名|クター)?[:：]?\s*(?:は)?\s*([^\s、。,]+)"),
    re.compile(r"([^\s、。,]{2,20})の([^\s、。,]{2,20})(?:のコス|で参加|をやり|になり)"),
]


def _parse_day(text: str, *, now: datetime | None = None) -> datetime | None:
    """日付を JST の0時として返す。年の指定が無ければ直近の未来を採る。"""
    now = (now or datetime.now(JST)).astimezone(JST)

    if "明後日" in text:
        return event_day(now + timedelta(days=2))
    if "明日" in text:
        return event_day(now + timedelta(days=1))
    if "今日" in text:
        return event_day(now)

    full = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", text)
    if full:
        year, month, day = (int(g) for g in full.groups())
        try:
            return datetime(year, month, day, tzinfo=JST)
        except ValueError:
            return None

    partial = re.search(r"(?<!\d)(\d{1,2})[/月](\d{1,2})日?", text)
    if partial:
        month, day = (int(g) for g in partial.groups())
        for year in (now.year, now.year + 1):
            try:
                candidate = datetime(year, month, day, tzinfo=JST)
            except ValueError:
                return None
            if candidate >= event_day(now):
                return candidate
    return None


def _parse_event(text: str, known_events: list[dict]) -> str | None:
    lowered = text.lower()
    for event in known_events:
        event_id = str(event.get("event_id", ""))
        names = [event.get("name", ""), event.get("name_en", ""), event_id]
        names += _EVENT_ALIASES.get(event_id, [])
        for name in names:
            if name and str(name).lower() in lowered:
                return event_id
    return None


def _parse_luggage(text: str) -> LuggageMode | None:
    lowered = text.lower()
    for mode, aliases in _LUGGAGE_ALIASES:
        if any(alias.lower() in lowered for alias in aliases):
            return mode
    return None


def _parse_origin(text: str) -> str | None:
    for pattern in _ORIGIN_PATTERNS:
        found = pattern.search(text)
        if found:
            return found.group(1)
    return None


def _parse_character(text: str) -> tuple[str | None, str | None]:
    for pattern in _CHARACTER_PATTERNS:
        found = pattern.search(text)
        if found:
            return found.group(1), found.group(2)
    return None, None


def extract_slots(
    text: str, known_events: list[dict], *, now: datetime | None = None
) -> dict:
    """読み取れた項目だけを持つ辞書を返す。読めない項目はキーごと入れない。"""
    slots: dict = {}

    event_id = _parse_event(text, known_events)
    if event_id:
        slots["event_id"] = event_id

    day = _parse_day(text, now=now)
    if day:
        slots["day"] = day.isoformat()

    origin = _parse_origin(text)
    if origin:
        slots["origin_station"] = origin

    luggage = _parse_luggage(text)
    if luggage:
        slots["luggage_mode"] = luggage.value

    title, character = _parse_character(text)
    if title and character:
        slots["title"] = title
        slots["character"] = character

    return slots
