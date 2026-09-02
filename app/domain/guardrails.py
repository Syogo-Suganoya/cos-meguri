"""二次創作ガイドライン・エンジン（設計書 §7-4 / §11）。

3つの責務を持つ:
1. キャラ名・作品名は「メイク工程生成の内部入力」に限定し、外部共有される
   テキストからは落とす
2. 生成画像・完成イメージ・アフタームービーに権利物のロゴ・素材を合成する依頼を、
   出力前に止める
3. ボイスクローンの依頼を止める（キャラクター音声の権利リスクを構造的に回避）

止めた事実は監査ログ（IP_GUARD_BLOCKED / VOICE_CLONE_BLOCKED）に残す。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domain.models import CharacterRef

# 権利物の素材・ロゴ合成にあたる依頼語（日英）
_BLOCKED_PATTERNS: list[tuple[str, str]] = [
    (r"公式(の)?(ロゴ|イラスト|素材|画像|絵)", "公式素材の合成依頼"),
    (r"(ロゴ|エンブレム|社章)を(合成|貼|入れ|付け)", "ロゴ合成の依頼"),
    (r"アニメ(の)?(スクショ|スクリーンショット|キャプチャ)", "本編キャプチャの利用"),
    (r"原作(の)?(コマ|1枚絵|カット)", "原作画像の利用"),
    (r"official\s+(logo|art(work)?|asset|illustration)", "official asset composition"),
    (r"(composite|overlay|paste)\s+.*\blogo\b", "logo composition"),
    (r"anime\s+screenshot", "screenshot reuse"),
    (r"(公式|official).{0,6}(グッズ|merch).{0,6}(再現|replicate)", "official merch replication"),
]


@dataclass
class GuardResult:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    sanitized_text: str | None = None

    @property
    def blocked(self) -> bool:
        return not self.allowed


def screen_generation_request(prompt: str) -> GuardResult:
    """試着・画像生成の依頼文を出力前に検査する。"""
    reasons = [
        label
        for pattern, label in _BLOCKED_PATTERNS
        if re.search(pattern, prompt, flags=re.IGNORECASE)
    ]
    if reasons:
        return GuardResult(allowed=False, reasons=sorted(set(reasons)))
    return GuardResult(allowed=True, sanitized_text=prompt)


# ボイスクローンにあたる依頼語（設計書 §11「ボイスクローンは使用しない」）
_VOICE_CLONE_PATTERNS: list[tuple[str, str]] = [
    (r"(声|ボイス)(を)?(クローン|複製|再現|コピー)", "音声の複製依頼"),
    (r"(キャラ|中の人|声優)(の)?(声|ボイス)(で|に)", "キャラクター音声の再現依頼"),
    (r"voice\s*(clone|cloning|copy)", "voice cloning"),
    (r"clone\s+.{0,12}\bvoice\b", "voice cloning"),
    (r"(sound|speak)\s+like\s+.{0,20}(character|actor|seiyuu)", "voice imitation"),
]

# 生成物に必ず入れる表示（設計書 §11）
WATERMARK_LABEL_JA = "AI生成"
WATERMARK_LABEL_EN = "AI-generated"


def screen_voice_request(prompt: str) -> GuardResult:
    """音声合成の依頼文を検査する。

    ボイスクローンは技術的に可能でも使わない。止める場所を1箇所に集めておくと、
    「使わない」という約束がコード上で確認できる。
    """
    reasons = [
        label
        for pattern, label in _VOICE_CLONE_PATTERNS
        if re.search(pattern, prompt, flags=re.IGNORECASE)
    ]
    if reasons:
        return GuardResult(allowed=False, reasons=sorted(set(reasons)))
    return GuardResult(allowed=True, sanitized_text=prompt)


def watermark_label(lang: str) -> str:
    return WATERMARK_LABEL_JA if lang == "ja" else WATERMARK_LABEL_EN


def build_look_prompt(character: CharacterRef, *, wig: str, costume: str) -> str:
    """完成イメージ用のプロンプトを組む。

    キャラ名・作品名は入れない。入れると生成物が「そのキャラの絵」に寄り、
    権利物の複製に近づくため。渡すのは色味と造形の記述だけに留める
    （設計書 §7-4 の「内部入力に限定」を、生成の入力側でも守る）。
    """
    features = "、".join(character.features[:3]) if character.features else "はっきりした目元"
    return (
        "コスプレの完成予想図。"
        f"ウィッグ: {wig}（{character.hair_color or '指定色'}）、"
        f"衣装: {costume}、"
        f"瞳の色: {character.eye_color or '指定色'}、"
        f"特徴: {features}。"
        "実在の人物・公式イラスト・ロゴは使わない。全身、スタジオ照明、無地の背景。"
    )


def redact_character(text: str, character: CharacterRef) -> str:
    """共有テキストから作品名・キャラ名を伏せる。

    メイク工程はキャラ名を内部入力として使うが、Xやグループへ出す文面には
    残さない（身バレ・権利まわりの双方の理由）。
    """
    out = text
    for token in (character.name, character.title):
        if token:
            out = out.replace(token, "＊＊")
    return out


def shareable_summary(text: str, character: CharacterRef) -> str:
    """外部共有用の要約テキストを作る。キャラ情報は落とす。"""
    return redact_character(text, character).strip()


def is_internal_only(field_name: str) -> bool:
    """キャラ関連フィールドが内部入力限定かどうか。API 応答の整形で使う。"""
    return field_name in {"character", "character_hint"}
