"""チャット欄の検証。自由文からプランが立ち上がるまでを見る。"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.domain.models import JST, LuggageMode
from app.domain.parsing import extract_slots
from tests.conftest import DAY

EVENTS = [
    {"event_id": "comiket", "name": "コミックマーケット", "name_en": "Comic Market"},
    {"event_id": "acosta", "name": "acosta!", "name_en": "acosta!"},
]
NOW = datetime(2026, 8, 1, tzinfo=JST)


# ---------------------------------------------------------------- 抽出


def test_extracts_event_date_station_and_luggage_from_one_sentence():
    slots = extract_slots(
        "9/6のコミケに横浜駅から行きます。キャリー1個です", EVENTS, now=NOW
    )
    assert slots["event_id"] == "comiket"
    assert slots["day"].startswith("2026-09-06")
    assert slots["origin_station"] == "横浜"
    assert slots["luggage_mode"] == LuggageMode.CARRY.value


def test_partial_date_rolls_over_to_next_year():
    """1月の予定を8月に相談したら、来年の1月と解釈する。"""
    slots = extract_slots("1/10のacostaに行きたい", EVENTS, now=NOW)
    assert slots["day"].startswith("2027-01-10")


def test_heavy_luggage_wording_is_recognised():
    assert extract_slots("大荷物です", EVENTS, now=NOW)["luggage_mode"] == "heavy"
    assert extract_slots("手ぶらで行きます", EVENTS, now=NOW)["luggage_mode"] == "light"


def test_unknown_text_extracts_nothing():
    assert extract_slots("こんにちは", EVENTS, now=NOW) == {}


def test_character_is_read_from_two_phrasings():
    a = extract_slots("作品名は作品A、キャラ名はキャラB", EVENTS, now=NOW)
    assert (a.get("title"), a.get("character")) == ("作品A", "キャラB")

    b = extract_slots("作品Xのキャラクター太郎のコスをします", EVENTS, now=NOW)
    assert b.get("title") and b.get("character")


@pytest.mark.parametrize(
    "text",
    [
        "作品は「星のカケラ」でキャラはリリカです",
        "作品は星のカケラでキャラはリリカ",
        "作品名：星のカケラ キャラ名：リリカ",
        "作品「星のカケラ」キャラ「リリカ」",
        "キャラはリリカ、作品は星のカケラ",
    ],
)
def test_character_drops_particles_and_brackets(text):
    """語尾の「で」「です」や鉤括弧を作品名・キャラ名に混ぜない。

    値まで1本の正規表現で捕まえていた頃は「星のカケラ」で / リリカです になり、
    そのままメイク工程の生成に渡っていた。
    """
    slots = extract_slots(text, EVENTS, now=NOW)
    assert (slots.get("title"), slots.get("character")) == ("星のカケラ", "リリカ")


def test_series_word_inside_a_title_is_not_a_key():
    """「作品X」の「作品」はキーではない。直後に区切りが来たときだけキーとみなす。"""
    slots = extract_slots("作品Xのキャラクター太郎のコスをします", EVENTS, now=NOW)
    assert slots["title"] == "作品X"


def test_title_and_character_can_be_answered_one_at_a_time():
    """会話は1項目ずつ聞き返すので、片方だけの返事も拾える。"""
    assert extract_slots("作品名は星のカケラ", EVENTS, now=NOW) == {"title": "星のカケラ"}
    assert extract_slots("キャラ名はリリカ", EVENTS, now=NOW) == {"character": "リリカ"}


# ---------------------------------------------------------------- 会話


def test_chat_asks_only_for_what_is_missing(user):
    first = user.get("/api/chat").json()
    assert first["messages"][0]["role"] == "agent"
    # プロフィールの荷物設定は最初から埋まっている
    assert "luggage_mode" not in first["missing"]

    res = user.post("/api/chat", json={"message": "9/6のコミケに横浜駅から行きます"}).json()
    assert res["slots"]["event_id"] == "comiket"
    assert res["slots"]["origin_station"] == "横浜"
    assert res["missing"] == ["title", "character"]

    reply = res["messages"][-1]["text"]
    assert "コミックマーケット" in reply  # 把握済みの条件を読み返す
    assert "作品名" in reply  # 次に聞くのは作品名だけ


def test_chat_builds_the_plan_once_every_slot_is_filled(user):
    user.post("/api/chat", json={"message": "9/6のコミケに横浜駅から行きます。大荷物です"})
    res = user.post("/api/chat", json={"message": "作品名は作品A、キャラ名はキャラB"}).json()

    assert res["is_complete"] is True
    assert res["exp_id"]
    assert res["expedition"]["makeup"]["steps"]
    assert res["expedition"]["routes"]["outbound"]["luggage_mode"] == "heavy"

    reply = res["messages"][-1]["text"]
    assert "メイク" in reply and "出発" in reply
    # 設計書 §7-4: 会話の返答にもキャラ名を残さない前提でプラン要約を作る
    assert "character" not in res["expedition"]


def test_chat_history_survives_and_can_be_reset(user):
    user.post("/api/chat", json={"message": "コミケに行きます"})
    assert len(user.get("/api/chat").json()["messages"]) == 3  # 挨拶＋往復

    reset = user.post("/api/chat/reset", json={}).json()
    assert len(reset["messages"]) == 1
    assert reset["slots"]["event_id"] is None


def test_chat_is_private_to_each_layer(user, login):
    user.post("/api/chat", json={"message": "コミケに行きます"})
    other = login("別の人")
    assert other.get("/api/chat").json()["slots"]["event_id"] is None


def test_english_layer_is_asked_in_english(login):
    visitor = login("Visitor")
    visitor.patch("/api/me", json={"lang": "en"})
    visitor.post("/api/chat/reset", json={})
    res = visitor.post("/api/chat", json={"message": "I'm going to Comic Market"}).json()
    assert res["slots"]["event_id"] == "comiket"
    assert "Which date?" in res["messages"][-1]["text"]


def test_plan_from_chat_matches_the_event_calendar(user):
    user.post(
        "/api/chat",
        json={"message": f"{DAY:%-m/%-d}のacostaに新宿駅から行きます。キャリー1個です"},
    )
    res = user.post("/api/chat", json={"message": "作品名は作品A、キャラ名はキャラB"}).json()
    assert res["expedition"]["event"]["event_id"] == "acosta"
    # acosta! は 10:00 開場（JST）
    starts_at = datetime.fromisoformat(
        res["expedition"]["event"]["starts_at"].replace("Z", "+00:00")
    )
    assert starts_at.astimezone(JST).hour == 10


def test_plan_reply_points_at_the_plan_page(user):
    """案内先はページ名で書く。以前は「右の」と書いていたが、右には何もない。"""
    user.post(
        "/api/chat",
        json={"message": f"{DAY:%-m/%-d}のコミケに横浜駅から行きます。大荷物です"},
    )
    res = user.post(
        "/api/chat", json={"message": "作品は「星のカケラ」でキャラはリリカです"}
    ).json()
    reply = res["messages"][-1]["text"]
    assert "プラン" in reply
    assert "右の" not in reply
    # 括弧も語尾も混ざらずにキャラが渡っている
    assert res["slots"]["title"] == "星のカケラ"
    assert res["slots"]["character"] == "リリカ"


def test_english_plan_reply_also_points_somewhere(login):
    """英語側には案内文が1つも無かった。"""
    visitor = login("Visitor")
    visitor.patch("/api/me", json={"lang": "en"})
    visitor.post("/api/chat/reset", json={})
    visitor.post(
        "/api/chat",
        json={"message": f"Comic Market on {DAY:%-m/%-d}, 横浜駅から, one suitcase"},
    )
    res = visitor.post(
        "/api/chat", json={"message": "Series: Series A, Character: Char B"}
    ).json()
    assert res["slots"]["title"] == "Series A"
    assert "Plan page" in res["messages"][-1]["text"]
