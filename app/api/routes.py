"""HTTP エンドポイント（設計書 §4 API Gateway）。

方針:
- 誰であるかは必ずトークンから決める。body の layer_id は信用しない
- キャラ名・作品名は既定で返さない（設計書 §7-4）
- 更衣室の値には「モデル推定」フラグを必ず添える（設計書 §9）
- 位置共有は有効期限つきで、失効後は値ごと消えている（設計書 §7-3）
"""

from __future__ import annotations

import base64
import binascii
import secrets
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.adapters.dev_auth import DevAuth
from app.agents.fitting import IpGuardBlocked
from app.agents.visual import IpGuardBlocked as VisualIpGuardBlocked
from app.agents.voice import VoiceCloneBlocked
from app.agents.i18n import supported_langs
from app.agents.orchestrator import PlanRequest
from app.api.deps import AgentBundle, current_layer, get_agents
from app.config import get_settings
from app.api.schemas import (
    AfterMovieRequest,
    AwaseCreate,
    ChatRequest,
    DecisionIn,
    DevLoginRequest,
    ExpeditionCreate,
    FaceAnalyzeRequest,
    FittingRequest,
    LayerUpdate,
    LookImageRequest,
    MarkReadRequest,
    ProgressUpdate,
    SessionRequest,
    ShootCreate,
    VoiceGuideRequest,
)
from app.domain.events import get_event, list_events
from app.domain.models import (
    AuditAction,
    AuditLog,
    Awase,
    AwaseMember,
    EventRef,
    Expedition,
    Layer,
    NotificationKind,
    Shoot,
    event_day,
)
from app.ports.auth import AuthError

router = APIRouter(prefix="/api")


def _decode_image(image_b64: str | None) -> bytes | None:
    if not image_b64:
        return None
    payload = image_b64.split(",", 1)[-1]  # data URL のヘッダを落とす
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="画像のデコードに失敗しました")


# ---------------------------------------------------------------- 認証


@router.get("/auth/config")
async def api_auth_config(agents: AgentBundle = Depends(get_agents)) -> dict:
    """ログイン画面が必要とする公開情報だけを返す。"""
    return agents.auth.client_config()


@router.post("/auth/dev-login")
async def api_dev_login(
    body: DevLoginRequest, agents: AgentBundle = Depends(get_agents)
) -> dict:
    """開発用ログイン。パスワードを検証しないので dev モードでのみ有効。"""
    auth = agents.auth
    if not isinstance(auth, DevAuth):
        raise HTTPException(
            status_code=404,
            detail="開発用ログインは無効です。Firebase Authentication でログインしてください",
        )
    try:
        return auth.issue(body.handle)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/auth/session")
