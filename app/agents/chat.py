"""チャットエージェント。自由文の相談から遠征プランまでを1本の会話で運ぶ。

やっていることは素朴なスロットフィリング:
1. 発話から条件（イベント・日付・作品/キャラ・出発駅・荷物）を抜き出す
2. 足りない項目を1つずつ聞き返す
3. 揃ったら Orchestrator に渡してプランを組み、結果を要約して返す

Gemini があれば抽出精度が上がるだけで、無くてもキーワード抽出で最後まで進む。
LLM に「次に何を聞くか」を委ねないのは、聞き漏らしと堂々巡りを避けるため。
"""

from __future__ import annotations

from datetime import datetime

from app.agents.orchestrator import Orchestrator, PlanRequest
from app.domain.events import get_event, list_events
from app.domain.models import (
    CharacterRef,
    ChatMessage,
    ChatRole,
    ChatSession,
    ChatSlots,
    JST,
    Lang,
    Layer,
    LuggageMode,
    jst_hm,
)
from app.ports.llm import LlmPort
from app.ports.repository import RepositoryPort

# 足りない項目を聞き返す文面
_PROMPTS: dict[str, dict[str, str]] = {
    "event_id": {
        "ja": "どのイベントですか？（コミケ / acosta / 世界コスプレサミット / ホココス）",
        "en": "Which event? (Comic Market / acosta! / World Cosplay Summit / Hokokos)",
    },
    "day": {
        "ja": "開催日はいつですか？（例: 9/6、2026-09-06）",
        "en": "Which date? (e.g. 9/6 or 2026-09-06)",
    },
    "title": {
        "ja": "作品名を教えてください。メイク工程の生成にだけ使い、共有文には残しません。",
        "en": "Which series? It is used only to build your makeup steps, never in shared text.",
    },
    "character": {
        "ja": "キャラクター名を教えてください。",
        "en": "Which character?",
    },
    "origin_station": {
        "ja": "出発駅はどこですか？（例: 横浜駅から）",
        "en": "Which station are you leaving from?",
    },
    "luggage_mode": {
        "ja": "荷物はどのくらいですか？（手荷物のみ / キャリー1個 / キャリー＋ウィッグ＋大道具）",
        "en": "How much luggage? (hand luggage only / one suitcase / suitcase + wig + props)",
    },
}

_GREETING = {
    "ja": "遠征の予定を教えてください。イベント・日付・キャラ・出発駅・荷物が揃えば、一日ぶんを組み立てます。",
    "en": "Tell me about your trip. With the event, date, character, origin station and luggage, I'll build your whole day.",
}


