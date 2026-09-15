# ローカルのログイン先。Firebase Authentication のエミュレータだけを動かす。
#
# 本番と同じ Identity Toolkit の REST（メール＋パスワード）を喋るので、
# ログイン画面もバックエンドの検証も本番と同じコードのまま通る。
# 認証エミュレータは Java を要らない（Firestore のエミュレータは別コンテナ）。
FROM node:22-slim

RUN npm install -g firebase-tools@15.30.1 && npm cache clean --force

WORKDIR /emulator
COPY firebase.json .

EXPOSE 9099
CMD ["firebase", "emulators:start", "--only", "auth", "--project", "cos-meguri-local"]
