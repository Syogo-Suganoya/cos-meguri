# README に載せる画面操作イメージを撮るためだけのコンテナ。
# 起動中の api にブラウザで繋ぎ、利用者と同じ順に操作して撮る。
FROM zenika/alpine-chrome:with-puppeteer

USER root
# 日本語のフォントが無いと全部豆腐になる
RUN apk add --no-cache font-noto-cjk
