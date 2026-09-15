"""お気に入りの写しを作る。外部には依存しない。

写しは本人の遠征からだけ作る。クライアントから届いた工程や経路は信用しない
（他人の工程を「自分のお気に入り」として置けてしまう）。

見出しにはキャラ名・作品名を入れる。お気に入りは本人にしか返さない
（`GET /api/me/favorites`）ので、並べたときに「どのキャラのものか」で見分けられる
ほうを取った。他人に見える場所（遠征の応答など）には、これまでどおり出さない（設計書 §7-4）。
"""

from __future__ import annotations

from app.domain.models import JST, Expedition, Favorite, FavoriteKind, Lang

# 1人が持てる数。写しを丸ごと持つので、際限なく積めないようにしておく
MAX_FAVORITES = 100

_DIRECTION_LABEL = {
    Lang.JA: {"outbound": "行き", "return": "帰り"},
    Lang.EN: {"outbound": "outbound", "return": "return"},
}


class FavoriteError(ValueError):
    """写しを作れない（プランに無い部分を指した・動線の向きが無いなど）。"""


def _day(exp: Expedition) -> str:
    return exp.event.starts_at.astimezone(JST).strftime("%m/%d")


def _who(exp: Expedition, lang: Lang) -> str:
    """「アロナ（ブルーアーカイブ）」の形。どちらかが空なら、あるほうだけ。"""
    name, title = exp.character.name.strip(), exp.character.title.strip()
    if name and title:
        return f"{name}（{title}）" if lang is Lang.JA else f"{name} ({title})"
    return name or title


def build_favorite(
    exp: Expedition,
    kind: FavoriteKind,
    *,
    favorite_id: str,
    direction: str | None = None,
) -> Favorite:
    """遠征の一部を写してお気に入りにする。見出しはキャラ・イベント・日付（動線なら駅も）。"""
    lang = exp.lang if exp.lang in _DIRECTION_LABEL else Lang.EN
    who = _who(exp, lang)
    when = f"{exp.event.name} {_day(exp)}"

    if kind is FavoriteKind.MAKEUP:
        if not exp.makeup or not exp.makeup.steps:
            raise FavoriteError("このプランにはメイクの工程がありません")
        label = (
            f"{who}のメイク・{when}" if lang is Lang.JA else f"Makeup: {who}, {when}"
        )
        return Favorite(
            favorite_id=favorite_id,
            layer_id=exp.layer_id,
            kind=kind,
            label=label,
            exp_id=exp.exp_id,
            event=exp.event,
            lang=exp.lang,
            makeup=exp.makeup,
        )

    if direction not in ("outbound", "return"):
        raise FavoriteError("動線は行き（outbound）か帰り（return）を指定してください")
    route = exp.routes.get(direction)
    if route is None or not route.segments:
        raise FavoriteError("このプランにはその向きの動線がありません")

    stations = f"{route.segments[0].from_station} → {route.segments[-1].to_station}"
    way = _DIRECTION_LABEL[lang][direction]
    label = (
        f"{stations}（{way}）・{who}・{when}"
        if lang is Lang.JA
        else f"{stations} ({way}): {who}, {when}"
    )
    return Favorite(
        favorite_id=favorite_id,
        layer_id=exp.layer_id,
        kind=kind,
        label=label,
        exp_id=exp.exp_id,
        direction=direction,
        event=exp.event,
        lang=exp.lang,
        route=route,
    )


def same_source(a: Favorite, b: Favorite) -> bool:
    """同じプランの同じ部分を指しているか。二重に保存しないために使う。"""
    return (a.exp_id, a.kind, a.direction) == (b.exp_id, b.kind, b.direction)