class ChatAgent:
    def __init__(
        self,
        orchestrator: Orchestrator,
        llm: LlmPort,
        repository: RepositoryPort,
    ) -> None:
        self.orchestrator = orchestrator
        self.llm = llm
        self.repository = repository

    async def history(self, layer: Layer) -> ChatSession:
        session = await self.repository.get_chat(layer.layer_id)
        if session is None:
            session = ChatSession(layer_id=layer.layer_id, lang=layer.lang)
            session.messages.append(
                ChatMessage(role=ChatRole.AGENT, text=_text(_GREETING, layer.lang))
            )
            # 既定値として、プロフィールの荷物設定を先に埋めておく
            session.slots.luggage_mode = layer.prefs.luggage_mode
            await self.repository.save_chat(session)
        return session

    async def send(self, layer: Layer, text: str) -> ChatSession:
        """1往復進める。プランが組めた場合は session.exp_id が埋まる。"""
        session = await self.history(layer)
        session.lang = layer.lang
        session.messages.append(ChatMessage(role=ChatRole.USER, text=text))

        extracted = await self.llm.extract_slots(text, known_events=_event_catalog())
        session.slots = _merge(session.slots, extracted)

        if session.slots.is_complete:
            reply = await self._build_plan(layer, session)
        else:
            reply = self._ask_next(session)

        session.messages.append(ChatMessage(role=ChatRole.AGENT, text=reply))
        return await self.repository.save_chat(session)

    def _ask_next(self, session: ChatSession) -> str:
        missing = session.slots.missing()
        filled = _filled_summary(session.slots, session.lang)
        question = _text(_PROMPTS[missing[0]], session.lang)
        if not filled:
            return question
        remaining = len(missing) - 1
        tail = (
            f"（残り{remaining}項目）" if session.lang is Lang.JA else f" ({remaining} more to go)"
        )
        return f"{filled}\n{question}{tail if remaining else ''}"

    async def _build_plan(self, layer: Layer, session: ChatSession) -> str:
        slots = session.slots
        req = PlanRequest(
            layer_id=layer.layer_id,
            event_id=slots.event_id,
            day=slots.day,
            character=CharacterRef(title=slots.title, name=slots.character),
            origin_station=slots.origin_station,
            luggage_mode=slots.luggage_mode or LuggageMode.CARRY,
            lang=layer.lang,
        )
        exp, extras = await self.orchestrator.plan(req)
        session.exp_id = exp.exp_id

        route = exp.routes.get("outbound")
        dressing = exp.dressing
        if layer.lang is Lang.JA:
            lines = [
                f"{exp.event.name}（{exp.event.venue}）の一日を組みました。",
                f"・メイク {exp.makeup.total_minutes}分／{len(exp.makeup.steps)}工程"
                f"（Fitzpatrick {exp.makeup.fitzpatrick_type.value} と顔属性で個別化）",
            ]
            if route and route.depart_at:
                lines.append(
                    f"・出発 {jst_hm(route.depart_at)}／体感 {route.effective_minutes}分"
                    f"（荷物ぶん +{route.penalty_minutes}分）"
                )
            if dressing and dressing.recommended_entry:
                lines.append(
                    f"・更衣室は {jst_hm(dressing.recommended_entry)} 入場、"
                    f"{jst_hm(dressing.recommended_exit)} 撤収がおすすめ（モデル推定）"
                )
            if extras.get("wake_up_hint"):
                lines.append(f"・{extras['wake_up_hint']}")
            lines.append("右の「当日の組み立て」で工程と動線を確認できます。")
            return "\n".join(lines)

        lines = [
            f"Your day at {exp.event.name} ({exp.event.venue}) is ready.",
            f"- Makeup: {exp.makeup.total_minutes} min over {len(exp.makeup.steps)} steps "
            f"(personalised for Fitzpatrick {exp.makeup.fitzpatrick_type.value} and your facial ratios)",
        ]
        if route and route.depart_at:
            lines.append(
                f"- Leave at {jst_hm(route.depart_at)}; {route.effective_minutes} min door-to-door "
                f"(+{route.penalty_minutes} min for luggage)"
            )
        if dressing and dressing.recommended_entry:
            lines.append(
                f"- Changing room: enter around {jst_hm(dressing.recommended_entry)}, "
                f"leave by {jst_hm(dressing.recommended_exit)} (model estimate)"
            )
        if extras.get("wake_up_hint"):
            lines.append(f"- {extras['wake_up_hint']}")
        return "\n".join(lines)

    async def reset(self, layer: Layer) -> ChatSession:
        """会話をやり直す。プランそのものは消さない。"""
        session = ChatSession(layer_id=layer.layer_id, lang=layer.lang)
        session.messages.append(
            ChatMessage(role=ChatRole.AGENT, text=_text(_GREETING, layer.lang))
        )
        session.slots.luggage_mode = layer.prefs.luggage_mode
        return await self.repository.save_chat(session)


# ---------------------------------------------------------------- 補助


def _event_catalog() -> list[dict]:
    return [
        {"event_id": e.event_id, "name": e.name, "name_en": e.name_en}
        for e in list_events()
    ]


def _text(table: dict[str, str], lang: Lang) -> str:
    return table.get(lang.value) or table["en"]


def _merge(slots: ChatSlots, extracted: dict) -> ChatSlots:
    """抽出結果を反映する。既に埋まっている項目も、新しい発話があれば上書きする。"""
    updated = slots.model_copy(deep=True)

    if event_id := extracted.get("event_id"):
        if get_event(str(event_id)):
            updated.event_id = str(event_id)

    if raw_day := extracted.get("day"):
        parsed = _parse_iso(str(raw_day))
        if parsed:
            updated.day = parsed

    for field in ("title", "character", "origin_station"):
        value = extracted.get(field)
        if isinstance(value, str) and value.strip():
            setattr(updated, field, value.strip())

    if raw_mode := extracted.get("luggage_mode"):
        try:
            updated.luggage_mode = LuggageMode(str(raw_mode))
        except ValueError:
            pass

    return updated


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=JST)


def _filled_summary(slots: ChatSlots, lang: Lang) -> str:
    """いま把握できている条件を短く返す。聞き返しの前に置いて、行き違いを防ぐ。"""
    parts: list[str] = []
    if slots.event_id and (event := get_event(slots.event_id)):
        parts.append(event.name if lang is Lang.JA else event.name_en)
    if slots.day:
        parts.append(f"{slots.day.astimezone(JST):%m/%d}")
    if slots.title and slots.character:
        parts.append(f"{slots.title} / {slots.character}")
    if slots.origin_station:
        parts.append(
            f"{slots.origin_station}発" if lang is Lang.JA else f"from {slots.origin_station}"
        )
    if slots.luggage_mode:
        parts.append(
            slots.luggage_mode.label if lang is Lang.JA else slots.luggage_mode.value
        )
    if not parts:
        return ""
    joined = " / ".join(parts)
    return f"承知しました（{joined}）。" if lang is Lang.JA else f"Got it ({joined})."
