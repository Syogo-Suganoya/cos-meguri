"""合わせエージェント（設計書 §4）。起案までが自律、確定は主催者承認。

「勝手に枠を動かさない」ことがこのエージェントの設計上の核なので、
承認と却下の両方を必ず監査ログに残す（設計書 §7-5）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.domain import awase as awase_rules
from app.domain.models import (
    AuditAction,
    AuditLog,
    Awase,
    AwaseMember,
    MemberProgress,
    NotificationKind,
    RescheduleProposal,
    Shoot,
    jst_hm,
    utcnow,
)
from app.ports.notifier import NotifierPort
from app.ports.repository import RepositoryPort


class AwaseAgent:
    def __init__(self, repository: RepositoryPort, notifier: NotifierPort) -> None:
        self.repository = repository
        self.notifier = notifier

    # -- 進捗 -----------------------------------------------------------
    async def update_progress(
        self,
        awase: Awase,
        layer_id: str,
        progress: MemberProgress,
        *,
        eta: datetime | None = None,
        share_location: bool = False,
    ) -> Awase:
        member = awase.member(layer_id)
        if member is None:
            raise KeyError(f"member not in awase: {layer_id}")

        updated = awase.model_copy(deep=True)
        for m in updated.members:
            if m.layer_id != layer_id:
                continue
            m.progress = progress
            if share_location:
                shared = awase_rules.enable_location_share(m, awase.event.ends_at, eta=eta)
                m.location = shared.location
            elif eta and m.location.enabled:
                m.location.eta = eta

        if share_location:
            await self.repository.append_audit(
                AuditLog(
                    log_id=f"log_{uuid.uuid4().hex[:8]}",
                    actor=layer_id,
                    action=AuditAction.LOCATION_SHARE_ENABLED,
                    subject_id=awase.awase_id,
                    payload={
                        "expires_at": (awase.event.ends_at).isoformat(),
                        "scope": "event_day_only",
                    },
                )
            )

        return await self.repository.save_awase(updated)

    def summary(self, awase: Awase) -> dict:
        return awase_rules.progress_summary(awase)

    # -- 到着監視・リスケ起案 -------------------------------------------
    async def monitor(self, awase: Awase, *, now: datetime | None = None) -> list[RescheduleProposal]:
        """全撮影枠を見て、間に合わない枠のリスケを起案する（確定はしない）。"""
        now = now or utcnow()
        updated = awase.model_copy(deep=True)
        created: list[RescheduleProposal] = []

        for shoot in updated.shoots:
            if shoot.starts_at < now:
                continue
            if any(
                p.shoot_id == shoot.shoot_id and p.status == "proposed"
                for p in updated.proposals
            ):
                continue  # 同じ枠に起案を重ねない
            proposal = awase_rules.propose_reschedule(updated, shoot, now=now)
            if proposal is None:
                continue

            updated.proposals.append(proposal)
            created.append(proposal)
            await self.repository.append_audit(
                AuditLog(
                    log_id=f"log_{uuid.uuid4().hex[:8]}",
                    actor="awase-agent",
                    action=AuditAction.RESCHEDULE_PROPOSED,
                    subject_id=awase.awase_id,
                    payload={
                        "proposal_id": proposal.proposal_id,
                        "shoot_id": proposal.shoot_id,
                        "delay_minutes": proposal.delay_minutes,
                    },
                )
            )

        if created:
            await self.repository.save_awase(updated)
            organizer = updated.organizer
            if organizer:
                for p in created:
                    await self.notifier.push(
                        layer_id=organizer.layer_id,
                        message=(
                            f"【承認待ち】{jst_hm(p.current_start)}の枠を"
                            f"{jst_hm(p.proposed_start)}へ後ろ倒しする起案があります。{p.reason}"
                        ),
                        kind=NotificationKind.RESCHEDULE_REQUEST,
                        lang=organizer.lang,
                        awase_id=awase.awase_id,
                    )
        return created

    async def decide(
        self,
        awase: Awase,
        proposal_id: str,
        *,
        approved: bool,
        decided_by: str,
    ) -> tuple[Awase, RescheduleProposal]:
        """主催者の承認/却下。ここを通らない限り枠は動かない。"""
        proposal = next(
            (p for p in awase.proposals if p.proposal_id == proposal_id), None
        )
        if proposal is None:
            raise KeyError(f"proposal not found: {proposal_id}")

        updated, decided = awase_rules.apply_decision(
            awase, proposal, approved=approved, decided_by=decided_by
        )
        await self.repository.save_awase(updated)
        await self.repository.append_audit(
            AuditLog(
                log_id=f"log_{uuid.uuid4().hex[:8]}",
                actor=decided_by,
                action=AuditAction.RESCHEDULE_APPROVED
                if approved
                else AuditAction.RESCHEDULE_REJECTED,
                subject_id=awase.awase_id,
                payload={
                    "proposal_id": proposal_id,
                    "shoot_id": decided.shoot_id,
                    "proposed_start": decided.proposed_start.isoformat(),
                },
            )
        )

        message = (
            f"撮影枠を{jst_hm(decided.current_start)}→{jst_hm(decided.proposed_start)}に"
            "変更しました（主催者承認済み）"
            if approved
            else f"{jst_hm(decided.current_start)}の枠は変更しません（主催者が却下）"
        )
        await self.notifier.broadcast(
            layer_ids=[m.layer_id for m in updated.members],
            message=message,
            kind=NotificationKind.RESCHEDULE_RESULT,
            awase_id=awase.awase_id,
        )
        return updated, decided

    # -- 招集 -----------------------------------------------------------
    async def invite(self, awase: Awase, members: list[AwaseMember]) -> Awase:
        updated = awase.model_copy(deep=True)
        known = {m.layer_id for m in updated.members}
        for m in members:
            if m.layer_id not in known:
                updated.members.append(m)
        saved = await self.repository.save_awase(updated)
        for m in members:
            await self.notifier.push(
                layer_id=m.layer_id,
                message=f"「{awase.title}」に招待されました。参加可否と進捗を登録してください。",
                kind=NotificationKind.AWASE_INVITE,
                lang=m.lang,
                awase_id=awase.awase_id,
            )
        return saved

    def next_shoot(self, awase: Awase, *, now: datetime | None = None) -> Shoot | None:
        now = now or utcnow()
        upcoming = [s for s in awase.shoots if s.starts_at >= now]
        return min(upcoming, key=lambda s: s.starts_at) if upcoming else None
