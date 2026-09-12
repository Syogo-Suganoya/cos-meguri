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
    Lang,
    LuggageMode,
    MemberProgress,
)


# ---------------------------------------------------------------- レイヤー


class DevLoginRequest(BaseModel):
    """開発用ログイン（パスワード検証なし）。本番では Firebase 側でトークンを得る。"""

    handle: str = Field(min_length=1, max_length=40)


class SessionRequest(BaseModel):
    """ログイン直後にコス名アカウントを引き当てる／作る。"""

    handle: str | None = Field(default=None, max_length=40)


class LayerUpdate(BaseModel):
    handle: str | None = Field(default=None, min_length=1, max_length=40)
    lang: Lang | None = None
    luggage_mode: LuggageMode | None = None
    home_event: str | None = None


# ---------------------------------------------------------------- 遠征


class ExpeditionCreate(BaseModel):
    event_id: str
    day: datetime
    character: CharacterRef
    origin_station: str
    luggage_mode: LuggageMode | None = None
    lang: Lang | None = None
    attendance_factor: float = Field(1.0, gt=0.0, le=3.0)


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
    dressing: dict | None = None
    extras: dict = Field(default_factory=dict)


# ---------------------------------------------------------------- 合わせ


class AwaseMemberIn(BaseModel):
    """招待はコス名で行う。相手がまだログインしていなくても招待できる。"""

    handle: str = Field(min_length=1, max_length=40)
    lang: Lang = Lang.JA


class AwaseCreate(BaseModel):
    title: str
    event_id: str
    day: datetime
    # 作成者が主催者になる。ここに書くのは招待する相手だけ
    members: list[AwaseMemberIn] = Field(default_factory=list)


class ShootCreate(BaseModel):
    starts_at: datetime
    minutes: int = 30
    place: str = ""
    photographer: str | None = None
    member_ids: list[str] = Field(default_factory=list)


class ProgressUpdate(BaseModel):
    progress: MemberProgress
    eta: datetime | None = None
    share_location: bool = False
    # 主催者が代理で入れる場合のみ。省略時は自分の進捗
    layer_id: str | None = None


class DecisionIn(BaseModel):
    approved: bool


# ---------------------------------------------------------------- チャット


class ChatSlotsIn(BaseModel):
    """条件の直接指定。画面の入力欄から来る。空文字は「消す」。"""

    event_id: str | None = None
    day: datetime | None = None
    title: str | None = Field(default=None, max_length=60)
    character: str | None = Field(default=None, max_length=60)
    origin_station: str | None = Field(default=None, max_length=40)
    luggage_mode: LuggageMode | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


# ---------------------------------------------------------------- 通知


class MarkReadRequest(BaseModel):
    notification_ids: list[str] = Field(default_factory=list)
