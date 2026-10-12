# kotoco

[Kokoro-82M](https://github.com/hexgrad/kokoro) を使った、軽量な日本語対応テキスト読み上げ (TTS) サービス。
Docker で WebUI と API を分けて動かします。
本番は https://kotoko.s-quad.com です（h-1）。

```
kotoco/
├── api/      FastAPI による TTS API (Kokoro, CPU 推論)  docs: api/docs/API.md
├── webui/    nginx + 静的HTML。/api/* を API に中継
└── docker-compose.yml
```

## 機能

- 🎵 音声合成: ボイス/話速/WAV・MP3 選択、波形ビジュアライザー、curl サンプルのリアルタイム表示
- 📝 置換ルール: 合成前の置換辞書 (`kotoko → ことこ`)。`src@dst` 形式の一括インポート/エクスポート
- 🔤 読みチェック: 単語がどう読まれるか(音素列)を確認し、そのまま置換ルールへ登録
- 📜 履歴: 生成履歴の再生・コピー・再入力
- API は Swagger UI (`/api/docs`) と [api/docs/API.md](api/docs/API.md)

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
- モデルは `./cache`、置換ルールと履歴(SQLite)は `./data` に保存されます (どちらも git 管理外)。
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
