"""二次創作ガイドライン・エンジン（設計書 §7-4 / §11）。

2つの責務を持つ:
1. キャラ名・作品名は「メイク工程生成の内部入力」に限定し、外部共有される
   テキストからは落とす
2. 試着の生成画像に権利物のロゴ・素材を合成する依頼を、出力前に止める

止めた事実は監査ログ（IP_GUARD_BLOCKED）に残す。
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
