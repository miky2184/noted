import asyncio

from fastapi import APIRouter, File, HTTPException, UploadFile


router = APIRouter()


# ── Voice transcription ────────────────────────────────────────────────────────

_whisper_model = None

def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        try:
            import ssl, whisper
            # macOS Python non usa i certificati di sistema → patch temporanea per il download del modello
            _orig = ssl._create_default_https_context
            ssl._create_default_https_context = ssl._create_unverified_context
            try:
                _whisper_model = whisper.load_model("base")
            finally:
                ssl._create_default_https_context = _orig
        except ImportError:
            raise HTTPException(status_code=501, detail="openai-whisper non installato. Esegui: pip install -e .")
    return _whisper_model

def _ensure_ffmpeg_in_path():
    """Aggiunge le dir Homebrew al PATH se ffmpeg non è già trovabile."""
    import os, shutil
    if shutil.which("ffmpeg"):
        return
    extras = ["/opt/homebrew/bin", "/usr/local/bin", "/opt/homebrew/sbin"]
    current = os.environ.get("PATH", "")
    os.environ["PATH"] = ":".join(extras) + (":" + current if current else "")

@router.post("/api/voice/transcribe")
async def api_voice_transcribe(audio: UploadFile = File(...)):
    import tempfile, os
    _ensure_ffmpeg_in_path()
    suffix = ".webm" if "webm" in (audio.content_type or "") else ".mp4"
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="Audio vuoto")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        tmp_path = f.name
    try:
        loop = asyncio.get_event_loop()
        model = await loop.run_in_executor(None, _get_whisper_model)
        result = await loop.run_in_executor(None, lambda: model.transcribe(tmp_path, language="it"))
        return {"text": result["text"].strip()}
    except Exception as exc:
        msg = str(exc)
        if "ffmpeg" in msg.lower() or "No such file or directory" in msg:
            msg = "ffmpeg non trovato. Installalo con: brew install ffmpeg"
        raise HTTPException(status_code=500, detail=msg)
    finally:
        os.unlink(tmp_path)
