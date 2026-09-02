# アーキテクチャ図の生成専用イメージ。
# graphviz と日本語フォント（Noto CJK）が要るので、アプリ本体とは分ける。
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends graphviz fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip && pip install "diagrams>=0.24"

WORKDIR /work

CMD ["python", "docs/architecture.py"]
