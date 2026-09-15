"""ログインしなくても相談とプランは使え、お気に入りはログインした人だけが使えることの検証。

ログインしていない人は、画面が Firebase の匿名ログインでゲストの通行証を取る。
ゲストのあいだに組んだプランは、ログインや登録をしたときに本人へ移す。
"""

from __future__ import annotations

from tests.test_ask import FULL


def test_guest_can_fill_the_conditions_and_get_a_plan(guest):
    session = guest.post("/api/auth/session").json()
    assert session["guest"] is True

    body = guest.patch("/api/chat/slots", json=FULL).json()
    assert body["is_complete"] is True
    exp_id = body["exp_id"]
    assert guest.get(f"/api/expeditions/{exp_id}").status_code == 200
    assert [e["exp_id"] for e in guest.get("/api/me/expeditions").json()["expeditions"]] == [exp_id]


def test_signed_in_session_is_not_a_guest(user):
    assert user.post("/api/auth/session").json()["guest"] is False


def test_favorites_are_for_signed_in_people_only(guest):
    exp_id = guest.patch("/api/chat/slots", json=FULL).json()["exp_id"]

    for res in (
        guest.get("/api/me/favorites"),
        guest.post("/api/me/favorites", json={"exp_id": exp_id, "kind": "makeup"}),
        guest.delete("/api/me/favorites/fav_x"),
    ):
        assert res.status_code == 403
        # 画面は reason を見て、登録とログインの案内に切り替える
        assert res.json()["detail"]["reason"] == "guest"


def test_signing_in_carries_the_guest_plan_over_and_it_can_be_saved(guest, login):
    exp_id = guest.patch("/api/chat/slots", json=FULL).json()["exp_id"]
    member = login("登録したての人")

    res = member.post("/api/auth/adopt", json={"guest_token": guest.token})
    assert res.json() == {"adopted": True}

    chat = member.get("/api/chat").json()
    assert chat["exp_id"] == exp_id
    assert chat["slots"]["character"] == "キャラB"
    assert member.post("/api/me/favorites", json={"exp_id": exp_id, "kind": "makeup"}).status_code == 201

    # ゲスト側には何も残らない。移したプランも、もうゲストのものではない
    left = guest.get("/api/chat").json()
    assert left["exp_id"] is None and left["slots"]["character"] is None
    assert guest.get(f"/api/expeditions/{exp_id}").status_code == 403


def test_empty_guest_does_not_wipe_the_members_conditions(guest, user):
    user.patch("/api/chat/slots", json=FULL)
    guest.get("/api/chat")  # 開いただけで何も入れていない

    assert user.post("/api/auth/adopt", json={"guest_token": guest.token}).json() == {"adopted": False}
    assert user.get("/api/chat").json()["is_complete"] is True


def test_guest_draft_does_not_replace_a_finished_plan(guest, user):
    finished = user.patch("/api/chat/slots", json=FULL).json()["exp_id"]
    guest.patch("/api/chat/slots", json={"origin_station": "新宿"})  # 組み上がっていない

    assert user.post("/api/auth/adopt", json={"guest_token": guest.token}).json() == {"adopted": False}
    assert user.get("/api/chat").json()["exp_id"] == finished


def test_only_a_guest_token_can_be_adopted(user, login):
    """ログインした他人のトークンを渡して、その人の条件を吸い上げることはできない。"""
    other = login("別の人")
    other.patch("/api/chat/slots", json=FULL)

    assert user.post("/api/auth/adopt", json={"guest_token": other.token}).status_code == 400
    assert user.post("/api/auth/adopt", json={"guest_token": "garbage"}).status_code == 400
    assert user.get("/api/chat").json()["exp_id"] is None
    assert other.get("/api/chat").json()["is_complete"] is True


def test_guest_cannot_adopt(guest, login):
    other_guest = login("もう1人の通りすがり", anonymous=True)
    other_guest.patch("/api/chat/slots", json=FULL)
    assert guest.post("/api/auth/adopt", json={"guest_token": other_guest.token}).status_code == 403
