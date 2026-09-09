"""Gemini API 実装（REST 直叩き）。

工程の骨格は domain/makeup.py が決めるので、ここは「整える・訳す・補足する」
だけを担う。応答が壊れていても必ず fallback を返し、上位に例外を漏らさない。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import httpx

from app.domain.models import JST
from app.domain.parsing import extract_slots as keyword_slots
from app.ports.llm import LlmPort

logger = logging.getLogger(__name__)

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_LANG_NAMES = {"ja": "Japanese", "en": "English", "zh": "Chinese", "ko": "Korean"}


class GeminiLlm(LlmPort):
    name = "gemini:live"

    def __init__(self, api_key: str, model: str = "gemini-3.7-flash", timeout: float = 20.0) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _generation_config(self, *, json_mode: bool) -> dict:
        """このアダプタの用途（言い換え・翻訳・短い説明）に合わせた設定。

        Gemini 3系は temperature / top_p / top_k を受け付けず、思考量は
        thinking_level（既定 medium）で指定する。ここでの仕事は工程文の
        言い換えと翻訳だけなので low で足りる（レイテンシと費用を抑える）。
        古いモデルを指定されたときは送らない（未知パラメータで弾かれるため）。
        """
        config: dict = {}
        if json_mode:
            config["response_mime_type"] = "application/json"
        if self.model.startswith("gemini-3"):
            # generationConfig の直下ではなく thinkingConfig の中。直下に置くと
            # 400 "Unknown name thinking_level" で全リクエストが落ちる
            config["thinkingConfig"] = {"thinkingLevel": "low"}
        return config

    async def _generate(self, prompt: str, *, json_mode: bool = False) -> str | None:
        payload: dict = {"contents": [{"parts": [{"text": prompt}]}]}
        config = self._generation_config(json_mode=json_mode)
        if config:
            payload["generationConfig"] = config
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(
                    _ENDPOINT.format(model=self.model),
                    # キーはヘッダで渡す。?key= にすると httpx が URL ごと
                    # INFO ログに出し、キーが平文でログに残る
                    headers={"x-goog-api-key": self.api_key},
                    json=payload,
                )
                res.raise_for_status()
                data = res.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except httpx.HTTPStatusError as exc:
            # 本文にはモデル名の誤りなど原因が入る。キーは URL に無いので安全
            logger.warning(
                "gemini %s: %s", exc.response.status_code, exc.response.text[:400]
            )
            return None
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            logger.warning("gemini call failed: %s", exc)
            return None

    async def interpret_character(self, title: str, name: str, *, lang: str = "ja") -> dict:
        target = _LANG_NAMES.get(lang, "English")
        prompt = (
            "次のキャラクターの外見的特徴を、メイク工程の生成に使う内部データとして"
            "JSONで返してください。キー: hair_color, eye_color, features(配列)。"
            "画像や公式素材は使わず、一般に知られた色味の記述だけを短く書いてください。"
            # 値は工程文へそのまま埋め込まれるため、言語を混ぜない
            f"値はすべて {target} で書いてください。\n"
            f"作品: {title}\nキャラクター: {name}"
        )
        raw = await self._generate(prompt, json_mode=True)
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return {
            "hair_color": parsed.get("hair_color"),
            "eye_color": parsed.get("eye_color"),
            "features": list(parsed.get("features") or [])[:5],
        }

    async def refine_steps(
        self, steps: list[str], *, lang: str, fallback: list[str]
    ) -> list[str]:
        if not steps:
            return list(fallback)
        target = _LANG_NAMES.get(lang, "English")
        prompt = (
            f"Rewrite each makeup step below in natural {target}, keeping the exact same "
            "count and order. Do not add, merge, drop, or reorder steps. Do not change the "
            "technical content — especially not any instruction about skin tone. "
            "Return a JSON array of strings only.\n\n"
            + json.dumps(steps, ensure_ascii=False)
        )
        raw = await self._generate(prompt, json_mode=True)
        if not raw:
            return list(fallback)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return list(fallback)
        # 件数が変わった応答は信用しない（工程の欠落を防ぐ）
        if isinstance(parsed, list) and len(parsed) == len(steps):
            return [str(s) for s in parsed]
        return list(fallback)

    async def cultural_note(self, event_name: str, *, lang: str, fallback: str) -> str:
        target = _LANG_NAMES.get(lang, "English")
        prompt = (
            f"In {target}, explain in 3 short sentences what a visiting cosplayer needs to know "
            f"about changing-room rules and on-site etiquette at the Japanese event "
            f"'{event_name}': queueing, moving in costume, and where photography is allowed. "
            "Plain sentences, no headings."
        )
        return (await self._generate(prompt)) or fallback

    async def explain(self, prompt: str, *, fallback: str) -> str:
        return (await self._generate(prompt)) or fallback

    async def extract_slots(self, text: str, *, known_events: list[dict]) -> dict:
        # LLM が落ちても会話が止まらないよう、キーワード抽出を土台に置く
        fallback = keyword_slots(text, known_events)
        catalog = json.dumps(
            [{"event_id": e.get("event_id"), "name": e.get("name")} for e in known_events],
            ensure_ascii=False,
        )
        prompt = (
            "コスプレ遠征の相談文から、次のキーをJSONで抜き出してください。"
            "読み取れないキーは省き、推測で埋めないこと。\n"
            "event_id（次の一覧から選ぶ）, day（ISO8601、日本時間）, title（作品名）, "
            "character（キャラ名）, origin_station（出発駅）, "
            "luggage_mode（light/carry/heavy のいずれか）\n"
            f"イベント一覧: {catalog}\n"
            f"本日: {datetime.now(JST).date().isoformat()}（日本時間）\n"
            f"相談文: {text}"
        )
        raw = await self._generate(prompt, json_mode=True)
        if not raw:
            return fallback
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return fallback
        if not isinstance(parsed, dict):
            return fallback

        allowed = {"event_id", "day", "title", "character", "origin_station", "luggage_mode"}
        merged = dict(fallback)
        # LLM が読み取れた項目で上書きする（空文字・null は無視）
        merged.update({k: v for k, v in parsed.items() if k in allowed and v})
        return merged
