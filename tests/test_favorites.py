"""お気に入りの検証。メイクと動線を、それぞれ写しとして保存できるか。"""

from __future__ import annotations

from tests.conftest import DAY


def _plan(session) -> dict:
    res = session.post(
        "/api/expeditions",
        json={
            "event_id": "comiket",
            "day": DAY.isoformat(),
            "character": {"title": "作品A", "name": "キャラB"},
            "origin_station": "横浜",
            "luggage_mode": "heavy",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_makeup_and_each_route_direction_can_be_saved(user):
    exp = _plan(user)
    makeup = user.post("/api/me/favorites", json={"exp_id": exp["exp_id"], "kind": "makeup"})
    outbound = user.post(
        "/api/me/favorites",
        json={"exp_id": exp["exp_id"], "kind": "route", "direction": "outbound"},
    )
    back = user.post(
        "/api/me/favorites",
        json={"exp_id": exp["exp_id"], "kind": "route", "direction": "return"},
    )
    assert makeup.status_code == outbound.status_code == back.status_code == 201

    assert makeup.json()["makeup"]["steps"][0]["area_label"]  # 画面用の見出しつき
    assert outbound.json()["route"]["segments"]
    assert "行き" in outbound.json()["label"] and "帰り" in back.json()["label"]

    listed = user.get("/api/me/favorites").json()["favorites"]
    assert {f["favorite_id"] for f in listed} == {
        makeup.json()["favorite_id"],
        outbound.json()["favorite_id"],
        back.json()["favorite_id"],
    }


def test_saving_the_same_part_twice_keeps_one(user):
    exp = _plan(user)
    body = {"exp_id": exp["exp_id"], "kind": "makeup"}
    first = user.post("/api/me/favorites", json=body)
    second = user.post("/api/me/favorites", json=body)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["favorite_id"] == second.json()["favorite_id"]
    assert len(user.get("/api/me/favorites").json()["favorites"]) == 1


def test_saved_copy_survives_rebuilding_the_plan(user):
    """元の遠征が組み直されても、保存した時点の中身が残る。"""
    exp = _plan(user)
    saved = user.post(
        "/api/me/favorites",
        json={"exp_id": exp["exp_id"], "kind": "route", "direction": "outbound"},
    ).json()
    _plan(user)  # 別の遠征を組む
    kept = user.get("/api/me/favorites").json()["favorites"][0]
    assert kept["route"] == saved["route"]


def test_favorite_titles_name_the_character_for_their_owner(user):
    """並べたときに見分けられるよう、本人のお気に入りの見出しにはキャラ名・作品名を入れる。"""
    exp = _plan(user)
    makeup = user.post("/api/me/favorites", json={"exp_id": exp["exp_id"], "kind": "makeup"}).json()
    route = user.post(
        "/api/me/favorites",
        json={"exp_id": exp["exp_id"], "kind": "route", "direction": "outbound"},
    ).json()
    assert makeup["label"].startswith("キャラB（作品A）のメイク")
    assert "キャラB（作品A）" in route["label"] and "行き" in route["label"]


def test_character_name_still_stays_out_of_the_shared_plan(user, login):
    """設計書 §7-4: 名前が出るのは本人のお気に入りだけ。遠征の応答と、他人の一覧には出ない。"""
    exp = _plan(user)
    assert "キャラB" not in user.get(f"/api/expeditions/{exp['exp_id']}").text
    user.post("/api/me/favorites", json={"exp_id": exp["exp_id"], "kind": "makeup"})
    assert "キャラB" not in login("別の人").get("/api/me/favorites").text


def test_route_needs_a_direction(user):
    exp = _plan(user)
    res = user.post("/api/me/favorites", json={"exp_id": exp["exp_id"], "kind": "route"})
    assert res.status_code == 422


def test_others_cannot_save_read_or_delete_my_favorites(user, login):
    exp = _plan(user)
    mine = user.post("/api/me/favorites", json={"exp_id": exp["exp_id"], "kind": "makeup"}).json()

    stranger = login("別の人")
    # 他人の遠征から写せない（あるかどうかも教えない）
    assert (
        stranger.post("/api/me/favorites", json={"exp_id": exp["exp_id"], "kind": "makeup"}).status_code
        == 404
    )
    assert stranger.get("/api/me/favorites").json()["favorites"] == []
    assert stranger.client.delete(
        f"/api/me/favorites/{mine['favorite_id']}", headers=stranger.headers
    ).status_code == 404
    assert len(user.get("/api/me/favorites").json()["favorites"]) == 1


def test_favorite_can_be_deleted(user):
    exp = _plan(user)
    fav = user.post("/api/me/favorites", json={"exp_id": exp["exp_id"], "kind": "makeup"}).json()
    res = user.client.delete(f"/api/me/favorites/{fav['favorite_id']}", headers=user.headers)
    assert res.status_code == 204
    assert user.get("/api/me/favorites").json()["favorites"] == []


def test_favorites_require_login(client):
    assert client.get("/api/me/favorites").status_code == 401
