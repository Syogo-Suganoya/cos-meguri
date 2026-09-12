"""コスめぐりのドメインモデル（設計書 §6 データモデルに対応）。

個人情報の扱いは §7 に従う:
- レイヤーはコス名（handle）のみで成立し、本名・素顔と紐づけない
- **顔画像は受け取らない**（解析する相手を持たないので、入口ごと作らない）
- 位置共有はイベント当日限定
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


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
    撮影枠などをそのまま書式化すると、9時間ずれた文面になるため。
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
    share_location_default: bool = False


class Layer(BaseModel):
    """layers/{layerId} — コス名のみ。本名・素顔と紐づけない（設計書 §7-1）。

    auth_uid は認証基盤（Firebase Authentication / 開発用ログイン）が払い出す
    識別子。ここに入るのは不透明なIDだけで、メールアドレスは保持しない。
    合わせに招待されただけでまだログインしていない人は auth_uid が None
    （pending）のまま存在する。
    """

    layer_id: str
    handle: str
    lang: Lang = Lang.JA
    prefs: LayerPrefs = Field(default_factory=LayerPrefs)
    auth_uid: str | None = None
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def is_pending(self) -> bool:
        """招待済みだが本人のログイン前。"""
        return self.auth_uid is None


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
    dressing_rooms: int = 1
    dressing_capacity: int = 120  # 同時収容人数（1室あたり）
    opens_at_hour: int = 9
    closes_at_hour: int = 17
    notes_ja: str = ""
    notes_en: str = ""

    @property
    def expected_cosplayers(self) -> int:
        return {"mega": 12000, "large": 3000, "medium": 900}[self.scale]


class EventRef(BaseModel):
    """expeditions/{expId}.event — マスタ参照＋当日の日時。"""

    event_id: str
    name: str
    venue: str
    starts_at: datetime
    ends_at: datetime

    @property
    def date_key(self) -> str:
        """開催日（JST）の YYYY-MM-DD。当日バッチの絞り込みキー。"""
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


class ServiceDisruption(BaseModel):
    line: str
    status: str
    delay_minutes: int
    detail: str


# ---------------------------------------------------------------- 更衣室


class CrowdLevel(str, Enum):
    CALM = "calm"
    BUSY = "busy"
    PEAK = "peak"

    @property
    def label_ja(self) -> str:
        return {CrowdLevel.CALM: "空き", CrowdLevel.BUSY: "混雑", CrowdLevel.PEAK: "ピーク"}[self]


class DressingSlot(BaseModel):
    """30分刻みの更衣室予測。MVPは実データ非連携のモデル値（設計書 §9）。"""

    starts_at: datetime
    predicted_users: int
    capacity: int
    occupancy: float  # 予測利用者 / 収容
    wait_minutes: int
    level: CrowdLevel


class DressingPlan(BaseModel):
    event_id: str
    slots: list[DressingSlot] = Field(default_factory=list)
    recommended_entry: datetime | None = None
    recommended_exit: datetime | None = None
    teardown_alert_at: datetime | None = None
    rationale: str = ""
    is_model_estimate: bool = True  # 実測ではないことを常に明示する


# ---------------------------------------------------------------- 遠征


class ExpeditionStatus(str, Enum):
    DRAFT = "draft"
    PLANNED = "planned"
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
    # 開催日（JST）の YYYY-MM-DD。当日バッチが日付で引くための冗長フィールド。
    # 入れ子フィールドの範囲検索を避け、Firestore 側を等値1本で済ませる。
    event_date: str = ""
    character: CharacterRef
    luggage_mode: LuggageMode = LuggageMode.CARRY
    origin_station: str = ""
    makeup: MakeupPlan | None = None
    routes: dict[str, RoutePlan] = Field(default_factory=dict)
    dressing: DressingPlan | None = None
    awase_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------- 合わせ


class MemberProgress(str, Enum):
    INVITED = "invited"
    ACCEPTED = "accepted"
    PREPARING = "preparing"
    EN_ROUTE = "en_route"
    ARRIVED = "arrived"
    DRESSED = "dressed"

    @property
    def rank(self) -> int:
        return list(MemberProgress).index(self)


class LocationShare(BaseModel):
    """設計書 §7-3: 当日限定フラグ。expires_at を過ぎたら値ごと捨てる。"""

    enabled: bool = False
    eta: datetime | None = None
    expires_at: datetime | None = None

    def is_active(self, now: datetime | None = None) -> bool:
        now = now or utcnow()
        return bool(self.enabled and self.expires_at and now < self.expires_at)

    def redacted(self) -> "LocationShare":
        return LocationShare(enabled=False, eta=None, expires_at=None)


class AwaseMember(BaseModel):
    layer_id: str
    handle: str
    lang: Lang = Lang.JA
    is_organizer: bool = False
    progress: MemberProgress = MemberProgress.INVITED
    location: LocationShare = Field(default_factory=LocationShare)
    exp_id: str | None = None


class Shoot(BaseModel):
    """awase/{awaseId}.shoots[] — 撮影枠。"""

    shoot_id: str
    starts_at: datetime
    minutes: int = 30
    place: str = ""
    photographer: str | None = None
    member_ids: list[str] = Field(default_factory=list)


class RescheduleProposal(BaseModel):
    """設計書 §7-5: 起案までが自律。確定は主催者承認を経る。"""

    proposal_id: str
    awase_id: str
    shoot_id: str
    current_start: datetime
    proposed_start: datetime
    delay_minutes: int
    reason: str
    blocking_members: list[str] = Field(default_factory=list)
    status: Literal["proposed", "approved", "rejected"] = "proposed"
    decided_by: str | None = None
    decided_at: datetime | None = None


class Awase(BaseModel):
    """awase/{awaseId} — 合わせの集約ルート。"""

    awase_id: str
    title: str
    event: EventRef
    members: list[AwaseMember] = Field(default_factory=list)
    shoots: list[Shoot] = Field(default_factory=list)
    proposals: list[RescheduleProposal] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def organizer(self) -> AwaseMember | None:
        for m in self.members:
            if m.is_organizer:
                return m
        return self.members[0] if self.members else None

    def member(self, layer_id: str) -> AwaseMember | None:
        for m in self.members:
            if m.layer_id == layer_id:
                return m
        return None


# ---------------------------------------------------------------- 監査


class NotificationKind(str, Enum):
    """アプリ内お知らせの種別。UI の見せ方と、既読管理の単位になる。"""

    ROUTE_DELAY = "route_delay"  # 遅延で経路を再計算した
    TEARDOWN = "teardown"  # 撤収の目安
    AWASE_INVITE = "awase_invite"  # 合わせへの招待
    RESCHEDULE_REQUEST = "reschedule_request"  # 主催者への承認依頼
    RESCHEDULE_RESULT = "reschedule_result"  # 承認/却下の結果
    INFO = "info"


class Notification(BaseModel):
    """notifications/{notificationId} — アプリ内のお知らせ。

    外部メッセージング（LINE等）は使わず、当日モードの自律通知もここへ積む。
    宛先はコス名アカウント（layerId）で、端末や電話番号は持たない。
    """

    notification_id: str
    layer_id: str
    kind: NotificationKind = NotificationKind.INFO
    message: str
    lang: Lang = Lang.JA
    awase_id: str | None = None
    exp_id: str | None = None
    read: bool = False
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------- チャット


class ChatRole(str, Enum):
    USER = "user"
    AGENT = "agent"


class ChatMessage(BaseModel):
    role: ChatRole
    text: str
    created_at: datetime = Field(default_factory=utcnow)


class ChatSlots(BaseModel):
    """遠征プランを組むために埋める必要のある項目。

    チャットは自由文で受けるが、最終的にこの型に落ちるまで質問を続ける。
    """

    event_id: str | None = None
    day: datetime | None = None
    title: str | None = None  # 作品名
    character: str | None = None  # キャラ名
    origin_station: str | None = None
    luggage_mode: LuggageMode | None = None

    def missing(self) -> list[str]:
        order = ["event_id", "day", "title", "character", "origin_station", "luggage_mode"]
        return [name for name in order if getattr(self, name) is None]

    @property
    def is_complete(self) -> bool:
        return not self.missing()


class ChatSession(BaseModel):
    """chats/{layerId} — 1レイヤーにつき1本の対話。"""

    layer_id: str
    lang: Lang = Lang.JA
    messages: list[ChatMessage] = Field(default_factory=list)
    slots: ChatSlots = Field(default_factory=ChatSlots)
    exp_id: str | None = None  # 組み上がった遠征
    updated_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------- 監査


class AuditAction(str, Enum):
    # 顔解析と試着を取り下げたので、いまは誰も書かない（値だけ残す）
    FACE_IMAGE_DISCARDED = "face_image_discarded"
    FITTING_IMAGE_DISCARDED = "fitting_image_discarded"  # 同上
    LOCATION_SHARE_ENABLED = "location_share_enabled"
    # 定期実行を外したので、いまは誰も書かない。過去に保存した記録を
    # 読み戻せるように値は残す（Firestore に文字列で入っている）
    LOCATION_SHARE_PURGED = "location_share_purged"
    RESCHEDULE_PROPOSED = "reschedule_proposed"
    RESCHEDULE_APPROVED = "reschedule_approved"
    RESCHEDULE_REJECTED = "reschedule_rejected"
    # 試着と画像生成を取り下げたので、いまは誰も書かない（値だけ残す）
    IP_GUARD_BLOCKED = "ip_guard_blocked"
    EXPEDITION_PURGED = "expedition_purged"  # 同上（いまは誰も書かない）
    ACCOUNT_LINKED = "account_linked"  # 認証IDとコス名アカウントの紐付け
    PROGRESS_UPDATED_BY_ORGANIZER = "progress_updated_by_organizer"
    # 生成メディアを取り下げたので、いまは誰も書かない（設計書 §11）。理由は上と同じ
    MEDIA_GENERATED = "media_generated"
    VOICE_CLONE_BLOCKED = "voice_clone_blocked"


class AuditLog(BaseModel):
    """audit/{logId} — 画像破棄・共有期間・リスケ承認の証跡（設計書 §7）。"""

    log_id: str
    actor: str
    action: AuditAction
    subject_id: str | None = None
    # この記録が「誰のこと」か。actor はエージェント名のことがあり
    # （awase-agent など）、subject_id も遠征IDや合わせIDが入るので、持ち主だけは
    # 独立して持つ。記録の一覧を本人ぶんに絞るのに使う。
    layer_ids: list[str] = Field(default_factory=list)
    payload: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
