"""キャラ再現メイクの工程分解（設計書 §4 メイクナビ、§7-2 公平性）。

Fitzpatrick 肌タイプと顔属性スコアから、決定的なルールで工程を組み立てる。
Gemini は「言い回しを整える／母語に落とす」ためだけに後段で使い、
LLM が無くても全工程が出せるようにここを純粋関数で完結させる。

公平性の原則:
- どの肌タイプも標準扱いしない。工程差は「同じキャラに同じ品質で近づく」ための差分
- 肌を明るく／暗く塗り替える指示は出さない。キャラの色味には光と影で寄せる
- 骨格の個別化は「元の骨格を否定する」表現を避け、光の置き場所として書く
"""

from __future__ import annotations

from app.domain.models import (
    CharacterRef,
    FaceAttributes,
    FaceProfile,
    FitzpatrickType,
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


def _base(skin: FitzpatrickType, char: CharacterRef) -> _Draft:
    d = _Draft(
        MakeupArea.BASE,
        "素肌の色を活かしたまま、色ムラだけを整える下地を薄く伸ばす。",
        "Even out tone with a thin primer while keeping your own skin colour.",
        minutes=6,
    )
    if skin.is_light:
        d.add(
            "血色が透けやすいので、赤みの出る小鼻と目周りにコントロールカラーを点置きしてから伸ばす。",
            "Redness shows easily on type I–II: dot a colour corrector around the nose and eyes first.",
            reason=f"Fitzpatrick {skin.value}: 赤みが出やすい",
            minutes=2,
        )
    elif skin.is_deep:
        d.add(
            "白浮きを避けるため、フェイスラインとまぶたで2トーン使い分け、境目をスポンジで叩き込む。"
            "キャラの肌色にはベースではなく、後段のハイライトと影で寄せる。",
            "Avoid ashy cast: use two shades (face line vs. eyelids) and press the seam with a sponge. "
            "Match the character's tone with highlight and shadow later — not by changing your base shade.",
            reason=f"Fitzpatrick {skin.value}: 白浮き回避・明度は変えない",
            minutes=3,
        )
    else:
        d.add(
            "テカりやすいTゾーンだけ皮脂崩れ防止を重ねる。",
            "Add a mattifying layer on the T-zone only.",
            reason=f"Fitzpatrick {skin.value}: Tゾーンの崩れ対策",
            minutes=1,
        )
    d.add(
        "撮影の照明で飛ばないよう、仕上げにフィックスミストを1プッシュ。",
        "Finish with one spray of setting mist so the base survives event lighting.",
        reason="屋内外の撮影を想定",
        minutes=1,
    )
    return d


def _brow(attrs: FaceAttributes, char: CharacterRef) -> _Draft:
    hair = char.hair_color or "髪色"
    d = _Draft(
        MakeupArea.BROW,
        f"地眉をコンシーラーで潰し、{hair}に合わせた眉を描き直す。",
        f"Block out your natural brows with concealer, then redraw them to match the {char.hair_color or 'wig'} colour.",
        minutes=8,
    )
    if attrs.high("brow_depth"):
        d.add(
            "眉骨が高いので、毛を1本ずつ描き足す方向で。面で塗ると影が強く出る。",
            "With a prominent brow bone, draw hair-by-hair — a solid fill casts a heavy shadow.",
            reason="彫りが深い: 面塗りだと影が強く出る",
        )
    elif attrs.low("brow_depth"):
        d.add(
            "眉骨が平坦なぶん、眉頭の下に薄く影を入れると立体が出る。",
            "With a flatter brow bone, a light shadow under the brow head adds dimension.",
            reason="彫りが浅い: 眉下の影で立体を作る",
        )
    else:
        d.add(
            "眉骨は中間なので、眉山の位置だけキャラに合わせて動かせば形が寄る。",
            "With an average brow bone, shifting only the arch position moves you toward the character.",
            reason="彫りは中間: 眉山の位置で寄せる",
        )
    return d


def _contour(skin: FitzpatrickType, attrs: FaceAttributes) -> _Draft:
    d = _Draft(
        MakeupArea.CONTOUR,
        "頬骨下と輪郭に影を入れて、キャラの顔の形に寄せる。",
        "Shade under the cheekbones and along the jaw to move toward the character's face shape.",
        minutes=6,
    )
    if skin.is_deep:
        d.add(
            "グレー寄りの影は灰色に沈むので、赤みかプラム寄りの影色を選ぶ。",
            "Grey-based contour reads ashy on deeper skin — pick a red or plum-leaning shade.",
            reason=f"Fitzpatrick {skin.value}: 影色の色相を選び直す",
        )
    elif skin.is_light:
        d.add(
            "オレンジ寄りの影は浮くので、グレーベージュ寄りを薄く重ねる。",
            "Orange-leaning contour looks stripey here — build up a grey-beige shade thinly.",
            reason=f"Fitzpatrick {skin.value}: 影色の色相を選び直す",
        )
    else:
        d.add(
            "ベージュ〜ブラウンの影が馴染む。濃さより、頬骨下の入れ始めの位置で決まる。",
            "Beige-to-brown shadow blends well here; placement under the cheekbone matters more than depth.",
            reason=f"Fitzpatrick {skin.value}: 影色の色相を選び直す",
        )
    if attrs.low("nose_bridge"):
        d.add(
            "鼻筋は眉頭から鼻先まで通さず、眉頭寄りの1/3だけ影を置くと自然に高く見える。",
            "Shade only the upper third of the nose bridge rather than the full length — it reads higher, not drawn-on.",
            reason="鼻筋が低い: 影は上1/3に限定",
            minutes=2,
        )
    if attrs.high("nose_bridge"):
        d.add(
            "鼻筋はすでに高いので、ノーズシャドウは省いて小鼻の脇だけに留める。",
            "Your bridge is already high — skip the nose contour and touch only the sides of the nostrils.",
            reason="鼻筋が高い: ノーズシャドウを省略",
        )
    if attrs.high("jaw_width"):
        d.add(
            "エラの外側は削らず、耳下からあご先へ向かう斜めの影でラインを繋ぐ。",
            "Rather than carving the jaw corners, sweep a diagonal shadow from below the ear to the chin.",
            reason="エラが張る: 削らず流れで繋ぐ",
        )
    if attrs.high("face_length"):
        d.add(
            "面長を締めるため、額の生え際とあご先にも横方向の影を薄く。",
            "For a longer face, add a light horizontal shadow at the hairline and chin tip.",
            reason="面長: 縦を詰める",
        )
    return d


def _highlight(skin: FitzpatrickType, attrs: FaceAttributes) -> _Draft:
    d = _Draft(
        MakeupArea.HIGHLIGHT,
        "頬骨の上・鼻先・唇の山に光を置く。",
        "Place light on the top of the cheekbones, the nose tip and the cupid's bow.",
        minutes=4,
    )
    if skin.is_deep:
        d.add(
            "白いパール系は粉っぽく出るので、ゴールド／ブロンズの偏光を使い、量より置き場所で効かせる。",
            "White pearl looks chalky — use gold or bronze shimmer and rely on placement rather than quantity.",
            reason=f"Fitzpatrick {skin.value}: ハイライトの色を選び直す",
        )
    elif skin.is_light:
        d.add(
            "シャンパン〜シルバー系を少量。強いゴールドは肌から浮く。",
            "A small amount of champagne or silver; strong gold separates from the skin here.",
            reason=f"Fitzpatrick {skin.value}: ハイライトの色を選び直す",
        )
    if attrs.high("brow_depth"):
        d.add(
            "眉骨がもともと高いので、眉下のハイライトは省く（陰影が過剰になる）。",
            "Skip the under-brow highlight — with a deep brow bone it over-sculpts.",
            reason="彫りが深い: 眉下ハイライトを省略",
        )
    else:
        d.add(
            "眉下と目頭に小さくハイライトを置き、目元の立体を作る。",
            "Add small highlights under the brow and at the inner corners to build eye dimension.",
            reason="彫りが浅い: 眉下・目頭で立体を足す",
        )
    return d


def _eyeshadow(skin: FitzpatrickType, attrs: FaceAttributes, char: CharacterRef) -> _Draft:
    eye = char.eye_color or "瞳の色"
    d = _Draft(
        MakeupArea.EYESHADOW,
        f"{eye}と揃うカラーをまぶたに。",
        f"Sweep a shade that echoes the character's {char.eye_color or 'eye colour'} across the lid.",
        minutes=8,
    )
    if skin.is_deep:
        d.add(
            "淡色は発色しないので、白の下地を仕込んでから重ねると色が出る。",
            "Pale shades won't show without a white base underneath — lay that down first.",
            reason=f"Fitzpatrick {skin.value}: 淡色の発色を確保",
            minutes=2,
        )
    if attrs.high("eye_roundness"):
        d.add(
            "丸目なので、横方向に長く入れると目の形がキャラ寄りに変わる。",
            "For rounder eyes, extend the colour horizontally to reshape toward the character.",
            reason="丸目: 横方向に伸ばす",
        )
    else:
        d.add(
            "切れ長なので、二重幅の中央を縦に濃くすると丸みが出る。",
            "For narrower eyes, deepen the centre of the crease vertically to add roundness.",
            reason="切れ長: 中央を縦に濃く",
        )
    return d


def _eyeline(attrs: FaceAttributes) -> _Draft:
    d = _Draft(
        MakeupArea.EYELINE,
        "上まぶたのキワを埋め、目尻を跳ね上げる。",
        "Fill the upper lash line, then flick the outer corner.",
        minutes=7,
    )
    if attrs.high("eye_distance"):
        d.add(
            "目が離れ気味なので、目頭側にラインを足して中央に寄せる。目尻の延長は控えめに。",
            "Eyes sit wider apart: extend the line at the inner corners and keep the outer flick short.",
            reason="離れ目: 目頭側を足す",
        )
    elif attrs.low("eye_distance"):
        d.add(
            "目が寄り気味なので、目尻側を長めに引いて外へ広げる。目頭は塗り足さない。",
            "Eyes sit closer together: draw the outer line longer and leave the inner corners bare.",
            reason="寄り目: 目尻側を伸ばす",
        )
    d.add(
        "下まぶたは目尻1/3のみ。全周を囲むと写真で目が小さく写る。",
        "Line only the outer third of the lower lid — a full circle shrinks the eye on camera.",
        reason="撮影での見え方",
    )
    return d


def _lens(skin: FitzpatrickType, char: CharacterRef) -> _Draft:
    eye = char.eye_color or "キャラの瞳色"
    d = _Draft(
        MakeupArea.LENS,
        f"{eye}のカラコンを装着。会場では乾きやすいので目薬を携行する。",
        f"Insert lenses in the character's {char.eye_color or 'eye'} colour. Carry drops — venues are dry.",
        minutes=5,
    )
    if skin.depth_rank >= 4:
        d.add(
            "地の虹彩が濃い場合、非着色の淡色レンズは発色しない。裏面が不透明（ベース入り）の型番を選ぶ。",
            "Over a darker iris, sheer pale lenses won't show — choose an opaque-backed (base-layer) design.",
            reason="虹彩が濃い: ベース入りレンズを選ぶ",
        )
    else:
        d.add(
            "地の虹彩が明るいので、フチが太い型は不自然に出やすい。フチ細めを選ぶ。",
            "Over a lighter iris, thick limbal rings look artificial — pick a thinner ring.",
            reason="虹彩が明るい: フチ細めを選ぶ",
        )
    return d


def _lip(skin: FitzpatrickType, attrs: FaceAttributes) -> _Draft:
    d = _Draft(
        MakeupArea.LIP,
        "唇の色をコンシーラーで一度消してから、キャラの色をのせる。",
        "Neutralise your lip colour with concealer first, then lay the character's shade on top.",
        minutes=4,
    )
    if attrs.high("lip_fullness"):
        d.add(
            "厚みがあるので、輪郭の外周1〜2mmをコンシーラーで締めると輪郭が整う。",
            "With fuller lips, tighten 1–2 mm outside the border with concealer.",
            reason="唇が厚い: 外周を締める",
        )
    elif attrs.low("lip_fullness"):
        d.add(
            "薄めなので、山と中央だけオーバーリップにして中央に光を置く。",
            "With thinner lips, over-draw only the cupid's bow and centre, then add light in the middle.",
            reason="唇が薄い: 中央だけオーバーリップ",
        )
    else:
        d.add(
            "厚みは中間なので、輪郭はそのまま使い、色だけキャラに寄せる。",
            "Average lip fullness — keep your own outline and shift only the colour.",
            reason="唇の厚みは中間: 輪郭は変えない",
        )
    if skin.is_deep:
        d.add(
            "淡いリップは下地を1枚仕込まないと沈む。",
            "Pale lipsticks need a base layer or they go muddy.",
            reason=f"Fitzpatrick {skin.value}: 淡色リップの発色",
        )
    return d


def _wig_line(skin: FitzpatrickType) -> _Draft:
    d = _Draft(
        MakeupArea.WIG_LINE,
        "ウィッグを被り、生え際の境目をファンデとパウダーで馴染ませる。",
        "Put the wig on and blend the hairline seam with foundation and powder.",
        minutes=6,
    )
    d.add(
        "自分の肌の色に合わせた粉を使う（ネットの色ではなく肌に合わせる）。",
        "Match the powder to your own skin, not to the wig cap colour.",
        reason=f"Fitzpatrick {skin.value}: 生え際の色は肌基準",
    )
    return d


# ---------------------------------------------------------------- 組み立て


_BUILDERS = {
    MakeupArea.BASE: lambda p, c: _base(p.fitzpatrick_type, c),
    MakeupArea.BROW: lambda p, c: _brow(p.attributes, c),
    MakeupArea.CONTOUR: lambda p, c: _contour(p.fitzpatrick_type, p.attributes),
    MakeupArea.HIGHLIGHT: lambda p, c: _highlight(p.fitzpatrick_type, p.attributes),
    MakeupArea.EYESHADOW: lambda p, c: _eyeshadow(p.fitzpatrick_type, p.attributes, c),
    MakeupArea.EYELINE: lambda p, c: _eyeline(p.attributes),
    MakeupArea.LENS: lambda p, c: _lens(p.fitzpatrick_type, c),
    MakeupArea.LIP: lambda p, c: _lip(p.fitzpatrick_type, p.attributes),
    MakeupArea.WIG_LINE: lambda p, c: _wig_line(p.fitzpatrick_type),
}

_NOTES = {
    Lang.JA: [
        "工程は肌タイプと顔属性に合わせた差分です。どのタイプも標準ではありません。",
        "肌の明るさ自体を変える指示は含みません。キャラの色味には光と影で寄せます。",
    ],
    Lang.EN: [
        "Steps are personalised to your skin type and facial ratios. No type is treated as the default.",
        "Nothing here changes your skin's lightness — the character's tone is matched with light and shadow.",
    ],
}


def build_plan(
    profile: FaceProfile,
    character: CharacterRef,
    *,
    lang: Lang = Lang.JA,
) -> MakeupPlan:
    """肌タイプ×顔属性×キャラから工程表を生成する（LLM非依存）。"""
    steps: list[MakeupStep] = []
    for order, area in enumerate(AREA_ORDER, start=1):
        draft = _BUILDERS[area](profile, character)
        instruction = draft.ja if lang is Lang.JA else draft.en
        steps.append(
            MakeupStep(
                order=order,
                area=area,
                instruction=instruction.strip(),
                lang=lang,
                minutes=draft.minutes,
                personalized_for=draft.reasons,
            )
        )
    return MakeupPlan(
        steps=steps,
        lang=lang,
        total_minutes=sum(s.minutes for s in steps),
        fitzpatrick_type=profile.fitzpatrick_type,
        notes=_NOTES.get(lang, _NOTES[Lang.EN]),
    )


def personalization_coverage(plan: MakeupPlan) -> dict[str, int]:
    """工程ごとの個別化件数。肌タイプ別の品質評価（設計書 §7-2）の素材。"""
    return {step.area.value: len(step.personalized_for) for step in plan.steps}