async def api_session(
    body: SessionRequest,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    """ログイン後の初回呼び出し。コス名アカウントを引き当てる／作る。"""
    if body.handle and layer.handle != body.handle:
        layer.handle = body.handle
        await agents.repository.save_layer(layer)
    return layer.model_dump(mode="json")


# ---------------------------------------------------------------- マスタ


@router.get("/events")
async def api_events() -> dict:
    return {
        "events": [
            {
                "event_id": e.event_id,
                "name": e.name,
                "name_en": e.name_en,
                "venue": e.venue,
                "station": e.station,
                "scale": e.scale,
                "style": e.style,
                "opens_at_hour": e.opens_at_hour,
                "closes_at_hour": e.closes_at_hour,
                "expected_cosplayers": e.expected_cosplayers,
                "notes_ja": e.notes_ja,
                "notes_en": e.notes_en,
            }
            for e in list_events()
        ]
    }


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
    if body.handle:
        layer.handle = body.handle
    if body.lang:
        layer.lang = body.lang
    if body.luggage_mode:
        layer.prefs.luggage_mode = body.luggage_mode
    if body.home_event is not None:
        layer.prefs.home_event = body.home_event
    await agents.repository.save_layer(layer)
    return layer.model_dump(mode="json")


@router.post("/me/face")
async def api_analyze_face(
    body: FaceAnalyzeRequest,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    """顔解析。画像は解析後に破棄し、数値スコアだけを保存する（設計書 §7-1）。"""
    image = _decode_image(body.image_b64) or b"demo-face"
    profile = await agents.fitting.analyze_face(layer.layer_id, image)
    del image

    layer.face_profile = profile
    await agents.repository.save_layer(layer)
    return {
        "face_profile": profile.model_dump(mode="json"),
        "image_retained": False,
        "audit": [
            log.model_dump(mode="json")
            for log in await agents.repository.list_audit(subject_id=layer.layer_id)
        ],
    }


# ---------------------------------------------------------------- お知らせ


@router.get("/me/notifications")
async def api_notifications(
    unread_only: bool = False,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    items = await agents.notifier.inbox(layer.layer_id, unread_only=unread_only)
    return {
        "notifications": [n.model_dump(mode="json") for n in items],
        "unread": sum(1 for n in items if not n.read),
    }


@router.post("/me/notifications/read")
async def api_mark_read(
    body: MarkReadRequest,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    ids = body.notification_ids
    if not ids:
        ids = [
            n.notification_id
            for n in await agents.notifier.inbox(layer.layer_id, unread_only=True)
        ]
    return {"read": await agents.notifier.mark_read(layer.layer_id, ids)}


# ---------------------------------------------------------------- チャット


@router.get("/chat")
async def api_chat_history(
    agents: AgentBundle = Depends(get_agents), layer: Layer = Depends(current_layer)
) -> dict:
    session = await agents.chat.history(layer)
    return _chat_payload(session)


@router.post("/chat")
async def api_chat(
    body: ChatRequest,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    session = await agents.chat.send(layer, body.message)
    payload = _chat_payload(session)
    if session.exp_id:
        exp = await agents.repository.get_expedition(session.exp_id)
        if exp:
            payload["expedition"] = _expedition_payload(exp)
    return payload


@router.post("/chat/reset")
async def api_chat_reset(
    agents: AgentBundle = Depends(get_agents), layer: Layer = Depends(current_layer)
) -> dict:
    return _chat_payload(await agents.chat.reset(layer))


def _chat_payload(session) -> dict:
    data = session.model_dump(mode="json")
    data["missing"] = session.slots.missing()
    data["is_complete"] = session.slots.is_complete
    return data


# ---------------------------------------------------------------- 試着


@router.post("/fitting")
async def api_fitting(
    body: FittingRequest,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    try:
        result = await agents.fitting.propose(
            layer_id=layer.layer_id,
            character=body.character,
            image_bytes=_decode_image(body.image_b64),
            limit=body.limit,
            request_note=body.request_note,
        )
    except IpGuardBlocked as exc:
        # 設計書 §7-4: 権利物の合成依頼は出力前に止める
        raise HTTPException(
            status_code=422,
            detail={"error": "ip_guard_blocked", "reasons": exc.reasons},
        )
    payload = result.model_dump(mode="json")
    payload.pop("character_hint", None)  # 内部入力は返さない
    return payload


# ---------------------------------------------------------------- 遠征


def _expedition_payload(exp: Expedition, extras: dict | None = None) -> dict:
    data = exp.model_dump(mode="json")
    data.pop("character", None)  # キャラ情報は内部入力に限定（§7-4）
    if data.get("fitting"):
        data["fitting"].pop("character_hint", None)
    if data.get("makeup"):
        for step, model in zip(data["makeup"]["steps"], exp.makeup.steps if exp.makeup else []):
            step["area_label"] = (
                model.area.label_ja if exp.lang.value == "ja" else model.area.label_en
            )
    if extras:
        data["extras"] = extras
    return data


@router.post("/expeditions", status_code=201)
async def api_create_expedition(
    body: ExpeditionCreate,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    if get_event(body.event_id) is None:
        raise HTTPException(status_code=404, detail="event not found")

    req = PlanRequest(
        layer_id=layer.layer_id,
        event_id=body.event_id,
        day=body.day,
        character=body.character,
        origin_station=body.origin_station,
        luggage_mode=body.luggage_mode or layer.prefs.luggage_mode,
        lang=body.lang or layer.lang,
        face_image=_decode_image(body.image_b64),
        include_fitting=body.include_fitting,
        attendance_factor=body.attendance_factor,
    )
    exp, extras = await agents.orchestrator.plan(req)
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


@router.post("/expeditions/{exp_id}/day-of")
async def api_day_of(
    exp_id: str,
    now: datetime | None = Query(default=None, description="デモ用の時刻上書き"),
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    """当日モードを1回進める。本番は Cloud Scheduler から定期起動する。"""
    exp = await agents.repository.get_expedition(exp_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="expedition not found")
    if exp.layer_id != layer.layer_id:
        raise HTTPException(status_code=403, detail="他の人の遠征は進められません")

    update = await agents.orchestrator.run_day_of(exp_id, now=now)
    return {
        "exp_id": update.exp_id,
        "route_delay_minutes": update.route_delay_minutes,
        "route_message": update.route_message,
        "dressing_alert": update.dressing_alert,
        "proposals": update.proposals,
        "notified": update.notified,
    }


# ---------------------------------------------------------------- 生成メディア（§11）


async def _owned_expedition(exp_id: str, agents: AgentBundle, layer: Layer) -> Expedition:
    exp = await agents.repository.get_expedition(exp_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="expedition not found")
    if exp.layer_id != layer.layer_id:
        raise HTTPException(status_code=403, detail="他の人の遠征は操作できません")
    return exp


@router.post("/expeditions/{exp_id}/look-image")
async def api_look_image(
    exp_id: str,
    body: LookImageRequest,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    """完成イメージを生成する（設計書 §11）。キャラ名はプロンプトに入れない。"""
    exp = await _owned_expedition(exp_id, agents, layer)
    try:
        asset = await agents.visual.look_image(
            layer_id=layer.layer_id, expedition=exp, request_note=body.request_note
        )
    except VisualIpGuardBlocked as exc:
        raise HTTPException(
            status_code=422, detail={"error": "ip_guard_blocked", "reasons": exc.reasons}
        )
    if asset is None:
        raise HTTPException(status_code=502, detail="完成イメージを生成できませんでした")

    exp.look_image = asset
    await agents.repository.save_expedition(exp)
    return asset.model_dump(mode="json")


@router.post("/expeditions/{exp_id}/voice-guide")
async def api_voice_guide(
    exp_id: str,
    body: VoiceGuideRequest,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    """メイク工程・動線の音声ガイド（設計書 §11）。台本も一緒に返す。"""
    exp = await _owned_expedition(exp_id, agents, layer)
    try:
        asset, script = await agents.voice.guide(
            layer_id=layer.layer_id,
            expedition=exp,
            section=body.section,
            request_note=body.request_note,
        )
    except VoiceCloneBlocked as exc:
        # 設計書 §11: ボイスクローンは使わない
        raise HTTPException(
            status_code=422, detail={"error": "voice_clone_blocked", "reasons": exc.reasons}
        )
    if asset is None:
        raise HTTPException(status_code=502, detail="音声を生成できませんでした")

    exp.voice_guides = [g for g in exp.voice_guides if g.kind is not asset.kind] + [asset]
    await agents.repository.save_expedition(exp)
    return {"asset": asset.model_dump(mode="json"), "script": script, "section": body.section}


# ---------------------------------------------------------------- 合わせ


def _awase_payload(awase: Awase, agents: AgentBundle) -> dict:
    data = awase.model_dump(mode="json")
    data["summary"] = agents.awase.summary(awase)
    data["ttl_at"] = awase.ttl_at.isoformat()
    return data


async def _load_awase(awase_id: str, agents: AgentBundle, layer: Layer) -> Awase:
    awase = await agents.repository.get_awase(awase_id)
    if awase is None:
        raise HTTPException(status_code=404, detail="awase not found")
    if awase.member(layer.layer_id) is None:
        raise HTTPException(status_code=403, detail="この合わせのメンバーではありません")
    return awase


@router.post("/awase", status_code=201)
async def api_create_awase(
    body: AwaseCreate,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    """作成者が主催者になる。招待相手はコス名で指定する。"""
    event = get_event(body.event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")

    day = event_day(body.day)  # 開場・閉場は JST 基準
    members = [
        AwaseMember(
            layer_id=layer.layer_id,
            handle=layer.handle,
            lang=layer.lang,
            is_organizer=True,
        )
    ]
    for invited in body.members:
        if invited.handle == layer.handle:
            continue
        member_layer = await _find_or_invite(agents, invited.handle, invited.lang)
        members.append(
            AwaseMember(
                layer_id=member_layer.layer_id,
                handle=member_layer.handle,
                lang=member_layer.lang,
            )
        )

    awase = Awase(
        awase_id=f"aw_{uuid.uuid4().hex[:8]}",
        title=body.title,
        event=EventRef(
            event_id=event.event_id,
            name=event.name,
            venue=event.venue,
            starts_at=day.replace(hour=event.opens_at_hour),
            ends_at=day.replace(hour=event.closes_at_hour),
        ),
        members=members,
    )
    await agents.repository.save_awase(awase)

    for member in members:
        if member.is_organizer:
            continue
        await agents.notifier.push(
            layer_id=member.layer_id,
            message=f"「{awase.title}」に招待されました。参加可否と進捗を登録してください。",
            kind=NotificationKind.AWASE_INVITE,
            lang=member.lang,
            awase_id=awase.awase_id,
        )
    return _awase_payload(awase, agents)


async def _find_or_invite(agents: AgentBundle, handle: str, lang) -> Layer:
    """コス名で既存アカウントを探し、無ければ未ログインのまま作る。

    相手がアプリを未導入でも合わせを組めるようにするため。本人が後で
    同じコス名でログインすると、このアカウントが引き継がれる。
    """
    found = await agents.repository.find_layer_by_handle(handle)
    if found is not None:
        return found
    invited = Layer(layer_id=f"ly_{uuid.uuid4().hex[:8]}", handle=handle, lang=lang)
    return await agents.repository.save_layer(invited)


@router.get("/awase/{awase_id}")
async def api_get_awase(
    awase_id: str,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    return _awase_payload(await _load_awase(awase_id, agents, layer), agents)


@router.post("/awase/{awase_id}/shoots", status_code=201)
async def api_add_shoot(
    awase_id: str,
    body: ShootCreate,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    awase = await _load_awase(awase_id, agents, layer)
    organizer = awase.organizer
    if organizer is None or organizer.layer_id != layer.layer_id:
        raise HTTPException(status_code=403, detail="撮影枠を置けるのは主催者だけです")

    awase.shoots.append(
        Shoot(
            shoot_id=f"sh_{uuid.uuid4().hex[:6]}",
            starts_at=body.starts_at,
            minutes=body.minutes,
            place=body.place,
            photographer=body.photographer,
            member_ids=body.member_ids,
        )
    )
    await agents.repository.save_awase(awase)
    return _awase_payload(awase, agents)


@router.post("/awase/{awase_id}/progress")
async def api_update_progress(
    awase_id: str,
    body: ProgressUpdate,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    """自分の進捗を更新する。主催者は幹事業務として代理入力もできる。"""
    awase = await _load_awase(awase_id, agents, layer)
    target_id = body.layer_id or layer.layer_id

    if target_id != layer.layer_id:
        organizer = awase.organizer
        if organizer is None or organizer.layer_id != layer.layer_id:
            raise HTTPException(
                status_code=403, detail="他のメンバーの進捗を変更できるのは主催者だけです"
            )
        await agents.repository.append_audit(
            AuditLog(
                log_id=f"log_{uuid.uuid4().hex[:8]}",
                actor=layer.layer_id,
                action=AuditAction.PROGRESS_UPDATED_BY_ORGANIZER,
                subject_id=awase_id,
                payload={"target": target_id, "progress": body.progress.value},
            )
        )

    try:
        updated = await agents.awase.update_progress(
            awase,
            target_id,
            body.progress,
            eta=body.eta,
            share_location=body.share_location,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="member not found")
    return _awase_payload(updated, agents)


@router.post("/awase/{awase_id}/monitor")
async def api_monitor(
    awase_id: str,
    now: datetime | None = Query(default=None, description="デモ用の時刻上書き"),
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    """到着監視。リスケが要るなら起案だけ作る（確定はしない）。"""
    awase = await _load_awase(awase_id, agents, layer)
    proposals = await agents.awase.monitor(awase, now=now)
    refreshed = await agents.repository.get_awase(awase_id) or awase
    return {
        "proposals": [p.model_dump(mode="json") for p in proposals],
        "awase": _awase_payload(refreshed, agents),
    }


@router.post("/awase/{awase_id}/proposals/{proposal_id}/decision")
async def api_decide(
    awase_id: str,
    proposal_id: str,
    body: DecisionIn,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    """設計書 §7-5: 主催者だけが枠の変更を確定できる。"""
    awase = await _load_awase(awase_id, agents, layer)
    try:
        updated, decided = await agents.awase.decide(
            awase, proposal_id, approved=body.approved, decided_by=layer.layer_id
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="proposal not found")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {
        "proposal": decided.model_dump(mode="json"),
        "awase": _awase_payload(updated, agents),
    }


@router.post("/awase/{awase_id}/after-movie")
async def api_after_movie(
    awase_id: str,
    body: AfterMovieRequest,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    """合わせのアフタームービーを作る（設計書 §11）。

    メンバー全員が写る成果物なので、作れるのは主催者だけにしている。
    """
    awase = await _load_awase(awase_id, agents, layer)
    organizer = awase.organizer
    if organizer is None or organizer.layer_id != layer.layer_id:
        raise HTTPException(status_code=403, detail="アフタームービーを作れるのは主催者だけです")
    if not body.image_urls:
        raise HTTPException(status_code=400, detail="撮影写真のURLを1枚以上指定してください")

    try:
        asset = await agents.visual.after_movie(
            layer_id=layer.layer_id,
            awase_id=awase_id,
            image_urls=body.image_urls,
            title=awase.title,
            lang=layer.lang,
            seconds=body.seconds,
            request_note=body.request_note,
        )
    except VisualIpGuardBlocked as exc:
        raise HTTPException(
            status_code=422, detail={"error": "ip_guard_blocked", "reasons": exc.reasons}
        )
    if asset is None:
        raise HTTPException(status_code=502, detail="アフタームービーを生成できませんでした")

    awase.after_movie = asset
    await agents.repository.save_awase(awase)
    await agents.notifier.broadcast(
        layer_ids=[m.layer_id for m in awase.members],
        message=f"「{awase.title}」のアフタームービーができました。",
        kind=NotificationKind.INFO,
        awase_id=awase_id,
    )
    return asset.model_dump(mode="json")


# ---------------------------------------------------------------- 監査


@router.get("/audit")
async def api_audit(
    subject_id: str | None = None,
    agents: AgentBundle = Depends(get_agents),
    layer: Layer = Depends(current_layer),
) -> dict:
    logs = await agents.repository.list_audit(subject_id=subject_id)
    return {"logs": [log.model_dump(mode="json") for log in logs]}


# ---------------------------------------------------------------- スケジューラ


def verify_tasks_token(x_tasks_token: str | None = Header(default=None)) -> None:
    """Cloud Scheduler から叩くバッチ用エンドポイントの保護。

    PWA を公開するためサービス全体が未認証許可になるので、Cloud Run の IAM では
    守れない。共有シークレットをアプリ側で突き合わせる。
    未設定のときはローカルだけ通し、それ以外は閉じる（開いたまま本番に出ない）。
    """
    settings = get_settings()
    if not settings.tasks_token:
        if settings.is_local:
            return
        raise HTTPException(
            status_code=503,
            detail="TASKS_TOKEN が未設定です。バッチ用エンドポイントは閉じています",
        )
    if not x_tasks_token or not secrets.compare_digest(
        x_tasks_token, settings.tasks_token
    ):
        raise HTTPException(status_code=403, detail="X-Tasks-Token が一致しません")


@router.post("/tasks/purge", dependencies=[Depends(verify_tasks_token)])
async def api_purge(
    now: datetime | None = Query(default=None),
    agents: AgentBundle = Depends(get_agents),
) -> dict:
    """設計書 §7-3: 期限切れの位置・進捗を削除する。Cloud Scheduler から叩く。"""
    purged = await agents.repository.purge_expired(now=now)
    return {"purged": purged, "count": len(purged)}


@router.post("/tasks/day-of", dependencies=[Depends(verify_tasks_token)])
async def api_day_of_batch(
    now: datetime | None = Query(default=None, description="デモ用の時刻上書き"),
    agents: AgentBundle = Depends(get_agents),
) -> dict:
    """その日の遠征をまとめて1回進める（設計書 §4 当日モードの自律進行）。

    利用者向けの `/api/expeditions/{id}/day-of` と違い、無人で回る入口。
    """
    updates = await agents.orchestrator.run_day_of_batch(now=now)
    return {
        "processed": len(updates),
        "notified": sum(u.notified for u in updates),
        "proposals": sum(len(u.proposals) for u in updates),
        "expeditions": [
            {
                "exp_id": u.exp_id,
                "route_delay_minutes": u.route_delay_minutes,
                "dressing_alert": bool(u.dressing_alert),
                "proposals": u.proposals,
            }
            for u in updates
        ],
    }
