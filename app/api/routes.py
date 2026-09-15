"""HTTP エンドポイント（設計書 §4 API Gateway）。

方針:
- 誰であるかは必ずトークンから決める。body の layer_id は信用しない
- キャラ名・作品名は既定で返さない（設計書 §7-4）
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response

from app.adapters.dev_auth import DevAuth
from app.agents.i18n import supported_langs
from app.agents.orchestrator import PlanError, PlanRequest
from app.api.deps import (
    AgentBundle,
    Principal,
    current_layer,
    current_principal,
    get_agents,
    member_layer,
)
from app.config import get_settings
from app.api.schemas import (
    AdoptGuestRequest,
    ChatSlotsIn,
    DevLoginRequest,
    ExpeditionCreate,
    FavoriteCreate,
    LayerUpdate,
)
from app.domain.events import event_defaults, find_event, get_event, list_events
from app.domain.favorites import MAX_FAVORITES, FavoriteError, build_favorite, same_source
from app.domain.models import Expedition, Favorite, Layer, MakeupArea
from app.ports.auth import AuthError

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------- 認証


@router.get("/auth/config")
async def api_auth_config(agents: AgentBundle = Depends(get_agents)) -> dict:
    """ログイン画面が必要とする公開情報だけを返す。"""
    return agents.auth.client_config()


@router.post("/auth/dev-login")
async def api_dev_login(
    body: DevLoginRequest, agents: AgentBundle = Depends(get_agents)
) -> dict:
    """テスト用ログイン。パスワードを検証しないので APP_ENV=test でのみ有効。"""
    auth = agents.auth
    if not isinstance(auth, DevAuth):
        raise HTTPException(
            status_code=404,
            detail="テスト用ログインは無効です。Firebase Authentication でログインしてください",
        )
    try:
        return auth.issue(body.user, anonymous=body.anonymous)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/auth/session")
async def api_session(principal: Principal = Depends(current_principal)) -> dict:
    """ログイン後の初回呼び出し。uid からアカウントを引き当てる（無ければ作る）。

    guest はゲスト（匿名ログイン）かどうか。画面はこれで、お気に入りの案内を出し分ける。
    """
    return {**principal.layer.model_dump(mode="json"), "guest": principal.guest}


@router.post("/auth/adopt")
async def api_adopt_guest(
    body: AdoptGuestRequest,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(member_layer),
) -> dict:
    """ログインや登録の直後に呼ぶ。ゲストのあいだに組んだ条件とプランを本人へ移す。

    本人であることは Authorization（ログインしたトークン）が、移す元は body の
    ゲストのトークンが示す。どちらも検証するので、他人の条件は引き取れない。
    """
    try:
        adopted = await agents.adopt_guest(layer, body.guest_token)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"adopted": adopted}


# ---------------------------------------------------------------- マスタ


def _event_payload(e) -> dict:
    return {
        "event_id": e.event_id,
        "name": e.name,
        "name_en": e.name_en,
        "venue": e.venue,
        "station": e.station,
        "scale": e.scale,
        "style": e.style,
        "opens_at_hour": e.opens_at_hour,
        "closes_at_hour": e.closes_at_hour,
        "notes_ja": e.notes_ja,
        "notes_en": e.notes_en,
        # 相談の欄にそのまま入れる形（目的地・開始・終了）
        "defaults": event_defaults(e),
    }


@router.get("/events")
async def api_events() -> dict:
    return {"events": [_event_payload(e) for e in list_events()]}


@router.get("/stations")
async def api_suggest_stations(
    name: str = "",
    agents: AgentBundle = Depends(get_agents),
    _layer: Layer = Depends(current_layer),
) -> dict:
    """書きかけの駅名から、正式な駅名の候補を返す（「大宮」→「大宮(埼玉県)」「大宮(京都府)」）。

    入力のたびに駅すぱあとを呼ぶので、通行証（ゲスト可）を持つ人にだけ答える。
    """
    name = name.strip()[:40]
    return {"stations": await agents.adapters.transit.suggest_stations(name) if name else []}


@router.get("/events/match")
async def api_match_event(name: str = "") -> dict:
    """書かれたイベント名を収載イベントに引き当てる。相談の画面が目的地と時刻を自動で埋めるのに使う。

    略称（「コミケ」）はサーバのマスタにしか無いので、画面では突き合わせずここに聞く。
    """
    event = find_event(name[:60])
    return {"event": _event_payload(event) if event else None}


@router.get("/langs")
async def api_langs() -> dict:
    return {"langs": supported_langs()}


@router.get("/providers")
async def api_providers(agents: AgentBundle = Depends(get_agents)) -> dict:
    """いま何が mock で何が live かを可視化する（デモ・デバッグ用）。"""
    return agents.adapters.describe()


# ---------------------------------------------------------------- 自分


@router.get("/me")
async def api_me(layer: Layer = Depends(current_layer)) -> dict:
    return layer.model_dump(mode="json")


@router.patch("/me")
async def api_update_me(
    body: LayerUpdate,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    relang = bool(body.lang) and body.lang != layer.lang
    if body.lang:
        layer.lang = body.lang
    if body.luggage_mode:
        layer.prefs.luggage_mode = body.luggage_mode
    if body.home_event is not None:
        layer.prefs.home_event = body.home_event
    await agents.repository.save_layer(layer)
    if relang:
        # 組み上がったプランがあれば、新しい言語で組み直す（工程の文面や注意書きは組んだ言語で持っている）。
        # お気に入りは保存した時点の写しなので、そのままにする
        session = await agents.chat.history(layer)
        if session.slots.is_complete:
            await agents.chat.set_slots(layer, {})
    return layer.model_dump(mode="json")


# ---------------------------------------------------------------- チャット


@router.get("/chat")
async def api_chat_history(
    agents: AgentBundle = Depends(get_agents), layer: Layer = Depends(current_layer)
) -> dict:
    session = await agents.chat.history(layer)
    return _chat_payload(session)


@router.patch("/chat/slots")
async def api_chat_slots(
    body: ChatSlotsIn,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    """条件を書き換える。揃えばプランまで組む。

    「相談」ページの欄から来る。直したい項目だけを送ればよい。
    イベントは名前（event_name）で受ける。収載イベントに当たれば event_id を入れ、
    同じ body で送られていない目的地・開始・終了をマスタで埋める（送られた値が勝つ）。
    当たらない名前（ローカルイベントなど）もそのまま受け、目的地と時刻は欄から入れてもらう。
    """
    values = body.model_dump(exclude_unset=True)
    for key in ("event_name", "destination_station"):
        if isinstance(values.get(key), str):
            values[key] = values[key].strip()

    master = None
    if "event_name" in values:
        master = find_event(values["event_name"]) if values["event_name"] else None
        values["event_id"] = master.event_id if master else None
    elif values.get("event_id"):
        # event_id の直指定（テストや古い呼び出し）。名前もマスタから入れる
        master = get_event(values["event_id"])
        if master is None:
            raise HTTPException(status_code=422, detail={"field": "event_name", "error": "event not found"})
        values["event_name"] = master.name
    if master is not None:
        for key, value in event_defaults(master).items():
            # 画面は全部の欄を送ってくる。空で送られた欄は「まだ入れていない」として埋める
            if not values.get(key):
                values[key] = value

    try:
        session = await agents.chat.set_slots(layer, values)
    except PlanError as exc:
        raise HTTPException(status_code=422, detail={"field": exc.field, "error": str(exc), "code": exc.code})
    payload = _chat_payload(session)
    if session.exp_id:
        exp = await agents.repository.get_expedition(session.exp_id)
        if exp is not None:
            payload["expedition"] = _expedition_payload(exp)
    return payload


def _chat_payload(session) -> dict:
    data = session.model_dump(mode="json")
    data["missing"] = session.slots.missing()
    data["is_complete"] = session.slots.is_complete
    return data


# ---------------------------------------------------------------- 遠征


def _expedition_payload(exp: Expedition, extras: dict | None = None) -> dict:
    data = exp.model_dump(mode="json")
    data.pop("character", None)  # キャラ情報は内部入力に限定（§7-4）
    _makeup_labels(data.get("makeup"), exp.lang.value)
    if extras:
        data["extras"] = extras
    return data


@router.post("/expeditions", status_code=201)
async def api_create_expedition(
    body: ExpeditionCreate,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    fields = {
        "event_name": body.event_name,
        "destination_station": body.destination_station,
        "starts_time": body.starts_time,
        "ends_time": body.ends_time,
    }
    if body.event_id:
        master = get_event(body.event_id)
        if master is None:
            raise HTTPException(status_code=404, detail="event not found")
        defaults = {"event_name": master.name, **event_defaults(master)}
        fields = {k: v or defaults[k] for k, v in fields.items()}
    missing = [k for k, v in fields.items() if not v]
    if missing:
        raise HTTPException(status_code=422, detail={"field": missing[0], "error": f"{', '.join(missing)} が足りません"})

    req = PlanRequest(
        layer_id=layer.layer_id,
        event_id=body.event_id,
        **fields,
        day=body.day,
        character=body.character,
        origin_station=body.origin_station,
        luggage_mode=body.luggage_mode or layer.prefs.luggage_mode,
        lang=body.lang or layer.lang,
    )
    try:
        exp, extras = await agents.orchestrator.plan(req)
    except PlanError as exc:
        raise HTTPException(status_code=422, detail={"field": exc.field, "error": str(exc), "code": exc.code})
    return _expedition_payload(exp, extras)


@router.get("/expeditions/{exp_id}")
async def api_get_expedition(
    exp_id: str,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    exp = await agents.repository.get_expedition(exp_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="expedition not found")
    if exp.layer_id != layer.layer_id:
        raise HTTPException(status_code=403, detail="他の人の遠征は参照できません")
    return _expedition_payload(exp)


@router.get("/me/expeditions")
async def api_list_expeditions(
    agents: AgentBundle = Depends(get_agents), layer: Layer = Depends(current_layer)
) -> dict:
    exps = await agents.repository.list_expeditions(layer.layer_id)
    return {"expeditions": [_expedition_payload(e) for e in exps]}


# ---------------------------------------------------------------- お気に入り


def _makeup_labels(makeup: dict | None, lang: str) -> None:
    """工程に画面用の見出し（ベース・眉…）を足す。遠征とお気に入りで同じ形にする。"""
    if not makeup:
        return
    for step in makeup.get("steps", []):
        try:
            area = MakeupArea(step["area"])
        except (KeyError, ValueError):
            continue
        step["area_label"] = area.label_ja if lang == "ja" else area.label_en


def _favorite_payload(favorite: Favorite) -> dict:
    data = favorite.model_dump(mode="json")
    _makeup_labels(data.get("makeup"), favorite.lang.value)
    return data


@router.get("/me/favorites")
async def api_list_favorites(
    agents: AgentBundle = Depends(get_agents), layer: Layer = Depends(member_layer)
) -> dict:
    favorites = await agents.repository.list_favorites(layer.layer_id)
    return {"favorites": [_favorite_payload(f) for f in favorites]}


@router.post("/me/favorites", status_code=201)
async def api_add_favorite(
    body: FavoriteCreate,
    response: Response,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(member_layer),
) -> dict:
    """本人の遠征の一部を写して保存する。同じ部分を二度保存しても1件のまま。"""
    exp = await agents.repository.get_expedition(body.exp_id)
    # 他人の遠征は「無い」と同じに扱う。あるかどうかも教えない
    if exp is None or exp.layer_id != layer.layer_id:
        raise HTTPException(status_code=404, detail="expedition not found")

    try:
        favorite = build_favorite(
            exp,
            body.kind,
            favorite_id=f"fav_{uuid.uuid4().hex[:10]}",
            direction=body.direction,
        )
    except FavoriteError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    existing = await agents.repository.list_favorites(layer.layer_id)
    for saved in existing:
        if same_source(saved, favorite):
            response.status_code = 200
            return _favorite_payload(saved)
    if len(existing) >= MAX_FAVORITES:
        raise HTTPException(
            status_code=409,
            detail={
                "error": f"お気に入りは{MAX_FAVORITES}件までです。マイページで要らないものを消してください",
                "code": "favorites_limit",
                "limit": MAX_FAVORITES,
            },
        )

    await agents.repository.save_favorite(favorite)
    return _favorite_payload(favorite)


@router.delete("/me/favorites/{favorite_id}", status_code=204)
async def api_delete_favorite(
    favorite_id: str,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(member_layer),
) -> Response:
    favorite = await agents.repository.get_favorite(favorite_id)
    # 他人のお気に入りも「無い」と同じに扱う
    if favorite is None or favorite.layer_id != layer.layer_id:
        raise HTTPException(status_code=404, detail="favorite not found")
    await agents.repository.delete_favorite(favorite_id)
    return Response(status_code=204)


# ---------------------------------------------------------------- 監査


@router.get("/audit")
async def api_audit(
    subject_id: str | None = None,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    """自分に関わる記録だけを返す。

    以前は絞り込みなしで全レイヤーぶんを返していた。記録は本人が自分の
    データの扱いを確かめるためのものなので、他人ぶんは見せない。
    """
    logs = await agents.repository.list_audit(
        subject_id=subject_id, layer_id=layer.layer_id
    )
    logs.sort(key=lambda log: log.created_at, reverse=True)
    return {"logs": [log.model_dump(mode="json") for log in logs]}
