"""キャラ再現メイクの工程分解（設計書 §4 メイクナビ）。

**キャラの色味と造形だけ**から、決定的なルールで工程を組み立てる。
Gemini は「言い回しを整える／母語に落とす」ためだけに後段で使い、
LLM が無くても全工程が出せるようにここを純粋関数で完結させる。

肌タイプ（Fitzpatrick）と顔比率による個別化は取り下げた。判定に使っていた
YouCam を外し、**測っていない数値で「あなたに合わせた」と言わない**ため。
そのぶん、工程文は「自分の肌で濃さを決める」前提の書き方に寄せてある。

守っている原則:
- 肌を明るく／暗く塗り替える指示は出さない。キャラの色味には光と影で寄せる
- 骨格を否定する表現を使わない。光と影の置き場所として書く
"""

from __future__ import annotations

from app.domain.models import (
    CharacterRef,
    Lang,
    MakeupArea,
    MakeupPlan,
    MakeupStep,
)

# 工程の並び順（塗り重ねの順序）
AREA_ORDER: list[MakeupArea] = [
    MakeupArea.BASE,
    MakeupArea.BROW,
    MakeupArea.CONTOUR,
    MakeupArea.HIGHLIGHT,
    MakeupArea.EYESHADOW,
    MakeupArea.EYELINE,
    MakeupArea.LENS,
    MakeupArea.LIP,
    MakeupArea.WIG_LINE,
]


class _Draft:
    """1工程の下書き。日英を同時に持ち、個別化の根拠を積む。"""

    def __init__(self, area: MakeupArea, ja: str, en: str, minutes: int = 3) -> None:
        self.area = area
        self.ja = ja
        self.en = en
        self.minutes = minutes
        self.reasons: list[str] = []

    def add(self, ja: str, en: str, reason: str, minutes: int = 0) -> "_Draft":
        self.ja += ja
        self.en += " " + en
        self.minutes += minutes
        self.reasons.append(reason)
        return self


# ---------------------------------------------------------------- 各工程


def _base(char: CharacterRef) -> _Draft:
    d = _Draft(
        MakeupArea.BASE,
        "素肌の色を活かしたまま、色ムラだけを整える下地を薄く伸ばす。",
        "Even out tone with a thin primer while keeping your own skin colour.",
        minutes=7,
    )
    d.add(
        "キャラの肌色にはベースの明るさではなく、後段のハイライトと影で寄せる。",
        "Match the character's tone with highlight and shadow later — not by changing your base shade.",
        reason="明度は変えない",
    )
    d.add(
        "撮影の照明で飛ばないよう、仕上げにフィックスミストを1プッシュ。",
        "Finish with one spray of setting mist so the base survives event lighting.",
        reason="屋内外の撮影を想定",
        minutes=1,
    )
    return d


def _brow(char: CharacterRef) -> _Draft:
    hair = char.hair_color or "ウィッグ"
    d = _Draft(
        MakeupArea.BROW,
        f"地眉をコンシーラーで潰し、{hair}に合わせた眉を描き直す。",
        f"Block out your natural brows with concealer, then redraw them to match the {char.hair_color or 'wig'} colour.",
        minutes=9,
    )
    d.add(
        "形はキャラの眉山の位置に合わせる。太さより、山をどこに置くかで印象が決まる。",
        "Match the arch position to the character — placement matters more than thickness.",
        reason="キャラの眉山に合わせる",
    )
    return d


def _contour() -> _Draft:
    d = _Draft(
        MakeupArea.CONTOUR,
        "頬骨下と輪郭に影を入れて、キャラの顔の形に寄せる。",
        "Shade under the cheekbones and along the jaw to move toward the character's face shape.",
        minutes=7,
    )
    d.add(
        "影色は自分の肌で試して選ぶ。濃さより、頬骨下の入れ始めの位置で決まる。",
        "Pick the shade against your own skin; where you start under the cheekbone matters more than depth.",
        reason="濃さより置き場所",
    )
    d.add(
        "鼻筋は眉頭から鼻先まで通さず、眉頭寄りの1/3に留めると自然に見える。",
        "Shade only the upper third of the nose bridge rather than the full length — it reads natural, not drawn-on.",
        reason="鼻の影は上1/3に限定",
        minutes=2,
    )
    return d


def _highlight() -> _Draft:
    d = _Draft(
        MakeupArea.HIGHLIGHT,
        "頬骨の上・鼻先・唇の山に光を置く。",
        "Place light on the top of the cheekbones, the nose tip and the cupid's bow.",
        minutes=5,
    )
    d.add(
        "眉下と目頭にも小さく置くと、目元に立体が出る。量より置き場所で効かせる。",
        "Small touches under the brow and at the inner corners build eye dimension; rely on placement, not quantity.",
        reason="光は量より置き場所",
    )
    return d


def _eyeshadow(char: CharacterRef) -> _Draft:
    eye = char.eye_color or "瞳の色"
    d = _Draft(
        MakeupArea.EYESHADOW,
        f"{eye}と揃うカラーをまぶたに。",
        f"Sweep a shade that echoes the character's {char.eye_color or 'eye colour'} across the lid.",
        minutes=9,
    )
    d.add(
        "淡い色が発色しないときは、白の下地を1枚仕込んでから重ねる。",
        "If a pale shade won't show, lay down a white base first.",
        reason="淡色の発色を確保",
        minutes=1,
    )
    return d


