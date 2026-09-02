"""Gemini の代役。決定的な既定値を返し、常に fallback を尊重する。

「LLM が落ちてもサービスは落ちない」を担保するための実装でもある。
ここが返すものと Gemini が返すものは、契約上どちらも同じ形になる。
"""

from __future__ import annotations

from app.domain.parsing import extract_slots as keyword_slots
from app.ports.llm import LlmPort

# デモで使うキャラ像の既定値（作品名・キャラ名は内部入力に留まる）。
# 色名は工程文にそのまま埋まるので、言語ごとに持つ。
_HAIR_HINTS = {
    "ja": ["黒", "銀", "金", "赤", "青", "桃"],
    "en": ["black", "silver", "blonde", "red", "blue", "pink"],
}
_EYE_HINTS = {
    "ja": ["赤", "金", "碧", "紫", "琥珀", "翠"],
    "en": ["red", "gold", "blue", "violet", "amber", "green"],
}
_FEATURE_HINTS = {
    "ja": ["ハイライトの強い瞳", "はっきりした眉"],
    "en": ["strong catchlights in the eyes", "well-defined brows"],
}

_CULTURAL_NOTES = {
    "ja": (
        "更衣室は当日の受付順です。会場内の移動は衣装のまま可、"
        "会場外へ出る際は上着かコートを羽織ってください。撮影は許可エリア内のみです。"
    ),
    "en": (
        "Changing rooms are first-come on the day. You may move inside the venue in costume, "
        "but cover up with a coat before stepping outside. Shoot only in permitted areas."
    ),
}


class StubLlm(LlmPort):
    name = "llm:stub"

    async def interpret_character(self, title: str, name: str, *, lang: str = "ja") -> dict:
        seed = sum(ord(c) for c in f"{title}{name}") if (title or name) else 0
        hair = _HAIR_HINTS.get(lang, _HAIR_HINTS["en"])
        eye = _EYE_HINTS.get(lang, _EYE_HINTS["en"])
        return {
            "hair_color": hair[seed % len(hair)],
            "eye_color": eye[(seed // 3) % len(eye)],
            "features": list(_FEATURE_HINTS.get(lang, _FEATURE_HINTS["en"])),
        }

    async def refine_steps(
        self, steps: list[str], *, lang: str, fallback: list[str]
    ) -> list[str]:
        # 整形はしない。ルールベースの工程をそのまま通す
        return list(steps) if steps else list(fallback)

    async def cultural_note(self, event_name: str, *, lang: str, fallback: str) -> str:
        return _CULTURAL_NOTES.get(lang) or fallback

    async def explain(self, prompt: str, *, fallback: str) -> str:
        return fallback

    async def extract_slots(self, text: str, *, known_events: list[dict]) -> dict:
        return keyword_slots(text, known_events)
