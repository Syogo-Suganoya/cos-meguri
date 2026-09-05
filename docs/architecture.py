"""コスめぐりの技術スタック図を生成する（設計書 §5）。

何がどこで動き、どの外部サービスに繋がるかだけを描く。
エージェント間の流れは README とコードを見れば足りるので、図には入れない。

生成:
    docker compose --profile docs run --rm diagram
出力:
    docs/architecture.png
"""

from __future__ import annotations

from diagrams import Cluster, Diagram, Edge
from diagrams.gcp.compute import Run
from diagrams.gcp.database import Firestore
from diagrams.gcp.devtools import Scheduler
from diagrams.gcp.ml import AIPlatform
from diagrams.gcp.operations import Logging
from diagrams.gcp.storage import Storage
from diagrams.gcp.security import Iam
from diagrams.onprem.client import Client, Users
from diagrams.onprem.network import Internet

FONT = "Noto Sans CJK JP"

GRAPH_ATTR = {
    "fontname": FONT,
    "fontsize": "13",
    "bgcolor": "white",
    "pad": "0.4",
    "splines": "spline",
    "nodesep": "0.6",
    "ranksep": "1.2",
}
NODE_ATTR = {"fontname": FONT, "fontsize": "11"}
EDGE_ATTR = {"fontname": FONT, "fontsize": "10"}


def main() -> None:
    with Diagram(
        "コスめぐり — 技術スタック",
        filename="docs/architecture",
        show=False,
        direction="TB",
        graph_attr=GRAPH_ATTR,
        node_attr=NODE_ATTR,
        edge_attr=EDGE_ATTR,
    ):
        users = Users("レイヤー\n（コス名のみ）")
        pwa = Client("PWA（自作UI）\n案内トップ＋機能5ページ\n相談チャットは全ページ常駐")

        with Cluster("Cloud Run（Docker / python:3.12-slim）", graph_attr={"fontname": FONT}):
            app = Run("FastAPI + Pydantic\nOrchestrator と7エージェント")

        with Cluster("外部API", graph_attr={"fontname": FONT}):
            gemini = AIPlatform("Gemini API\ngemini-3.7-flash")
            youcam = Internet("YouCam API\nVTO / 肌タイプ / 顔属性")
            ekispert = Internet("駅すぱあと\nMCPサーバー")
            gmi = Internet("GMI Cloud\n完成イメージ / PV / 音声")

        with Cluster("GCP", graph_attr={"fontname": FONT}):
            auth = Iam("Firebase Authentication\nIDトークン")
            firestore = Firestore("Firestore\n通知・チャットも同居")
            storage = Storage("Cloud Storage\n一時画像")
            logging = Logging("Cloud Logging\n監査ログ")
            scheduler = Scheduler("Cloud Scheduler\n当日監視 / TTL削除")

        users >> pwa >> Edge(label="REST + IDトークン") >> app
        pwa >> Edge(label="ログイン", style="dashed") >> auth
        app >> Edge(label="検証", style="dashed") >> auth
        app >> [gemini, youcam, ekispert, gmi]
        app >> [firestore, storage, logging]
        scheduler >> Edge(color="firebrick", style="bold") >> app


if __name__ == "__main__":
    main()
    print("wrote docs/architecture.png")
