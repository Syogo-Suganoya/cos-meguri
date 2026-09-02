"""YouCam の代役。キーが無くても全機能を通せるようにする。

画像の内容は見ないが、本番実装と同じ契約（解析後に破棄・数値のみ返す）で
振る舞う。判定は画像バイト列のハッシュから決定的に導き、デモの再現性を保つ。
"""

from __future__ import annotations

import hashlib

from app.domain.models import (
    CharacterRef,
    FaceAttributes,
    FaceProfile,
    FittingCandidate,
    FittingKind,
    FitzpatrickType,
)
from app.ports.vto import VtoPort

_WIG_STYLES = [
    ("ロングストレート", "long straight"),
    ("ツインテール", "twin tails"),
    ("ショートウルフ", "short wolf cut"),
    ("ミディアムレイヤー", "medium layered"),
]
_COSTUME_CUTS = [
    ("制服ジャケット", "uniform jacket"),
    ("ロングコート", "long coat"),
    ("和装アレンジ", "kimono-style"),
    ("アーマー付き", "with armour pieces"),
]


def _digest(data: bytes | None) -> int:
    return int(hashlib.sha256(data or b"cos-meguri").hexdigest()[:8], 16)


class MockVto(VtoPort):
    name = "vto:mock"

    async def analyze_face(self, image_bytes: bytes) -> FaceProfile:
        seed = _digest(image_bytes)
        types = list(FitzpatrickType)
        skin = types[seed % len(types)]

        def score(shift: int) -> float:
            return round(((seed >> shift) % 100) / 100, 2)

        profile = FaceProfile(
            fitzpatrick_type=skin,
            attributes=FaceAttributes(
                brow_depth=score(3),
                nose_bridge=score(5),
                eye_distance=score(7),
                eye_roundness=score(9),
                face_length=score(11),
                lip_fullness=score(13),
                jaw_width=score(15),
            ),
            source_image_discarded=True,
        )
        del image_bytes  # 設計書 §7-1: 解析が終わった時点で画像は保持しない
        return profile

    async def try_on(
        self,
        *,
        image_bytes: bytes | None,
        kind: FittingKind,
        character: CharacterRef,
        limit: int = 3,
    ) -> list[FittingCandidate]:
        seed = _digest(image_bytes)
        catalog = _WIG_STYLES if kind is FittingKind.WIG else _COSTUME_CUTS
        color = (
            character.hair_color if kind is FittingKind.WIG else None
        ) or "キャラ指定色"

        out: list[FittingCandidate] = []
        for i in range(min(limit, len(catalog))):
            label_ja, label_en = catalog[(seed + i) % len(catalog)]
            out.append(
                FittingCandidate(
                    candidate_id=f"{kind.value}_{(seed + i) % 9973:04d}",
                    kind=kind,
                    label=label_ja,
                    color=color,
                    # 一時URL。Cloud Storage 側の TTL で消える想定
                    preview_url=f"/preview/{kind.value}/{(seed + i) % 9973:04d}.png",
                    fit_score=round(0.92 - i * 0.07, 2),
                    note=f"mock preview ({label_en})",
                )
            )
        del image_bytes  # 試着画像も返却後に破棄する
        return out
