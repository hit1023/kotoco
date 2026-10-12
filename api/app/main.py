import io
import threading
import time
import urllib.parse

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import store

app = FastAPI(
    title="kotoco API",
    version="0.2.0",
    description="Kokoro-82M を使った日本語/英語のテキスト読み上げ API。結果は WAV または MP3 (24kHz, mono) で返します。",
)
store.init()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SAMPLE_RATE = 24000
VOICES = {
    "j": ["jf_alpha", "jf_gongitsune", "jf_nezumi", "jf_tebukuro", "jm_kumo"],
    "a": ["af_heart", "af_bella", "af_nicole", "am_adam", "am_michael"],
}
_pipelines = {}
_lock = threading.Lock()


def get_pipeline(lang):
    from kokoro import KPipeline
    if lang not in _pipelines:
        _pipelines[lang] = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M")
    return _pipelines[lang]


class TTSReq(BaseModel):
    text: str = Field(..., description="読み上げるテキスト", examples=["こんにちは。"])
    lang: str = Field("j", description="言語コード。j=日本語, a=英語(米)")
    voice: str = Field("jf_alpha", description="ボイス名。GET /voices で一覧取得")
    speed: float = Field(1.0, ge=0.5, le=2.0, description="話速 (0.5〜2.0)")
    format: str = Field("wav", description="出力形式。wav または mp3")
    use_replacements: bool = Field(True, description="置換ルールを適用する")
    record_history: bool = Field(True, description="履歴に記録する")


@app.get("/health", summary="死活確認")
def health():
    return {"status": "ok"}


@app.get("/voices", summary="言語ごとのボイス一覧")
def voices():
    return VOICES


@app.post("/tts", summary="テキストを音声(WAV)に変換", response_class=Response, responses={200: {"content": {"audio/wav": {}, "audio/mpeg": {}}}})
def tts(req: TTSReq):
    if not req.text.strip():
        raise HTTPException(400, "text is empty")
    if req.lang not in VOICES:
        raise HTTPException(400, "unsupported lang")
    if req.format not in ("wav", "mp3"):
        raise HTTPException(400, "unsupported format")
    t0 = time.time()
    text = store.apply_rules(req.text) if req.use_replacements else req.text
    with _lock:
        pipe = get_pipeline(req.lang)
        chunks = [np.asarray(a) for _, _, a in pipe(text, voice=req.voice, speed=req.speed)]
    if not chunks:
        raise HTTPException(500, "no audio generated")
    buf = io.BytesIO()
    sf.write(buf, np.concatenate(chunks), SAMPLE_RATE, format=req.format.upper())
    ms = int((time.time() - t0) * 1000)
    if req.record_history:
        store.add_history(req.text, text, req.lang, req.voice, req.speed, req.format, ms)
    media = "audio/mpeg" if req.format == "mp3" else "audio/wav"
    return Response(
        buf.getvalue(), media_type=media,
        headers={"X-Generation-Ms": str(ms), "X-Applied-Text": urllib.parse.quote(text), "Access-Control-Expose-Headers": "X-Generation-Ms, X-Applied-Text"},
    )


# ---- 置換ルール ----
class Rule(BaseModel):
    src: str = Field(..., description="置換前 (大文字小文字は区別しない)", examples=["kotoko"])
    dst: str = Field(..., description="置換後", examples=["ことこ"])


@app.get("/replacements", summary="置換ルール一覧", tags=["replacements"])
def replacements_list():
    return store.list_rules()


@app.post("/replacements", summary="置換ルールを追加/更新 (src が同じなら上書き)", tags=["replacements"])
def replacements_upsert(rule: Rule):
    if not rule.src.strip():
        raise HTTPException(400, "src is empty")
    store.upsert_rules([(rule.src, rule.dst)])
    return rule


@app.delete("/replacements", summary="置換ルールを削除", tags=["replacements"])
def replacements_delete(src: str):
    if not store.delete_rule(src):
        raise HTTPException(404, "not found")
    return {"deleted": src}


@app.get("/replacements/export", summary="`src@dst` 形式のテキストでエクスポート", response_class=PlainTextResponse, tags=["replacements"])
def replacements_export():
    return "".join(f"{r['src']}@{r['dst']}\n" for r in store.list_rules())


@app.post("/replacements/import", summary="`src@dst` 形式のテキスト(1行1件)を一括登録", tags=["replacements"])
async def replacements_import(request: Request):
    body = (await request.body()).decode("utf-8", "replace")
    pairs = []
    for line in body.splitlines():
        if "@" in line and not line.lstrip().startswith("#"):
            src, dst = line.split("@", 1)
            if src.strip():
                pairs.append((src.strip(), dst.strip()))
    store.upsert_rules(pairs)
    return {"imported": len(pairs)}


# ---- 読みチェック ----
class G2PReq(BaseModel):
    text: str
    lang: str = "j"
    use_replacements: bool = True


@app.post("/g2p", summary="テキストがどう読まれるか(音素列)を返す", tags=["tools"])
def g2p(req: G2PReq):
    if req.lang not in VOICES:
        raise HTTPException(400, "unsupported lang")
    text = store.apply_rules(req.text) if req.use_replacements else req.text
    with _lock:
        ps = get_pipeline(req.lang).g2p(text)[0]
    return {"input": req.text, "applied": text, "phonemes": ps}


# ---- 履歴 ----
@app.get("/history", summary="生成履歴 (新しい順)", tags=["history"])
def history(limit: int = 20, offset: int = 0):
    total, items = store.list_history(min(max(limit, 1), 200), max(offset, 0))
    return {"total": total, "items": items}


@app.delete("/history", summary="履歴を全削除", tags=["history"])
def history_clear():
    store.clear_history()
    return {"cleared": True}
