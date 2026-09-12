"""合わせの承認制と、プライバシー設計（設計書 §7-3 / §7-4 / §7-5）の検証。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.adapters.in_app_notifier import InAppNotifier
from app.adapters.memory_repo import MemoryRepository
from app.agents.awase import AwaseAgent
from app.domain import awase as awase_rules
from app.domain import guardrails
from app.domain.models import (
    AuditAction,
    Awase,
    AwaseMember,
    CharacterRef,
    EventRef,
    MemberProgress,
    NotificationKind,
    Shoot,
)

DAY = datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc)
EVENT = EventRef(
    event_id="acosta",
    name="acosta!",
    venue="池袋・ハレザ",
    starts_at=DAY,
    ends_at=DAY.replace(hour=17),
)


def make_awase() -> Awase:
    return Awase(
        awase_id="aw_test",
        title="テスト合わせ",
        event=EVENT,
        members=[
            AwaseMember(layer_id="ly_org", handle="幹事", is_organizer=True),
            AwaseMember(layer_id="ly_a", handle="Aさん"),
            AwaseMember(layer_id="ly_b", handle="Bさん"),
        ],
        shoots=[
            Shoot(shoot_id="sh_1", starts_at=DAY.replace(hour=13), place="屋上", minutes=30)
        ],
    )


def test_proposal_is_created_when_member_cannot_make_it():
    awase = make_awase()
    late = awase.members[1]
    late.location = awase_rules.enable_location_share(
        late, EVENT.ends_at, eta=DAY.replace(hour=13, minute=20)
    ).location
    awase.members[1] = late

    proposal = awase_rules.propose_reschedule(
        awase, awase.shoots[0], now=DAY.replace(hour=12)
    )
    assert proposal is not None
    assert proposal.status == "proposed"
    assert proposal.proposed_start > awase.shoots[0].starts_at
    assert "ly_a" in proposal.blocking_members


def test_no_proposal_when_everyone_is_on_time():
    awase = make_awase()
    for m in awase.members:
        m.progress = MemberProgress.DRESSED
    assert (
        awase_rules.propose_reschedule(awase, awase.shoots[0], now=DAY.replace(hour=12))
        is None
    )


def test_shoot_does_not_move_until_organizer_approves():
    """設計書 §7-5: 起案しただけでは枠は動かない。"""
    awase = make_awase()
    late = awase.members[1]
    late.location = awase_rules.enable_location_share(
        late, EVENT.ends_at, eta=DAY.replace(hour=13, minute=30)
    ).location

    proposal = awase_rules.propose_reschedule(awase, awase.shoots[0], now=DAY.replace(hour=12))
    awase.proposals.append(proposal)
    assert awase.shoots[0].starts_at == DAY.replace(hour=13)  # まだ動いていない

    approved, decided = awase_rules.apply_decision(
        awase, proposal, approved=True, decided_by="ly_org"
    )
    assert decided.status == "approved"
    assert approved.shoots[0].starts_at == proposal.proposed_start


def test_non_organizer_cannot_confirm_reschedule():
    awase = make_awase()
    late = awase.members[1]
    late.location = awase_rules.enable_location_share(
        late, EVENT.ends_at, eta=DAY.replace(hour=13, minute=30)
    ).location
    proposal = awase_rules.propose_reschedule(awase, awase.shoots[0], now=DAY.replace(hour=12))
    awase.proposals.append(proposal)

    with pytest.raises(PermissionError):
        awase_rules.apply_decision(awase, proposal, approved=True, decided_by="ly_a")


def test_rejected_proposal_leaves_shoot_untouched():
    awase = make_awase()
    late = awase.members[1]
    late.location = awase_rules.enable_location_share(
        late, EVENT.ends_at, eta=DAY.replace(hour=13, minute=30)
    ).location
    proposal = awase_rules.propose_reschedule(awase, awase.shoots[0], now=DAY.replace(hour=12))
    awase.proposals.append(proposal)

    updated, decided = awase_rules.apply_decision(
        awase, proposal, approved=False, decided_by="ly_org"
    )
    assert decided.status == "rejected"
    assert updated.shoots[0].starts_at == DAY.replace(hour=13)


def test_location_share_goes_inactive_after_the_event():
    """終了+24h を過ぎた位置共有は、失効として扱う（ETA も採らない）。"""
    awase = make_awase()
    member = awase.members[1]
    member.location = awase_rules.enable_location_share(
        member, EVENT.ends_at, eta=DAY.replace(hour=12)
    ).location
    assert member.location.is_active(DAY.replace(hour=12))
    assert not member.location.is_active(EVENT.ends_at + timedelta(hours=25))


async def test_agent_monitor_notifies_organizer_and_logs():
    repo = MemoryRepository()
    notifier = InAppNotifier(repo)
    agent = AwaseAgent(repo, notifier)
    awase = make_awase()
    member = awase.members[1]
    member.location = awase_rules.enable_location_share(
        member, EVENT.ends_at, eta=DAY.replace(hour=13, minute=40)
    ).location
    await repo.save_awase(awase)

    proposals = await agent.monitor(awase, now=DAY.replace(hour=12))
    assert len(proposals) == 1

    # 外部サービスではなく、主催者のアプリ内お知らせに積まれる
    inbox = await notifier.inbox("ly_org")
    assert inbox and inbox[0].kind is NotificationKind.RESCHEDULE_REQUEST
    assert "承認待ち" in inbox[0].message
    assert await notifier.inbox("ly_a") == []

    logs = await repo.list_audit(subject_id="aw_test")
    assert any(log.action is AuditAction.RESCHEDULE_PROPOSED for log in logs)

    # 同じ枠に起案を重ねない
    refreshed = await repo.get_awase("aw_test")
    assert await agent.monitor(refreshed, now=DAY.replace(hour=12, minute=30)) == []


def test_character_names_are_stripped_from_shared_text():
    char = CharacterRef(title="作品X", name="キャラY")
    text = "今日は作品XのキャラYで参加します"
    assert guardrails.shareable_summary(text, char) == "今日は＊＊の＊＊で参加します"


def test_records_are_scoped_to_the_person_they_belong_to(user, login):
    """記録は本人ぶんだけ返す。以前は絞り込み無しで全員ぶんが見えていた。"""
    mine = user.get("/api/audit").json()["logs"]
    assert mine, "自分の記録が1件も無い"
    assert all(user.layer_id in log["layer_ids"] for log in mine)

    # 他人の記録は1件も混ざらない（自分のログイン記録だけが見える）
    stranger = login("無関係な人")
    theirs = stranger.get("/api/audit").json()["logs"]
    assert all(stranger.layer_id in log["layer_ids"] for log in theirs)
    assert not any(log["action"] == "face_image_discarded" for log in theirs)
