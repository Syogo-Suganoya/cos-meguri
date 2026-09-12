"""FastAPI の依存関係。アダプタ束からエージェント群を組み立て、認証を挟む。"""

from __future__ import annotations

import uuid
from functools import lru_cache

from fastapi import Depends, Header, HTTPException

from app.adapters.registry import Adapters, get_adapters
from app.agents.awase import AwaseAgent
from app.agents.chat import ChatAgent
from app.agents.dressing import DressingAgent
from app.agents.i18n import I18nAgent
from app.agents.makeup import MakeupAgent
from app.agents.orchestrator import Orchestrator
from app.agents.route import RouteAgent
from app.domain.models import AuditAction, AuditLog, Layer
from app.ports.auth import AuthError


class AgentBundle:
    def __init__(self, adapters: Adapters) -> None:
        self.adapters = adapters
        self.repository = adapters.repository
        self.notifier = adapters.notifier
        self.auth = adapters.auth
        self.makeup = MakeupAgent(adapters.llm)
        self.route = RouteAgent(adapters.transit, adapters.llm)
        self.dressing = DressingAgent(adapters.llm)
        self.awase = AwaseAgent(adapters.repository, adapters.notifier)
        self.i18n = I18nAgent(adapters.llm)
        self.orchestrator = Orchestrator(
            makeup=self.makeup,
            route=self.route,
            dressing=self.dressing,
            awase=self.awase,
            i18n=self.i18n,
            repository=adapters.repository,
            notifier=adapters.notifier,
        )
        self.chat = ChatAgent(self.orchestrator, adapters.llm, adapters.repository)

    async def resolve_layer(self, token: str, *, handle: str | None = None) -> Layer:
        """トークンを検証し、コス名アカウントを引く（無ければ作る）。

        認証基盤から受け取るのは uid だけ。メールアドレス等は保存しない。
        """
        identity = await self.auth.verify(token)

        layer = await self.repository.get_layer_by_uid(identity.uid)
        if layer is not None:
            return layer

        # 招待だけされていた（auth_uid が未設定の）アカウントがあれば引き継ぐ
        wanted = (handle or identity.suggested_handle or "").strip()
        if wanted:
            pending = await self.repository.find_layer_by_handle(wanted)
            if pending is not None and pending.is_pending:
                pending.auth_uid = identity.uid
                await self.repository.save_layer(pending)
                await self._log_link(pending, identity.provider, linked_pending=True)
                return pending

        layer = Layer(
            layer_id=f"ly_{uuid.uuid4().hex[:8]}",
            handle=wanted or f"layer_{identity.uid[:6]}",
            auth_uid=identity.uid,
        )
        await self.repository.save_layer(layer)
        await self._log_link(layer, identity.provider, linked_pending=False)
        return layer

    async def _log_link(self, layer: Layer, provider: str, *, linked_pending: bool) -> None:
        await self.repository.append_audit(
            AuditLog(
                log_id=f"log_{uuid.uuid4().hex[:8]}",
                actor=layer.layer_id,
                action=AuditAction.ACCOUNT_LINKED,
                subject_id=layer.layer_id,
                layer_ids=[layer.layer_id],
                payload={
                    "provider": provider,
                    "linked_pending_account": linked_pending,
                    # uid そのものは payload に残さない（監査ログから辿れないようにする）
                    "stores_email": False,
                },
            )
        )


@lru_cache
def get_agents() -> AgentBundle:
    return AgentBundle(get_adapters())


async def current_layer(
    authorization: str | None = Header(default=None),
    agents: AgentBundle = Depends(get_agents),
) -> Layer:
    """`Authorization: Bearer <ID トークン>` から本人を解決する。"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="ログインが必要です")
    token = authorization.split(" ", 1)[1].strip()
    try:
        return await agents.resolve_layer(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
