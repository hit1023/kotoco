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

テキストを音声に変換し、`audio/wav` または `audio/mpeg`（24kHz / モノラル）をそのまま返します。

リクエスト (JSON)

| フィールド | 型 | 既定値 | 説明 |
|---|---|---|---|
| text | string | (必須) | 読み上げるテキスト。長文は内部で分割して合成 |
| lang | string | `j` | `j`=日本語, `a`=英語(米) |
| voice | string | `jf_alpha` | `/voices` にあるボイス名 |
| speed | number | `1.0` | 0.5〜2.0 |
| format | string | `wav` | `wav` または `mp3` |
| use_replacements | boolean | `true` | 置換ルールを適用する |
| record_history | boolean | `true` | 履歴に記録する |

```bash
curl -X POST http://localhost:8896/tts \
  -H 'Content-Type: application/json' \
  -d '{"text":"こんにちは。","lang":"j","voice":"jf_alpha","speed":1.0}' \
  -o out.wav
```

```bash
# MP3 で受け取る
curl -X POST http://localhost:8896/tts \
  -H 'Content-Type: application/json' \
  -d '{"text":"こんにちは。","format":"mp3"}' -o out.mp3
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
| 400 | text が空、未対応の lang、未対応の format |
| 422 | パラメータの型/範囲エラー (speed 範囲外など) |
| 500 | 音声が生成されなかった |

レスポンスヘッダー: `X-Generation-Ms`(生成時間ms)、`X-Applied-Text`(置換後テキスト, URLエンコード)

## 置換ルール

合成前にテキストへ適用される置換辞書。大文字小文字は区別せず、長い語が優先、置換結果は再置換されません。SQLite(`./data/kotoco.db`)に保存されます。

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/replacements` | 一覧 `[{"src","dst"}]` |
| POST | `/replacements` | 追加/更新 `{"src":"kotoko","dst":"ことこ"}` (src が同じなら上書き) |
| DELETE | `/replacements?src=kotoko` | 削除 (なければ 404) |
| GET | `/replacements/export` | `src@dst` 形式のテキスト |
| POST | `/replacements/import` | `src@dst` 形式(1行1件, `#`始まりはコメント)をボディに送って一括登録 |

```bash
curl -X POST http://localhost:8896/replacements -H 'Content-Type: application/json' -d '{"src":"kotoko","dst":"ことこ"}'
printf 'kotoco@ことこ\n' | curl -X POST http://localhost:8896/replacements/import --data-binary @-
```

## POST /g2p

テキストがどう読まれるか(音素列)を返します。`use_replacements` (既定 true) で置換後の読みを確認できます。

```json
{"input":"kotokoです","applied":"ことこです","phonemes":"ko toko desɨ"}
```

## 履歴

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/history?limit=20&offset=0` | 新しい順。`{"total":N,"items":[...]}` (最大1000件保持) |
| DELETE | `/history` | 全削除 |

## 注意

- 初回リクエストはモデル(約330MB)のダウンロードと読み込みで十数秒かかります。以降は `./cache` に残るため速くなります。
- 合成は排他制御しており、同時リクエストは順番に処理されます。
