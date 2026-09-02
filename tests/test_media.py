"""完成イメージ・アフタームービー・音声ガイド（設計書 §11 GMI Cloud 活用）。

生成そのものより、**生成の前後で守ると決めたこと**を検証する:
キャラ名を漏らさない、権利物の合成を止める、ボイスクローンを使わない、
AI生成であることを明示する、失敗しても遠征プランは壊れない。
"""

from __future__ import annotations

import base64

import pytest

from app.adapters.mock_media import MockImage, MockSpeech, MockVideo
from app.domain import guardrails
from app.domain.models import (
    CharacterRef,
    EventRef,
    Expedition,
    FittingCandidate,
    FittingKind,
    FittingResult,
    Lang,
)
from app.agents.visual import _selected_items, character_is_hidden
from tests.conftest import DAY

CHARACTER = {"title": "作品X", "name": "キャラY"}


def _plan(session, **overrides) -> dict:
    body = {
        "event_id": "acosta",
        "day": DAY.isoformat(),
        "character": CHARACTER,
        "origin_station": "新宿",
    }
    body.update(overrides)
    res = session.post("/api/expeditions", json=body)
    assert res.status_code == 201, res.text
    return res.json()


# ---------------------------------------------------------------- 完成イメージ


def test_look_image_is_generated_and_stored(user):
    exp = _plan(user)
    res = user.post(f"/api/expeditions/{exp['exp_id']}/look-image", json={})
    assert res.status_code == 200, res.text
    asset = res.json()

    assert asset["kind"] == "look_image"
    assert asset["url"].startswith("data:image/")  # モックでも実際に表示できる
    assert asset["watermarked"] is True
    assert asset["is_placeholder"] is True  # モックであることを隠さない
    assert asset["expires_at"]  # 参照は期限つき

    # 遠征に保存され、次に開いたときも見える
    stored = user.get(f"/api/expeditions/{exp['exp_id']}").json()
    assert stored["look_image"]["media_id"] == asset["media_id"]


def test_look_prompt_never_contains_the_character_name():
    """設計書 §7-4: キャラ名・作品名は生成の入力にも出さない。"""
    character = CharacterRef(title="作品X", name="キャラY", hair_color="銀", eye_color="赤")
    prompt = guardrails.build_look_prompt(character, wig="ロング", costume="制服")

    assert character_is_hidden(prompt, character)
    assert "銀" in prompt and "赤" in prompt  # 色味は渡す


def test_look_image_blocks_rights_infringing_requests(user):
    exp = _plan(user)
    res = user.post(
        f"/api/expeditions/{exp['exp_id']}/look-image",
        json={"request_note": "公式のイラストを背景に合成して"},
    )
    assert res.status_code == 422
    assert res.json()["detail"]["error"] == "ip_guard_blocked"

    logs = user.get("/api/audit", params={"subject_id": user.layer_id}).json()["logs"]
    assert any(log["action"] == "ip_guard_blocked" for log in logs)


def test_look_image_is_not_generated_for_other_peoples_expeditions(user, login):
    exp = _plan(user)
    stranger = login("別の人")
    res = stranger.post(f"/api/expeditions/{exp['exp_id']}/look-image", json={})
    assert res.status_code == 403


def test_selected_items_prefer_the_best_fitting_candidates():
    """試着候補のうち、適合度がいちばん高いウィッグと衣装を使う。"""
    exp = Expedition(
        exp_id="exp_test",
        layer_id="ly_test",
        event=EventRef(
            event_id="acosta",
            name="acosta!",
            venue="池袋",
            starts_at=DAY,
            ends_at=DAY,
        ),
        character=CharacterRef(title="作品X", name="キャラY"),
        fitting=FittingResult(
            character_hint="内部入力",
            candidates=[
                FittingCandidate(
                    candidate_id="w1", kind=FittingKind.WIG, label="いまいちウィッグ", fit_score=0.4
                ),
                FittingCandidate(
                    candidate_id="w2", kind=FittingKind.WIG, label="best ウィッグ", fit_score=0.9
                ),
                FittingCandidate(
                    candidate_id="c1", kind=FittingKind.COSTUME, label="best 衣装", fit_score=0.8
                ),
            ],
        ),
    )
    assert _selected_items(exp) == ("best ウィッグ", "best 衣装")


def test_selected_items_fall_back_before_fitting_runs():
    """試着前でも完成イメージは出せる（購入前の判断を支えるのが目的）。"""
    exp = Expedition(
        exp_id="exp_test",
        layer_id="ly_test",
        event=EventRef(
            event_id="acosta", name="acosta!", venue="池袋", starts_at=DAY, ends_at=DAY
        ),
        character=CharacterRef(title="作品X", name="キャラY"),
    )
    wig, costume = _selected_items(exp)
    assert wig and costume


# ---------------------------------------------------------------- 音声ガイド


