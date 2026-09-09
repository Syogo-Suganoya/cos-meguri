"""多言語エージェント（設計書 §4）。

UI 文言は辞書、生成物（メイク工程・案内文）は生成時に母語で出す。
辞書に無い言語は英語へフォールバックし、機能そのものは落とさない。
MVP は日英。中韓は _STRINGS に列を足すだけで有効になる。
"""

from __future__ import annotations

from app.domain.models import Lang
from app.ports.llm import LlmPort

_STRINGS: dict[str, dict[str, str]] = {
    "app.title": {"ja": "コスめぐり", "en": "Cos-Meguri"},
    "plan.ready": {"ja": "遠征プランができました", "en": "Your expedition plan is ready"},
    "makeup.heading": {"ja": "メイク工程", "en": "Makeup steps"},
    "makeup.personalized": {"ja": "この工程の個別化理由", "en": "Why this step is personalised"},
    "route.heading": {"ja": "大荷物モードの動線", "en": "Route (heavy-luggage mode)"},
    "route.penalty": {"ja": "荷物ぶんの上乗せ", "en": "Added for luggage"},
    "dressing.heading": {"ja": "更衣室の混雑予測", "en": "Changing-room forecast"},
    "dressing.estimate": {
        "ja": "実測ではなくモデル値です",
        "en": "Model estimate, not measured data",
    },
    "dressing.entry": {"ja": "入場のおすすめ", "en": "Suggested entry"},
    "dressing.exit": {"ja": "撤収のおすすめ", "en": "Suggested exit"},
    "awase.heading": {"ja": "合わせの進捗", "en": "Group progress"},
    "awase.proposal": {"ja": "時間の変更案（主催者の返事待ち）", "en": "Reschedule proposal (awaiting organiser)"},
    "privacy.note": {
        "ja": "顔画像は解析後に破棄しました。保持しているのは数値スコアのみです。",
        "en": "The face image was discarded after analysis. Only numeric scores are kept.",
    },
    "location.note": {
        "ja": "位置共有はイベント当日のみ有効で、終了24時間後に自動削除されます。",
        "en": "Location sharing is day-only and is deleted automatically 24h after the event.",
    },
}

_FALLBACK_NOTES = {
    "ja": (
        "更衣室は当日の受付順です。会場内は衣装のまま移動できますが、"
        "外へ出るときは上着を羽織ってください。撮影は許可エリア内のみです。"
    ),
    "en": (
        "Changing rooms are first-come on the day. You can move around the venue in costume, "
        "but cover up before going outside. Photography is allowed only in permitted areas."
    ),
}


def t(key: str, lang: Lang) -> str:
    """UI 文言を引く。未収載の言語は英語へ落とす。"""
    entry = _STRINGS.get(key)
    if not entry:
        return key
    return entry.get(lang.value) or entry.get("en") or key


def supported_langs() -> list[dict[str, str]]:
    """UI に出す言語一覧。辞書が揃っている言語だけを有効として返す。"""
    out = []
    for lang in Lang:
        ready = all(lang.value in entry for entry in _STRINGS.values())
        out.append({"code": lang.value, "label": lang.label, "ready": str(ready).lower()})
    return out


class I18nAgent:
    """イベント慣習・更衣室ルールの文化的補足を母語で生成する。"""

    def __init__(self, llm: LlmPort) -> None:
        self.llm = llm

    async def cultural_note(self, event_name: str, lang: Lang) -> str:
        fallback = _FALLBACK_NOTES.get(lang.value, _FALLBACK_NOTES["en"])
        return await self.llm.cultural_note(event_name, lang=lang.value, fallback=fallback)

    def ui_strings(self, lang: Lang) -> dict[str, str]:
        return {key: t(key, lang) for key in _STRINGS}
