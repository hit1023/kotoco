# kotoco

[Kokoro-82M](https://github.com/hexgrad/kokoro) を使った、軽量な日本語対応テキスト読み上げ (TTS) サービス。
Docker で WebUI と API を分けて動かします。

```
kotoco/
├── api/      FastAPI による TTS API (Kokoro, CPU 推論)  docs: api/docs/API.md
├── webui/    nginx + 静的HTML。/api/* を API に中継
└── docker-compose.yml
```

## 使い方

```bash
docker compose up -d --build
```

| 用途 | URL |
|---|---|
| WebUI | http://localhost:8895 |
| API | http://localhost:8896 |
| API ドキュメント (Swagger) | http://localhost:8896/docs |

```bash
curl -X POST http://localhost:8896/tts \
  -H 'Content-Type: application/json' \
  -d '{"text":"こんにちは。","voice":"jf_alpha"}' -o out.wav
```

API の詳細は [api/docs/API.md](api/docs/API.md) を参照。

## メモ

- 推論は CPU です。Docker Desktop for Mac の Linux VM からは Apple Neural Engine / Metal を使えません。
  Mac mini (M4) で約3秒の音声を約1.2秒で生成できます (初回はモデルDLで十数秒)。
- モデルは `./cache` に保存されます (git 管理外)。
- 日本語ボイス: jf_alpha / jf_gongitsune / jf_nezumi / jf_tebukuro / jm_kumo
- ボイスの学習・声のクローンは Kokoro 公式では非対応です。

## CI/CD

- CI: GitHub Actions (`.github/workflows/ci.yml`) が push / PR でイメージをビルドし、`/health` などを確認します。
- CD: h-1 では cron が `scripts/autodeploy.sh` を3分ごとに実行し、`origin/main` に新しいコミットがあれば
  `docker compose up -d --build` で反映します。`/health` が通らなければ直前のコミットへロールバックします。

```
*/3 * * * * flock -n /tmp/kotoco-autodeploy.lock /home/hit/docker/kotoco/scripts/autodeploy.sh >> /home/hit/docker/kotoco/autodeploy.log 2>&1 # kotoco-autodeploy
```

本番: https://kotoko.s-quad.com （h-1、NPM で Basic 認証）
