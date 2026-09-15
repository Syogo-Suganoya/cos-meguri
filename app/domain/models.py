"""コスめぐりのドメインモデル（設計書 §6 データモデルに対応）。

個人情報の扱いは §7 に従う:
- アカウントは認証基盤の uid だけで成立し、名前も本名も素顔も持たない
- **顔画像は受け取らない**（解析する相手を持たないので、入口ごと作らない）
- **位置は受け取らない**（合わせの機能ごと外したので、共有する相手がいない）
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# 収載イベントはいずれも日本開催。開場・閉場時刻は JST で解釈する。
# 訪日レイヤーが自国のタイムゾーンから予定を入れても、会場の時刻がずれない。
JST = timezone(timedelta(hours=9))


def event_day(day: datetime) -> datetime:
    """指定日を JST の 0 時に正規化する。開場時刻の組み立て起点。"""
    aware = day if day.tzinfo else day.replace(tzinfo=JST)
    return aware.astimezone(JST).replace(hour=0, minute=0, second=0, microsecond=0)


def jst_hm(value: datetime) -> str:
    """会場時刻（JST）の HH:MM。

    利用者に見せる時刻は必ずこれを通す。クライアントから UTC で届いた
    時刻をそのまま書式化すると、9時間ずれた文面になるため。
    """
    aware = value if value.tzinfo else value.replace(tzinfo=JST)
    return aware.astimezone(JST).strftime("%H:%M")


# ---------------------------------------------------------------- 言語


class Lang(str, Enum):
    """MVPは日英。中韓は i18n 辞書の追加だけで有効化できる（設計書 §9）。"""

    JA = "ja"
    EN = "en"
    ZH = "zh"
    KO = "ko"

    @property
    def label(self) -> str:
        return {
            Lang.JA: "日本語",
            Lang.EN: "English",
            Lang.ZH: "中文",
            Lang.KO: "한국어",
        }[self]


# ---------------------------------------------------------------- レイヤー


class LuggageMode(str, Enum):
    """大荷物の度合い。動線エージェントの制約パラメータ（設計書 §9 W1）。"""

    LIGHT = "light"  # 手荷物のみ
    CARRY = "carry"  # キャリー1個
    HEAVY = "heavy"  # キャリー＋ウィッグケース＋大道具

    @property
    def label(self) -> str:
        return {
            LuggageMode.LIGHT: "手荷物のみ",
            LuggageMode.CARRY: "キャリー1個",
            LuggageMode.HEAVY: "キャリー＋ウィッグ＋大道具",
        }[self]

    @property
    def transfer_penalty_minutes(self) -> int:
        return {LuggageMode.LIGHT: 0, LuggageMode.CARRY: 4, LuggageMode.HEAVY: 8}[self]


class LayerPrefs(BaseModel):
    luggage_mode: LuggageMode = LuggageMode.CARRY
    home_event: str | None = None


class Layer(BaseModel):
    """layers/{layerId} — 名前を持たないアカウント（設計書 §7-1）。

    auth_uid は認証基盤（Firebase Authentication / テスト用ログイン）が払い出す
    識別子。ここに入るのは不透明なIDだけで、メールアドレスは保持しない。
    """

    layer_id: str
    lang: Lang = Lang.JA
    prefs: LayerPrefs = Field(default_factory=LayerPrefs)
    auth_uid: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------- イベント


class EventMaster(BaseModel):
    """初期収載イベント（設計書 §3「対応イベント」）。"""

    event_id: str
    name: str
    name_en: str
    venue: str
    station: str
    scale: Literal["mega", "large", "medium"]
    style: Literal["hall", "street"]  # hall=会場完結 / street=市街地回遊
    opens_at_hour: int = 9
    closes_at_hour: int = 17
    notes_ja: str = ""
    notes_en: str = ""


# 収載イベントに当たらないイベント（ローカルイベントなど）の event_id
CUSTOM_EVENT_ID = "custom"


class EventRef(BaseModel):
    """expeditions/{expId}.event — 行き先と当日の日時。

    収載イベントならマスタの値、それ以外（CUSTOM_EVENT_ID）は相談の欄に書かれた値で埋まる。
    """

    event_id: str
    name: str
    venue: str
    station: str = ""  # 目的地（最寄り駅）。古い保存データには無い
    starts_at: datetime
    ends_at: datetime

    @property
    def date_key(self) -> str:
        """開催日（JST）の YYYY-MM-DD。日付で引くときのキー。"""
        return self.starts_at.astimezone(JST).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- メイク工程


class MakeupArea(str, Enum):
    BASE = "base"
    BROW = "brow"
    EYESHADOW = "eyeshadow"
    EYELINE = "eyeline"
    LENS = "lens"
    CONTOUR = "contour"
    HIGHLIGHT = "highlight"
    LIP = "lip"
    WIG_LINE = "wig_line"

    @property
    def label_ja(self) -> str:
        return {
            MakeupArea.BASE: "ベース",
            MakeupArea.BROW: "眉",
            MakeupArea.EYESHADOW: "アイシャドウ",
            MakeupArea.EYELINE: "アイライン",
            MakeupArea.LENS: "カラコン",
            MakeupArea.CONTOUR: "シェーディング",
            MakeupArea.HIGHLIGHT: "ハイライト",
            MakeupArea.LIP: "リップ",
            MakeupArea.WIG_LINE: "ウィッグ際",
        }[self]

    @property
    def label_en(self) -> str:
        return {
            MakeupArea.BASE: "Base",
            MakeupArea.BROW: "Brows",
            MakeupArea.EYESHADOW: "Eyeshadow",
            MakeupArea.EYELINE: "Eyeliner",
            MakeupArea.LENS: "Contact lenses",
            MakeupArea.CONTOUR: "Contour",
            MakeupArea.HIGHLIGHT: "Highlight",
            MakeupArea.LIP: "Lips",
            MakeupArea.WIG_LINE: "Wig line",
        }[self]


class MakeupStep(BaseModel):
    """expeditions/{expId}.makeup_steps[] — キャラの色味・造形から組んだ1工程。"""

    order: int
    area: MakeupArea
    instruction: str
    lang: Lang = Lang.JA
    minutes: int = 3
    personalized_for: list[str] = Field(default_factory=list)  # 個別化の根拠
    done: bool = False


class MakeupPlan(BaseModel):
    steps: list[MakeupStep] = Field(default_factory=list)
    lang: Lang = Lang.JA
    total_minutes: int = 0
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- 動線


class RouteSegment(BaseModel):
    """1区間。

    駅設備（エレベータ・階段）は駅すぱあと API に無いので持たない。大荷物の
    しんどさは「乗換の回数」で測る（乗換のたびに体感時間を足す）。
    """

    from_station: str
    to_station: str
    line: str
    minutes: int
    fare_yen: int = 0
    # 駅すぱあとで引けず、静的グラフの目安に落ちた区間。駅名の打ち間違いを本物の経路に見せないための印
    estimated: bool = False


class RoutePlan(BaseModel):
    """expeditions/{expId}.route.{行き|帰り} — 大荷物モードで再評価済み。"""

    direction: Literal["outbound", "return"]
    segments: list[RouteSegment] = Field(default_factory=list)
    luggage_mode: LuggageMode = LuggageMode.CARRY
    depart_at: datetime | None = None
    arrive_at: datetime | None = None
    base_minutes: int = 0
    effective_minutes: int = 0  # 大荷物ペナルティ込み
    fare_yen: int = 0
    transfers: int = 0
    warnings: list[str] = Field(default_factory=list)

    @property
    def penalty_minutes(self) -> int:
        return self.effective_minutes - self.base_minutes


# ---------------------------------------------------------------- 遠征


class ExpeditionStatus(str, Enum):
    DRAFT = "draft"
    PLANNED = "planned"
    # 当日モードを外したので、いまは誰も書かない。保存済みの値を読めるように残す
    DAY_OF = "day_of"
    DONE = "done"


class CharacterRef(BaseModel):
    """expeditions/{expId}.character — メイク工程生成にのみ使用（設計書 §7-4）。"""

    title: str  # 作品名
    name: str  # キャラ名
    hair_color: str | None = None
    eye_color: str | None = None
    features: list[str] = Field(default_factory=list)


class Expedition(BaseModel):
    """expeditions/{expId} の集約ルート。"""

    exp_id: str
    layer_id: str
    status: ExpeditionStatus = ExpeditionStatus.DRAFT
    lang: Lang = Lang.JA
    event: EventRef
    # 開催日（JST）の YYYY-MM-DD。日付で引くための冗長フィールド。
    # 入れ子フィールドの範囲検索を避け、Firestore 側を等値1本で済ませる。
    event_date: str = ""
    character: CharacterRef
    luggage_mode: LuggageMode = LuggageMode.CARRY
    origin_station: str = ""
    makeup: MakeupPlan | None = None
    routes: dict[str, RoutePlan] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------- お気に入り


class FavoriteKind(str, Enum):
    MAKEUP = "makeup"
    ROUTE = "route"


class Favorite(BaseModel):
    """favorites/{favoriteId} — 気に入ったメイク工程・動線の写し。

    元の遠征（exp_id）を指すだけにすると、条件を直して組み直した瞬間に中身が変わる。
    保存した時点のものを残したいので、工程・経路をそのまま写して持つ。
    写しはサーバが本人の遠征から作る。クライアントから届いた中身は保存しない。

    見出しにはキャラ名・作品名を入れる。お気に入りは本人にしか返さないため（設計書 §7-4）。
    """

    favorite_id: str
    layer_id: str
    kind: FavoriteKind
    label: str
    exp_id: str
    # 動線のときだけ。行き（outbound）か帰り（return）か
    direction: Literal["outbound", "return"] | None = None
    event: EventRef
    lang: Lang = Lang.JA
    makeup: MakeupPlan | None = None
    route: RoutePlan | None = None
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------- チャット


class ChatSlots(BaseModel):
    """遠征プランを組むために埋める必要のある項目。

    「相談」ページの欄がそのままこの型になる。イベントは名前・目的地（最寄り駅）・
    開始・終了で表す。収載イベントの名前なら、目的地と時刻はマスタで埋まる（書き換えてよい）。
    ローカルイベントのように収載に無いイベントも、3つを自分で埋めれば組める。
    """

    event_name: str | None = None
    event_id: str | None = None  # 収載イベントに当たったときだけ入る
    day: datetime | None = None
    destination_station: str | None = None
    starts_time: str | None = None  # "HH:MM"（JST）
    ends_time: str | None = None
    title: str | None = None  # 作品名
    character: str | None = None  # キャラ名
    origin_station: str | None = None
    luggage_mode: LuggageMode | None = None

    REQUIRED: ClassVar[tuple[str, ...]] = (
        "event_name",
        "day",
        "destination_station",
        "starts_time",
        "ends_time",
        "title",
        "character",
        "origin_station",
        "luggage_mode",
    )

    @model_validator(mode="before")
    @classmethod
    def _fill_from_legacy_event_id(cls, data):
        """イベントを event_id だけで持っていた頃の保存データを読み戻す。

        名前・目的地・時刻をマスタで補わないと、組み上がっていた条件が「足りない」に戻る。
        """
        if not isinstance(data, dict) or not data.get("event_id") or data.get("event_name"):
            return data
        from app.domain.events import event_defaults, get_event  # events が models を読むので、ここで引く

        event = get_event(data["event_id"])
        if event is None:
            return data
        filled = {k: data.get(k) or v for k, v in event_defaults(event).items()}
        return {**data, **filled, "event_name": event.name}

    def missing(self) -> list[str]:
        return [name for name in self.REQUIRED if getattr(self, name) is None]

    @property
    def is_complete(self) -> bool:
        return not self.missing()


class ChatSession(BaseModel):
    """chats/{layerId} — 1レイヤーにつき1組の条件。

    自由文の会話は取り下げた（条件は画面の欄から直接入れる）。以前のドキュメントに
    残っている `messages` は読み込み時に無視される。
    """

    layer_id: str
    lang: Lang = Lang.JA
    slots: ChatSlots = Field(default_factory=ChatSlots)
    exp_id: str | None = None  # 組み上がった遠征
    updated_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------- 監査


class AuditAction(str, Enum):
    # いま書くのは ACCOUNT_LINKED だけ。ほかは取り下げた機能のぶんで、
    # 過去に保存した記録を読み戻せるように値だけ残す（Firestore に文字列で入っている）
    ACCOUNT_LINKED = "account_linked"  # 認証IDとコス名アカウントの紐付け
    # 顔解析と試着
    FACE_IMAGE_DISCARDED = "face_image_discarded"
    FITTING_IMAGE_DISCARDED = "fitting_image_discarded"
    # 合わせ（位置共有・時間変更の承認）と定期実行
    LOCATION_SHARE_ENABLED = "location_share_enabled"
    LOCATION_SHARE_PURGED = "location_share_purged"
    RESCHEDULE_PROPOSED = "reschedule_proposed"
    RESCHEDULE_APPROVED = "reschedule_approved"
    RESCHEDULE_REJECTED = "reschedule_rejected"
    PROGRESS_UPDATED_BY_ORGANIZER = "progress_updated_by_organizer"
    # 試着と画像生成
    IP_GUARD_BLOCKED = "ip_guard_blocked"
    EXPEDITION_PURGED = "expedition_purged"
    # 生成メディアを取り下げたので、いまは誰も書かない（設計書 §11）。理由は上と同じ
    MEDIA_GENERATED = "media_generated"
    VOICE_CLONE_BLOCKED = "voice_clone_blocked"


class AuditLog(BaseModel):
    """audit/{logId} — 自分のデータがどう扱われたかの記録（設計書 §7）。"""

    log_id: str
    actor: str
    action: AuditAction
    subject_id: str | None = None
    # この記録が「誰のこと」か。actor や subject_id が本人以外を指す記録も
    # 読み戻すことがあるので、持ち主だけは独立して持つ。一覧を本人ぶんに絞るのに使う。
    layer_ids: list[str] = Field(default_factory=list)
    payload: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
