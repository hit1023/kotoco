import io
import re
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
    version="0.3.0",
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


_SENT = re.compile(r"[^。！？!?\n]+[。！？!?]*")
_NOSPACE_BEFORE = set(",.!?;:、。！？…")


def _join_ps(parts):
    out = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        out += p if (not out or p[0] in _NOSPACE_BEFORE or out[-1] == " ") else " " + p
    return out


def build_ps_chunks(pipe, text, lang):
    """発音辞書の単語は音素列をそのまま埋め込み、それ以外は通常の G2P。
    辞書にヒットしなければ None (=通常の Kokoro 処理に任せる)。510音素以内に分割して返す。"""
    pat, mp = store.pron_pattern(lang)
    if not pat or not pat.search(text):
        return None
    chunks, cur = [], ""
    for sent in _SENT.findall(text):
        parts, pos = [], 0
        for m in pat.finditer(sent):
            if m.start() > pos and sent[pos:m.start()].strip():
                parts.append(pipe.g2p(sent[pos:m.start()])[0])
            parts.append(mp[m.group(0).lower()])
            pos = m.end()
        if sent[pos:].strip():
            parts.append(pipe.g2p(sent[pos:])[0])
        ps = _join_ps(parts)
        if not ps:
            continue
        if cur and len(cur) + len(ps) + 1 > 500:
            chunks.append(cur)
            cur = ""
        cur = _join_ps([cur, ps]) if cur else ps
    if cur:
        chunks.append(cur)
    return [c[:510] for c in chunks]


def synth_audio(text, lang, voice, speed, use_pron):
    pipe = get_pipeline(lang)
    chunks = build_ps_chunks(pipe, text, lang) if use_pron else None
    if chunks is None:
        return [np.asarray(a) for _, _, a in pipe(text, voice=voice, speed=speed)]
    model = pipe.model
    pack = pipe.load_voice(voice).to(model.device)
    return [pipe.infer(model, ps, pack, speed).audio.detach().cpu().numpy() for ps in chunks]


class TTSReq(BaseModel):
    text: str = Field("", description="読み上げるテキスト (phonemes 指定時は省略可)", examples=["こんにちは。"])
    phonemes: str = Field("", description="音素列を直接指定して合成する (発音の試聴用)。指定時は text より優先")
    lang: str = Field("j", description="言語コード。j=日本語, a=英語(米)")
    voice: str = Field("jf_alpha", description="ボイス名。GET /voices で一覧取得")
    speed: float = Field(1.0, ge=0.5, le=2.0, description="話速 (0.5〜2.0)")
    format: str = Field("wav", description="出力形式。wav または mp3")
    use_replacements: bool = Field(True, description="置換ルールを適用する")
    use_pronunciations: bool = Field(True, description="発音辞書(音素列の直接指定)を適用する")
    record_history: bool = Field(True, description="履歴に記録する")


@app.get("/health", summary="死活確認")
def health():
    return {"status": "ok"}


@app.get("/voices", summary="言語ごとのボイス一覧")
def voices():
    return VOICES


@app.post("/tts", summary="テキストを音声(WAV)に変換", response_class=Response, responses={200: {"content": {"audio/wav": {}, "audio/mpeg": {}}}})
def tts(req: TTSReq):
    if not req.text.strip() and not req.phonemes.strip():
        raise HTTPException(400, "text is empty")
    if req.lang not in VOICES:
        raise HTTPException(400, "unsupported lang")
    if req.format not in ("wav", "mp3"):
        raise HTTPException(400, "unsupported format")
    t0 = time.time()
    text = store.apply_rules(req.text) if req.use_replacements else req.text
    if req.phonemes.strip():
        _check_ps(req.phonemes)
    with _lock:
        if req.phonemes.strip():
            pipe = get_pipeline(req.lang)
            pack = pipe.load_voice(req.voice).to(pipe.model.device)
            chunks = [pipe.infer(pipe.model, req.phonemes.strip()[:510], pack, req.speed).audio.detach().cpu().numpy()]
        else:
            chunks = synth_audio(text, req.lang, req.voice, req.speed, req.use_pronunciations)
    if not chunks:
        raise HTTPException(500, "no audio generated")
    buf = io.BytesIO()
    sf.write(buf, np.concatenate(chunks), SAMPLE_RATE, format=req.format.upper())
    ms = int((time.time() - t0) * 1000)
    if req.record_history and not req.phonemes.strip():
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
    use_pronunciations: bool = True


