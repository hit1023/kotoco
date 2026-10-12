# kotoco API リファレンス

ベースURL: `http://localhost:8896`（WebUI 経由なら `http://localhost:8895/api`）

対話的なドキュメントは起動後に以下で見られます。

- Swagger UI: `/docs`
- ReDoc: `/redoc`
- OpenAPI JSON: `/openapi.json`

認証はありません（LAN 内利用を想定）。公開する場合はリバースプロキシ側で制限してください。

## GET /health

死活確認。`{"status": "ok"}` を返します。

## GET /voices

言語コードごとのボイス一覧。

```json
{
  "j": ["jf_alpha", "jf_gongitsune", "jf_nezumi", "jf_tebukuro", "jm_kumo"],
  "a": ["af_heart", "af_bella", "af_nicole", "am_adam", "am_michael"]
}
```

## POST /tts

テキストを音声に変換し、`audio/wav`（24kHz / モノラル）をそのまま返します。

リクエスト (JSON)

| フィールド | 型 | 既定値 | 説明 |
|---|---|---|---|
| text | string | (必須) | 読み上げるテキスト。長文は内部で分割して合成 |
| lang | string | `j` | `j`=日本語, `a`=英語(米) |
| voice | string | `jf_alpha` | `/voices` にあるボイス名 |
| speed | number | `1.0` | 0.5〜2.0 |

```bash
curl -X POST http://localhost:8896/tts \
  -H 'Content-Type: application/json' \
  -d '{"text":"こんにちは。","lang":"j","voice":"jf_alpha","speed":1.0}' \
  -o out.wav
```

```python
import requests
r = requests.post("http://localhost:8896/tts",
                  json={"text": "こんにちは。", "voice": "jf_alpha"})
open("out.wav", "wb").write(r.content)
```

エラー

| ステータス | 内容 |
|---|---|
| 400 | text が空、または未対応の lang |
| 422 | パラメータの型/範囲エラー (speed 範囲外など) |
| 500 | 音声が生成されなかった |

## 注意

- 初回リクエストはモデル(約330MB)のダウンロードと読み込みで十数秒かかります。以降は `./cache` に残るため速くなります。
- 合成は排他制御しており、同時リクエストは順番に処理されます。
