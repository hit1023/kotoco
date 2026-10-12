import io
import threading

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

app = FastAPI(
    title="kotoco API",
    version="0.1.0",
    description="Kokoro-82M を使った日本語/英語のテキスト読み上げ API。結果は WAV または MP3 (24kHz, mono) で返します。",
)
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
    with _lock:
        pipe = get_pipeline(req.lang)
        chunks = [np.asarray(a) for _, _, a in pipe(req.text, voice=req.voice, speed=req.speed)]
    if not chunks:
        raise HTTPException(500, "no audio generated")
    buf = io.BytesIO()
    sf.write(buf, np.concatenate(chunks), SAMPLE_RATE, format=req.format.upper())
    media = "audio/mpeg" if req.format == "mp3" else "audio/wav"
    return Response(buf.getvalue(), media_type=media)