@app.post("/g2p", summary="テキストがどう読まれるか(音素列)を返す", tags=["tools"])
def g2p(req: G2PReq):
    if req.lang not in VOICES:
        raise HTTPException(400, "unsupported lang")
    text = store.apply_rules(req.text) if req.use_replacements else req.text
    with _lock:
        pipe = get_pipeline(req.lang)
        chunks = build_ps_chunks(pipe, text, req.lang) if req.use_pronunciations else None
        ps = " ".join(chunks) if chunks is not None else pipe.g2p(text)[0]
    return {"input": req.text, "applied": text, "phonemes": ps, "from_dictionary": chunks is not None}


@app.get("/phonemes/vocab", summary="Kokoro が受け付ける音素記号の一覧", tags=["tools"])
def phonemes_vocab():
    with _lock:
        vocab = get_pipeline("j").model.vocab
    return {"symbols": "".join(sorted(k for k in vocab if k != " "))}


# ---- 発音辞書 ----
class Pron(BaseModel):
    word: str = Field(..., description="対象の単語 (大文字小文字は区別しない)", examples=["kotoko"])
    phonemes: str = Field(..., description="音素列。POST /g2p や GET /phonemes/vocab を参考に", examples=["kotoko"])
    lang: str = Field("j", description="言語コード")


def _check_ps(ps):
    with _lock:
        vocab = get_pipeline("j").model.vocab
    bad = sorted({ch for ch in ps if ch not in vocab})
    if bad:
        raise HTTPException(400, "unknown phoneme symbols: " + "".join(bad))


@app.get("/pronunciations", summary="発音辞書の一覧", tags=["pronunciations"])
def prons_list(lang: str = None):
    return store.list_prons(lang)


@app.post("/pronunciations", summary="発音辞書に追加/更新", tags=["pronunciations"])
def prons_upsert(p: Pron):
    if not p.word.strip() or not p.phonemes.strip():
        raise HTTPException(400, "word and phonemes are required")
    if p.lang not in VOICES:
        raise HTTPException(400, "unsupported lang")
    _check_ps(p.phonemes)
    store.upsert_pron(p.word.strip(), p.lang, p.phonemes.strip())
    return p


@app.delete("/pronunciations", summary="発音辞書から削除", tags=["pronunciations"])
def prons_delete(word: str, lang: str = "j"):
    if not store.delete_pron(word, lang):
        raise HTTPException(404, "not found")
    return {"deleted": word}


@app.get("/pronunciations/export", summary="`word@phonemes` 形式でエクスポート", response_class=PlainTextResponse, tags=["pronunciations"])
def prons_export(lang: str = "j"):
    return "".join(f"{r['word']}@{r['ps']}\n" for r in store.list_prons(lang))


@app.post("/pronunciations/import", summary="`word@phonemes` 形式(1行1件)を一括登録", tags=["pronunciations"])
async def prons_import(request: Request, lang: str = "j"):
    n = 0
    for line in (await request.body()).decode("utf-8", "replace").splitlines():
        if "@" in line and not line.lstrip().startswith("#"):
            w, ps = (x.strip() for x in line.split("@", 1))
            if w and ps:
                _check_ps(ps)
                store.upsert_pron(w, lang, ps)
                n += 1
    return {"imported": n}


# ---- 履歴 ----
@app.get("/history", summary="生成履歴 (新しい順)", tags=["history"])
def history(limit: int = 20, offset: int = 0):
    total, items = store.list_history(min(max(limit, 1), 200), max(offset, 0))
    return {"total": total, "items": items}


@app.delete("/history", summary="履歴を全削除", tags=["history"])
def history_clear():
    store.clear_history()
    return {"cleared": True}
