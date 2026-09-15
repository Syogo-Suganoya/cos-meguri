"""FastAPI の依存関係。アダプタ束からエージェント群を組み立て、認証を挟む。"""

from __future__ import annotations

import uuid
from functools import lru_cache

from fastapi import Depends, Header, HTTPException

from app.adapters.registry import Adapters, get_adapters
from app.agents.chat import ChatAgent
from app.agents.i18n import I18nAgent
from app.agents.makeup import MakeupAgent
from app.agents.orchestrator import Orchestrator
from app.agents.route import RouteAgent
from app.domain.models import AuditAction, AuditLog, ChatSession, ChatSlots, Layer
from app.ports.auth import AuthError, AuthIdentity


class AgentBundle:
    def __init__(self, adapters: Adapters) -> None:
        self.adapters = adapters
        self.repository = adapters.repository
        self.auth = adapters.auth
        self.makeup = MakeupAgent(adapters.llm)
        self.route = RouteAgent(adapters.transit, adapters.llm)
        self.i18n = I18nAgent(adapters.llm)
        self.orchestrator = Orchestrator(
            makeup=self.makeup,
            route=self.route,
            i18n=self.i18n,
            repository=adapters.repository,
        )
        self.chat = ChatAgent(self.orchestrator, adapters.repository)

    async def resolve_layer(self, token: str) -> Layer:
        """トークンを検証し、アカウントを引く（無ければ作る）。"""
        return (await self.resolve(token)).layer

    async def resolve(self, token: str) -> "Principal":
        """トークンを検証し、身元とアカウントを返す。

        認証基盤から受け取るのは uid と「ゲストかどうか」だけ。メールアドレス等は保存しない。
        ゲスト（匿名ログイン）にもアカウントを作る。相談の条件とプランの置き場所が要るため。
        """
        identity = await self.auth.verify(token)

        layer = await self.repository.get_layer_by_uid(identity.uid)
        if layer is not None:
            return Principal(identity, layer)

        layer = Layer(
            layer_id=f"ly_{uuid.uuid4().hex[:8]}",
            auth_uid=identity.uid,
        )
        await self.repository.save_layer(layer)
        await self.repository.append_audit(
            AuditLog(
                log_id=f"log_{uuid.uuid4().hex[:8]}",
                actor=layer.layer_id,
                action=AuditAction.ACCOUNT_LINKED,
                subject_id=layer.layer_id,
                layer_ids=[layer.layer_id],
                payload={
                    "provider": identity.provider,
                    "guest": identity.anonymous,
                    # uid そのものは payload に残さない（監査ログから辿れないようにする）
                    "stores_email": False,
                },
            )
        )
        return Principal(identity, layer)

    async def adopt_guest(self, member: Layer, guest_token: str) -> bool:
        """ゲストのあいだに組んだ条件とプランを、ログインした本人へ移す。移したら True。

        移すのは「相談の条件」と「ゲストの遠征」。移さないのは次のとき。
          - 渡されたトークンがゲストのものではない（他人のアカウントから吸い上げさせない）
          - ゲストが何も入れていない（本人の条件を空で上書きしない）
          - ゲストは組み上がっておらず、本人はプランを持っている（下書きで完成品を潰さない）
        """
        identity = await self.auth.verify(guest_token)
        if not identity.anonymous:
            raise AuthError("ゲストのログイン情報ではありません")
        guest = await self.repository.get_layer_by_uid(identity.uid)
        if guest is None or guest.layer_id == member.layer_id:
            return False

        draft = await self.repository.get_chat(guest.layer_id)
        if draft is None or not any(
            getattr(draft.slots, name) for name in ChatSlots.model_fields if name != "luggage_mode"
        ):
            return False
        current = await self.repository.get_chat(member.layer_id)
        if draft.exp_id is None and current is not None and current.exp_id is not None:
            return False

        for exp in await self.repository.list_expeditions(guest.layer_id):
            exp.layer_id = member.layer_id
            await self.repository.save_expedition(exp)
        await self.repository.save_chat(draft.model_copy(update={"layer_id": member.layer_id}))
        # ゲスト側には条件を残さない（キャラ名が持ち主のいない場所に残り続けないように）
        await self.repository.save_chat(ChatSession(layer_id=guest.layer_id, lang=guest.lang))
        return True


class Principal:
    """1リクエストぶんの「誰か」。ゲストかどうかはトークンが決める（保存しない）。"""

    def __init__(self, identity: AuthIdentity, layer: Layer) -> None:
        self.identity = identity
        self.layer = layer

    @property
    def guest(self) -> bool:
        return self.identity.anonymous


@lru_cache
def get_agents() -> AgentBundle:
    return AgentBundle(get_adapters())


async def current_principal(
    authorization: str | None = Header(default=None),
    agents: AgentBundle = Depends(get_agents),
) -> Principal:
    """`Authorization: Bearer <ID トークン>` から本人を解決する。ゲストもここを通る。

    FastAPI は同じリクエストの中で依存を1回しか解かないので、
    current_layer と member_layer を併用してもトークンの検証は1回で済む。
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="ログインが必要です")
    token = authorization.split(" ", 1)[1].strip()
    try:
        return await agents.resolve(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


async def current_layer(principal: Principal = Depends(current_principal)) -> Layer:
    """ゲストでもよい操作（相談・プラン）。"""
    return principal.layer


async def member_layer(principal: Principal = Depends(current_principal)) -> Layer:
    """ログインした人だけの操作（お気に入り）。ゲストは 403 で、画面が登録を案内する。"""
    if principal.guest:
        raise HTTPException(
            status_code=403,
            detail={"error": "お気に入りはログインすると使えます", "reason": "guest", "code": "guest"},
        )
    return principal.layer