def _eyeline(char: CharacterRef) -> _Draft:
    d = _Draft(
        MakeupArea.EYELINE,
        "上まぶたのキワを埋め、目尻を跳ね上げる。",
        "Fill the upper lash line, then flick the outer corner.",
        minutes=8,
    )
    d.add(
        "跳ね上げの角度はキャラの目の形に合わせる。長さは鏡で正面から確かめる。",
        "Match the flick angle to the character's eye shape; check the length head-on in the mirror.",
        reason="キャラの目の形に合わせる",
    )
    d.add(
        "下まぶたは目尻1/3のみ。全周を囲むと写真で目が小さく写る。",
        "Line only the outer third of the lower lid — a full circle shrinks the eye on camera.",
        reason="撮影での見え方",
    )
    return d


def _lens(char: CharacterRef) -> _Draft:
    eye = char.eye_color or "キャラの瞳色"
    d = _Draft(
        MakeupArea.LENS,
        f"{eye}のカラコンを装着。会場では乾きやすいので目薬を携行する。",
        f"Insert lenses in the character's {char.eye_color or 'eye'} colour. Carry drops — venues are dry.",
        minutes=5,
    )
    d.add(
        "地の虹彩が濃いと淡色レンズは発色しない。裏面が不透明（ベース入り）の型番なら色が出る。",
        "Over a darker iris, sheer pale lenses won't show — an opaque-backed (base-layer) design will.",
        reason="発色しないときはベース入りを選ぶ",
    )
    return d


def _lip(char: CharacterRef) -> _Draft:
    d = _Draft(
        MakeupArea.LIP,
        "唇の色をコンシーラーで一度消してから、キャラの色をのせる。",
        "Neutralise your lip colour with concealer first, then lay the character's shade on top.",
        minutes=5,
    )
    d.add(
        "淡いリップは下地を1枚仕込まないと沈む。",
        "Pale lipsticks need a base layer or they go muddy.",
        reason="淡色リップの発色",
    )
    return d


def _wig_line(char: CharacterRef) -> _Draft:
    d = _Draft(
        MakeupArea.WIG_LINE,
        "ウィッグを被り、生え際の境目をファンデとパウダーで馴染ませる。",
        "Put the wig on and blend the hairline seam with foundation and powder.",
        minutes=6,
    )
    d.add(
        "自分の肌の色に合わせた粉を使う（ネットの色ではなく肌に合わせる）。",
        "Match the powder to your own skin, not to the wig cap colour.",
        reason="生え際の色は肌基準",
    )
    return d


# ---------------------------------------------------------------- 組み立て


_BUILDERS = {
    MakeupArea.BASE: _base,
    MakeupArea.BROW: _brow,
    MakeupArea.CONTOUR: lambda c: _contour(),
    MakeupArea.HIGHLIGHT: lambda c: _highlight(),
    MakeupArea.EYESHADOW: _eyeshadow,
    MakeupArea.EYELINE: _eyeline,
    MakeupArea.LENS: _lens,
    MakeupArea.LIP: _lip,
    MakeupArea.WIG_LINE: _wig_line,
}

# 工程の根拠のタグ。下書きは日本語で積み、英語の工程表ではここで置き換える
_REASON_EN = {
    "明度は変えない": "Lightness unchanged",
    "屋内外の撮影を想定": "Indoor and outdoor shoots",
    "キャラの眉山に合わせる": "Match the character's brow arch",
    "濃さより置き場所": "Placement over depth",
    "鼻の影は上1/3に限定": "Nose shade on the upper third only",
    "光は量より置き場所": "Light: placement over amount",
    "淡色の発色を確保": "Keep pale colours vivid",
    "キャラの目の形に合わせる": "Match the character's eye shape",
    "撮影での見え方": "How it reads on camera",
    "発色しないときはベース入りを選ぶ": "Use a tinted base if colour won't show",
    "淡色リップの発色": "Pale lip colour payoff",
    "生え際の色は肌基準": "Hairline colour follows your skin",
}

_NOTES = {
    Lang.JA: [
        "工程はキャラの色味と造形から組んでいます。肌の色や顔立ちは見ていないので、濃さはご自身に合わせて決めてください。",
        "肌の明るさ自体を変える指示は含みません。キャラの色味には光と影で寄せます。",
    ],
    Lang.EN: [
        "Steps are built from the character's colours and shapes. We don't look at your skin or face, so judge intensity against your own.",
        "Nothing here changes your skin's lightness — the character's tone is matched with light and shadow.",
    ],
}


def build_plan(character: CharacterRef, *, lang: Lang = Lang.JA) -> MakeupPlan:
    """キャラから工程表を生成する（LLM非依存）。"""
    steps: list[MakeupStep] = []
    for order, area in enumerate(AREA_ORDER, start=1):
        draft = _BUILDERS[area](character)
        instruction = draft.ja if lang is Lang.JA else draft.en
        steps.append(
            MakeupStep(
                order=order,
                area=area,
                instruction=instruction.strip(),
                lang=lang,
                minutes=draft.minutes,
                personalized_for=(
                    draft.reasons if lang is Lang.JA else [_REASON_EN.get(r, r) for r in draft.reasons]
                ),
            )
        )
    return MakeupPlan(
        steps=steps,
        lang=lang,
        total_minutes=sum(s.minutes for s in steps),
        notes=_NOTES.get(lang, _NOTES[Lang.EN]),
    )


def personalization_coverage(plan: MakeupPlan) -> dict[str, int]:
    """工程ごとの根拠の件数。工程の厚みを見るための素材。"""
    return {step.area.value: len(step.personalized_for) for step in plan.steps}
