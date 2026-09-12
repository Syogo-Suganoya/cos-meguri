"""Cloud Run のエントリポイント（設計書 §4 API Gateway）。

同一イメージをローカル・CI・本番で使う。フロント（PWA）は web/ を
静的配信し、MVP のうちは API と同居させる。
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.adapters.registry import get_adapters
from app.api.routes import router
from app.config import get_settings

logging.basicConfig(level=logging.INFO)

# httpx は送信先の URL を INFO で丸ごと出す。駅すぱあとの REST のように
# APIキーをクエリでしか受けない相手がいるので、そのままだとキーが平文で
# ログに残る（Cloud Logging にも流れる）。この1行が唯一の防波堤なので外さない。
logging.getLogger("httpx").setLevel(logging.WARNING)

settings = get_settings()
app = FastAPI(
    title="コスめぐり API",
    description="レイヤーの一日エージェント",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_env == "local" else [],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/healthz")
async def healthz() -> dict:
    """稼働確認。設定の取り違えを目視ではなく応答で分かるようにする。

    live のつもりが mock に落ちている・開発用ログインのまま、といった状態は
    起動ログを読まないと気づけない。warnings に出して確認を1回で済ませる。
    """
    providers = get_adapters().describe()
    warnings: list[str] = []

    if providers["auth"] == "auth:dev":
        warnings.append(
            "開発用ログイン（パスワード検証なし）で動いています。本番では AUTH_MODE=firebase を設定してください"
        )
    # providers のキーは環境変数と同じ名前にしてある。警告を読んだ人が
    # どの変数を直せばよいか、対応表を引かずに分かるようにするため
    for name, mode in (
        ("ekispert", settings.ekispert_mode),
        ("gemini", settings.gemini_mode),
    ):
        # live 指定なのに mock/stub 実装が入っている = キーが無くて降格した
        degraded = providers[name].endswith((":mock", ":stub"))
        if mode == "live" and degraded:
            warnings.append(
                f"{name.upper()}_MODE=live ですが、キーが無いため mock で動いています"
            )

    return {
        "status": "ok",
        "env": settings.app_env,
        "providers": providers,
        "warnings": warnings,
    }


# ETag は返っているので、no-cache を足せば「変わっていなければ 304」で済む。
# 付けないとブラウザが独自の判断で握り込み、デプロイしても古いまま出る。
NO_CACHE = {"Cache-Control": "no-cache"}


def _page(path: Path, media_type: str | None = None) -> FileResponse:
    """ページ・マニフェスト・SW を返す。**必ず再確認させる。**

    HTML に no-cache が無いと、`?v=` を上げても意味がない（新しい HTML を
    読みに行かないので、古い HTML が古いままのアセットを指し続ける）。
    """
    return FileResponse(path, media_type=media_type, headers=NO_CACHE)


class RevalidatingStaticFiles(StaticFiles):
    """毎回 ETag で確かめてから使わせる。

    JS モジュールは URL にバージョンを付けられない（import 側にも書く羽目になる）。
    Cache-Control が無いとブラウザが独自の判断で握り込み、デプロイしても
    古いモジュールのまま動く。中身が変わっていなければ 304 で済むので、
    電波の悪い会場でも負担にならない。
    """

    def file_response(self, *args, **kwargs):  # type: ignore[override]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


WEB_DIR = Path(__file__).resolve().parent.parent / "web"
if WEB_DIR.is_dir():
    app.mount("/static", RevalidatingStaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return _page(WEB_DIR / "index.html")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def manifest() -> FileResponse:
        return _page(WEB_DIR / "manifest.webmanifest")

    # ブラウザとiOSはルート直下を見にくる。/static/ に置くと拾われない
    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon() -> FileResponse:
        return FileResponse(WEB_DIR / "favicon.svg", media_type="image/svg+xml")

    @app.get("/apple-touch-icon.png", include_in_schema=False)
    async def apple_touch_icon() -> FileResponse:
        return FileResponse(WEB_DIR / "apple-touch-icon.png", media_type="image/png")

    @app.get("/sw.js", include_in_schema=False)
    async def service_worker() -> FileResponse:
        # PWA の Service Worker はルート直下から配信する必要がある。
        # ここが握り込まれると、古い SW が居座って更新が止まる
        return _page(WEB_DIR / "sw.js", media_type="application/javascript")

    # 機能ごとのページ。catch-all にすると /api や /docs の除外が要るうえ、
    # 打ち間違いが全部200になるので、出すページだけを明示する。
    PAGES = {
        "ask": "ask.html",
        "login": "login.html",
        "prep": "prep.html",
        "plan": "plan.html",
        "day": "day.html",
    }

    @app.get("/{page}", include_in_schema=False)
    async def feature_page(page: str) -> FileResponse:
        filename = PAGES.get(page)
        if filename is None:
            raise HTTPException(status_code=404, detail="not found")
        return _page(WEB_DIR / "pages" / filename)
