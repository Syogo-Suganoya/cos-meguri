"""生成メディアのポート（設計書 §11 GMI Cloud 活用）。

画像・動画・音声で提供元は同じ（GMI Cloud）だが、責務が違うので3つに分ける。
呼び出し側が「完成イメージだけ欲しい」ときに動画の実装を気にしなくて済む。

どの実装も次を守る:
- バイト列を返さず MediaAsset（参照と失効時刻）を返す
- 生成物には AI 生成の表示を入れる（watermarked=True）
- 失敗時は例外を上へ投げず None を返す。生成物は「あれば嬉しい」ものであって、
  遠征プランの成立条件ではない
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.models import Lang, MediaAsset


class ImagePort(ABC):
    """完成イメージ（ウィッグ×衣装×メイクの全部盛り予想図）。"""

    name: str = "image"

    @abstractmethod
    async def generate_look(self, prompt: str, *, lang: Lang = Lang.JA) -> MediaAsset | None:
        """プロンプトから1枚生成する。失敗時は None。"""


class VideoPort(ABC):
    """アフタームービー（合わせの撮影写真からのPV）。"""

    name: str = "video"

    @abstractmethod
    async def generate_after_movie(
        self,
        *,
        image_urls: list[str],
        prompt: str,
        seconds: int = 5,
        lang: Lang = Lang.JA,
    ) -> MediaAsset | None:
        """写真から短い動画を作る。失敗時は None。"""


class SpeechPort(ABC):
    """音声ガイド（メイク工程・動線の読み上げ）。"""

    name: str = "speech"

    @abstractmethod
    async def synthesize(self, text: str, *, lang: Lang = Lang.JA) -> MediaAsset | None:
        """母語で読み上げる。失敗時は None。

        **ボイスクローンは実装しない。** 参照音声を受け取る引数を持たないことで、
        使えないことを型で示す（設計書 §11）。
        """
