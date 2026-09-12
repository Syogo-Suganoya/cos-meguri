"""キャラ名・作品名の取り扱い（設計書 §7-4）。

キャラ名と作品名は**メイク工程の生成にだけ**使い、外へ出すテキストからは落とす。
身バレと権利まわりの両方の理由がある。

権利物のロゴ・素材の合成を止める検査は、試着と画像生成を取り下げた時点で
呼び出し元が無くなったので消した。`AuditAction.IP_GUARD_BLOCKED` は
過去の記録を読み戻せるように値だけ残してある。
"""

from __future__ import annotations

from app.domain.models import CharacterRef


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
