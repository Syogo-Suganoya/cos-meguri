"""合わせ（グループ）のオーケストレーション（設計書 §4 合わせエージェント）。

自律でやるのは「進捗の集計・到着監視・リスケの起案」まで。
枠の確定は必ず主催者の承認を通す（設計書 §7-5）。
位置共有は当日限定で、期限切れは値ごと落とす（設計書 §7-3）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from app.domain.models import (
    Awase,
    AwaseMember,
    LocationShare,
    MemberProgress,
    RescheduleProposal,
    Shoot,
    utcnow,
)

# 撮影枠までにこの分数を切ったら「間に合わない」と判定する
SETUP_BUFFER_MINUTES = 15
# リスケ起案の最小遅延。これ未満のズレでは起案しない
MIN_DELAY_MINUTES = 10


def progress_summary(awase: Awase) -> dict:
    """メンバー進捗の集計。誰が遅れているかを一覧で返す。"""
    counts: dict[str, int] = {p.value: 0 for p in MemberProgress}
    for m in awase.members:
        counts[m.progress.value] += 1
    total = len(awase.members) or 1
    ready = sum(1 for m in awase.members if m.progress.rank >= MemberProgress.ARRIVED.rank)
    return {
        "total": len(awase.members),
        "counts": counts,
        "ready": ready,
        "ready_ratio": round(ready / total, 2),
        "slowest": min(awase.members, key=lambda m: m.progress.rank).handle
        if awase.members
        else None,
    }


def enable_location_share(
    member: AwaseMember, event_ends_at: datetime, *, eta: datetime | None = None
) -> AwaseMember:
    """位置共有を当日限定で有効化する。期限はイベント終了 +24h。"""
    updated = member.model_copy(deep=True)
    updated.location = LocationShare(
        enabled=True,
        eta=eta,
        expires_at=event_ends_at + timedelta(hours=24),
    )
    return updated


def purge_expired_locations(awase: Awase, *, now: datetime | None = None) -> tuple[Awase, list[str]]:
    """期限切れの位置共有を落とす。落とした layer_id を返す（監査ログ用）。"""
    now = now or utcnow()
    updated = awase.model_copy(deep=True)
    purged: list[str] = []
    for m in updated.members:
        if m.location.enabled and not m.location.is_active(now):
            m.location = m.location.redacted()
            purged.append(m.layer_id)
    return updated, purged


def late_members(
    awase: Awase, shoot: Shoot, *, now: datetime | None = None
) -> list[AwaseMember]:
    """撮影枠に間に合わないメンバーを、ETA と進捗の両面から拾う。"""
    now = now or utcnow()
    deadline = shoot.starts_at - timedelta(minutes=SETUP_BUFFER_MINUTES)
    out: list[AwaseMember] = []
    for m in awase.members:
        if shoot.member_ids and m.layer_id not in shoot.member_ids:
            continue
        if m.progress is MemberProgress.DRESSED:
            continue
        eta = m.location.eta if m.location.is_active(now) else None
        if eta and eta > deadline:
            out.append(m)
        elif eta is None and now >= deadline and m.progress.rank < MemberProgress.ARRIVED.rank:
            # 位置共有オフのメンバーは進捗申告だけで判断する
            out.append(m)
    return out


def propose_reschedule(
    awase: Awase, shoot: Shoot, *, now: datetime | None = None
) -> RescheduleProposal | None:
    """遅れているメンバーに合わせた新枠を起案する。確定はしない。"""
    now = now or utcnow()
    blockers = late_members(awase, shoot, now=now)
    if not blockers:
        return None

    etas = [m.location.eta for m in blockers if m.location.is_active(now) and m.location.eta]
    if etas:
        ready_at = max(etas) + timedelta(minutes=SETUP_BUFFER_MINUTES)
    else:
        # ETA が無い場合は着替え時間ぶんを見込んで一律で押す
        ready_at = max(now, shoot.starts_at) + timedelta(minutes=30)

    delay = int((ready_at - shoot.starts_at).total_seconds() // 60)
    if delay < MIN_DELAY_MINUTES:
        return None

    # 5分刻みに丸める
    delay = int(round(delay / 5) * 5)
    proposed = shoot.starts_at + timedelta(minutes=delay)
    handles = "・".join(m.handle for m in blockers)

    return RescheduleProposal(
        proposal_id=f"prop_{uuid.uuid4().hex[:8]}",
        awase_id=awase.awase_id,
        shoot_id=shoot.shoot_id,
        current_start=shoot.starts_at,
        proposed_start=proposed,
        delay_minutes=delay,
        reason=(
            f"{handles}が枠のはじまる{SETUP_BUFFER_MINUTES}分前に間に合いません。"
            f"{delay}分うしろにずらす案です（決めるのは主催者です）"
        ),
        blocking_members=[m.layer_id for m in blockers],
    )


def apply_decision(
    awase: Awase,
    proposal: RescheduleProposal,
    *,
    approved: bool,
    decided_by: str,
    now: datetime | None = None,
) -> tuple[Awase, RescheduleProposal]:
    """主催者の承認/却下を反映する。承認時のみ撮影枠を動かす。"""
    now = now or utcnow()
    if proposal.status != "proposed":
        raise ValueError(f"already decided: {proposal.proposal_id}")

    organizer = awase.organizer
    if organizer is None or decided_by != organizer.layer_id:
        raise PermissionError("リスケの確定は合わせ主催者のみが行えます")

    updated_awase = awase.model_copy(deep=True)
    updated_proposal = proposal.model_copy(deep=True)
    updated_proposal.status = "approved" if approved else "rejected"
    updated_proposal.decided_by = decided_by
    updated_proposal.decided_at = now

    if approved:
        for s in updated_awase.shoots:
            if s.shoot_id == proposal.shoot_id:
                s.starts_at = proposal.proposed_start

    updated_awase.proposals = [
        updated_proposal if p.proposal_id == proposal.proposal_id else p
        for p in updated_awase.proposals
    ]
    if all(p.proposal_id != proposal.proposal_id for p in updated_awase.proposals):
        updated_awase.proposals.append(updated_proposal)

    return updated_awase, updated_proposal


def should_purge(awase: Awase, *, now: datetime | None = None) -> bool:
    """TTL（イベント終了 +24h）に達したか。Cloud Scheduler から回す。"""
    return (now or utcnow()) >= awase.ttl_at
