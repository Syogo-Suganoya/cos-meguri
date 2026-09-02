"""Cloud Run のエントリポイント（設計書 §4 API Gateway）。

同一イメージをローカル・CI・本番で使う。フロント（PWA）は web/ を
静的配信し、MVP のうちは API と同居させる。
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.adapters.registry import get_adapters
from app.api.routes import router
from app.config import get_settings

logging.basicConfig(level=logging.INFO)

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
    for name, mode in (
        ("vto", settings.vto_mode),
        ("transit", settings.transit_mode),
        ("llm", settings.llm_mode),
    ):
        # live 指定なのに mock/stub 実装が入っている = キーが無くて降格した
        degraded = providers[name].endswith((":mock", ":stub"))
        if mode == "live" and degraded:
            warnings.append(f"{name}: live 指定ですがキーが無いため mock で動いています")
    if not settings.tasks_token and not settings.is_local:
        warnings.append("TASKS_TOKEN が未設定です。バッチ用エンドポイントは閉じています")

    return {
        "status": "ok",
        "env": settings.app_env,
        "providers": providers,
        "warnings": warnings,
    }


WEB_DIR = Path(__file__).resolve().parent.parent / "web"
if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def manifest() -> FileResponse:
        return FileResponse(WEB_DIR / "manifest.webmanifest")

    @app.get("/sw.js", include_in_schema=False)
    async def service_worker() -> FileResponse:
        # PWA の Service Worker はルート直下から配信する必要がある
        return FileResponse(WEB_DIR / "sw.js", media_type="application/javascript")
