"""自然文の解釈・説明生成・翻訳のポート（Gemini API）。

メイク工程の骨格は domain/makeup.py が LLM 抜きで決め切る。LLM の役割は
「言い回しを整える」「母語に落とす」「文化的な補足を足す」の3つに限る。
どのメソッドも失敗時は fallback を返し、LLM 不在でも全機能が動く。
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class LlmPort(ABC):
    name: str = "gemini"

    @abstractmethod
    async def interpret_character(self, title: str, name: str, *, lang: str = "ja") -> dict:
        """作品名・キャラ名から {hair_color, eye_color, features} を推定する。

        値は lang の言語で返す。ここで返した色名はメイク工程の文面へ
        そのまま埋め込まれるため、言語が混ざると工程文が壊れる。
        """

    @abstractmethod
    async def refine_steps(
        self, steps: list[str], *, lang: str, fallback: list[str]
    ) -> list[str]:
        """工程文を指定言語で整える。件数と順序は必ず維持する。"""

    @abstractmethod
    async def cultural_note(self, event_name: str, *, lang: str, fallback: str) -> str:
        """更衣室ルール・イベント慣習の文化的補足を母語で生成する。"""

    @abstractmethod
    async def explain(self, prompt: str, *, fallback: str) -> str:
        """混雑・動線の判断理由を短い文で説明する。"""

    @abstractmethod
    async def extract_slots(self, text: str, *, known_events: list[dict]) -> dict:
        """チャットの自由文から遠征の条件を抜き出す。

        返すのは {event_id, day(ISO8601), title, character, origin_station,
        luggage_mode} のうち読み取れたものだけ。読み取れない項目は含めない。
        LLM が使えない場合もキーワード一致で最低限は埋まること。
        """
