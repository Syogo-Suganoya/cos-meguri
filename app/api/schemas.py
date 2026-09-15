"""API の入出力スキーマ。

外向きの応答では、キャラ名・作品名を持つフィールドを既定で出さない
（設計書 §7-4「内部入力に限定」）。必要な画面だけが明示的に取りに行く。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.models import (
    CharacterRef,
    FavoriteKind,
    Lang,
    LuggageMode,
)


# ---------------------------------------------------------------- レイヤー


class DevLoginRequest(BaseModel):
    """テスト用ログイン（パスワード検証なし）。ローカルと本番は Firebase 側でトークンを得る。"""

    user: str = Field(min_length=1, max_length=40)
    anonymous: bool = False  # ゲスト（匿名ログイン）として発行する


class AdoptGuestRequest(BaseModel):
    """ゲストのあいだに組んだ条件とプランを、ログインした本人へ移す。"""

    guest_token: str = Field(min_length=1, max_length=4096)


class LayerUpdate(BaseModel):
    lang: Lang | None = None
    luggage_mode: LuggageMode | None = None
    home_event: str | None = None


# ---------------------------------------------------------------- 遠征


HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"
HHMM_OR_EMPTY = r"^(|([01]\d|2[0-3]):[0-5]\d)$"


class ExpeditionCreate(BaseModel):
    """一括生成。収載イベントなら event_id だけでよく、それ以外は名前・目的地・開始・終了を渡す。

    event_id と一緒に渡した目的地・時刻は、マスタより優先する。
    """

    event_id: str | None = None
    event_name: str | None = Field(default=None, max_length=60)
    destination_station: str | None = Field(default=None, max_length=40)
    starts_time: str | None = Field(default=None, pattern=HHMM)
    ends_time: str | None = Field(default=None, pattern=HHMM)
    day: datetime
    character: CharacterRef
    origin_station: str
    luggage_mode: LuggageMode | None = None
    lang: Lang | None = None


class MakeupStepOut(BaseModel):
    order: int
    area: str
    area_label: str
    instruction: str
    minutes: int
    personalized_for: list[str]


class ExpeditionOut(BaseModel):
    exp_id: str
    layer_id: str
    status: str
    lang: Lang
    event: dict
    luggage_mode: str
    makeup: dict | None = None
    routes: dict = Field(default_factory=dict)
    extras: dict = Field(default_factory=dict)


# ---------------------------------------------------------------- お気に入り


class FavoriteCreate(BaseModel):
    """どのプランのどの部分を保存するか。中身はサーバが本人の遠征から写す。"""

    exp_id: str
    kind: FavoriteKind
    direction: Literal["outbound", "return"] | None = None


# ---------------------------------------------------------------- チャット


class ChatSlotsIn(BaseModel):
    """条件の直接指定。画面の入力欄から来る。空文字は「消す」。"""

    event_id: str | None = None
    # 画面の欄は自由入力。収載イベントに当たれば event_id を入れ、目的地と時刻も埋める
    event_name: str | None = Field(default=None, max_length=60)
    day: datetime | None = None
    destination_station: str | None = Field(default=None, max_length=40)
    # 空文字は「消す」。それ以外は HH:MM
    starts_time: str | None = Field(default=None, pattern=HHMM_OR_EMPTY)
    ends_time: str | None = Field(default=None, pattern=HHMM_OR_EMPTY)
    title: str | None = Field(default=None, max_length=60)
    character: str | None = Field(default=None, max_length=60)
    origin_station: str | None = Field(default=None, max_length=40)
    luggage_mode: LuggageMode | None = None