def test_voice_guide_reads_the_makeup_steps(user):
    exp = _plan(user)
    res = user.post(
        f"/api/expeditions/{exp['exp_id']}/voice-guide", json={"section": "makeup"}
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["asset"]["kind"] == "voice_guide"
    assert body["asset"]["url"].startswith("data:audio/wav")  # 実際に再生できる
    assert body["asset"]["seconds"] > 0
    # 台本は工程数ぶんの案内を含む
    assert "9工程" in body["script"] or "9 makeup steps" in body["script"]
    assert "1番目" in body["script"]


def test_voice_guide_reads_the_route(user):
    exp = _plan(user)
    body = user.post(
        f"/api/expeditions/{exp['exp_id']}/voice-guide", json={"section": "route"}
    ).json()
    script = body["script"]
    assert "出発は" in script
    assert "区間目" in script
    # 記号ではなく文で読ませる（読み上げ向けの台本になっている）
    assert "→" not in script


def test_voice_guide_follows_the_layers_language(login):
    visitor = login("Visitor")
    visitor.patch("/api/me", json={"lang": "en"})
    exp = _plan(visitor, character={"title": "Series A", "name": "Character B"})

    body = visitor.post(
        f"/api/expeditions/{exp['exp_id']}/voice-guide", json={"section": "makeup"}
    ).json()
    assert body["asset"]["lang"] == "en"
    assert "Step 1," in body["script"]


def test_voice_cloning_is_refused(user):
    """設計書 §11: ボイスクローンは使わない。"""
    exp = _plan(user)
    res = user.post(
        f"/api/expeditions/{exp['exp_id']}/voice-guide",
        json={"section": "makeup", "request_note": "キャラの声でクローンして読んで"},
    )
    assert res.status_code == 422
    assert res.json()["detail"]["error"] == "voice_clone_blocked"

    logs = user.get("/api/audit", params={"subject_id": user.layer_id}).json()["logs"]
    assert any(log["action"] == "voice_clone_blocked" for log in logs)


@pytest.mark.parametrize(
    "note",
    ["声をクローンして", "voice cloning please", "声優の声で読んで"],
)
def test_voice_clone_wording_is_caught(note: str):
    assert guardrails.screen_voice_request(note).blocked


def test_ordinary_voice_requests_pass():
    assert guardrails.screen_voice_request("ゆっくり読んでください").allowed


def test_regenerating_replaces_the_previous_guide(user):
    exp = _plan(user)
    for _ in range(2):
        user.post(f"/api/expeditions/{exp['exp_id']}/voice-guide", json={"section": "makeup"})

    stored = user.get(f"/api/expeditions/{exp['exp_id']}").json()
    assert len(stored["voice_guides"]) == 1  # 溜め込まない


# ---------------------------------------------------------------- アフタームービー


def test_after_movie_is_organizer_only(user, login):
    awase = user.post(
        "/api/awase",
        json={
            "title": "PVテスト",
            "event_id": "acosta",
            "day": DAY.isoformat(),
            "members": [{"handle": "Aさん"}],
        },
    ).json()
    member = login("Aさん")

    payload = {"image_urls": ["https://example.com/1.jpg"], "seconds": 5}
    assert member.post(f"/api/awase/{awase['awase_id']}/after-movie", json=payload).status_code == 403

    res = user.post(f"/api/awase/{awase['awase_id']}/after-movie", json=payload)
    assert res.status_code == 200, res.text
    assert res.json()["kind"] == "after_movie"


def test_after_movie_needs_photos(user):
    awase = user.post(
        "/api/awase",
        json={"title": "写真なし", "event_id": "acosta", "day": DAY.isoformat()},
    ).json()
    res = user.post(f"/api/awase/{awase['awase_id']}/after-movie", json={"image_urls": []})
    assert res.status_code == 400


def test_after_movie_notifies_every_member(user, login):
    awase = user.post(
        "/api/awase",
        json={
            "title": "通知テスト",
            "event_id": "acosta",
            "day": DAY.isoformat(),
            "members": [{"handle": "Bさん"}],
        },
    ).json()
    user.post(
        f"/api/awase/{awase['awase_id']}/after-movie",
        json={"image_urls": ["https://example.com/1.jpg"]},
    )

    member = login("Bさん")
    messages = [n["message"] for n in member.get("/api/me/notifications").json()["notifications"]]
    assert any("アフタームービー" in m for m in messages)


# ---------------------------------------------------------------- モック実装


async def test_mock_image_returns_a_decodable_svg():
    asset = await MockImage().generate_look("テスト", lang=Lang.JA)
    payload = asset.url.split(",", 1)[1]
    svg = base64.b64decode(payload).decode("utf-8")
    assert svg.startswith("<svg")
    assert "AI生成" in svg  # 生成物である表示が入っている


async def test_mock_speech_returns_a_playable_wav():
    asset = await MockSpeech().synthesize("読み上げます", lang=Lang.JA)
    payload = asset.url.split(",", 1)[1]
    audio = base64.b64decode(payload)
    assert audio[:4] == b"RIFF" and audio[8:12] == b"WAVE"
    assert asset.seconds == 1.0


async def test_mock_speech_ignores_empty_text():
    assert await MockSpeech().synthesize("   ") is None


async def test_mock_video_needs_at_least_one_photo():
    video = MockVideo()
    assert await video.generate_after_movie(image_urls=[], prompt="x") is None
    asset = await video.generate_after_movie(
        image_urls=["https://example.com/1.jpg"], prompt="x", seconds=10
    )
    assert asset.seconds == 10.0
    assert asset.is_placeholder is True
