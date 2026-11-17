"""Англи дуут тушаалыг компьютер дээрээ, интернэт, API түлхүүргүйгээр текст болгох (Vosk, offline).

Ажиллах дараалал (main._transcribe):
  1) Англи горимд (language: en) эхлээд энд Vosk-оор таньна — үнэгүй, токен зарцуулахгүй, бичлэг гадагш гарахгүй.
  2) Тод, итгэлтэй англи яриа биш бол (жишээ нь монголоор хэлсэн) Gemini-д илгээж таниулна.
Дуудах үг («Hey Ted»)-ийн загварыг дахин ашиглана (vosk-model-small-en-us, ≈40 MB).
Тохиргоо: config.yaml → voice.offline_english (true/false), voice.offline_min_confidence (0.80).
"""
import io
import json
import logging
import threading
import wave

from .config import CFG, EN

log = logging.getLogger("terre.stt")
_model = None
_lock = threading.Lock()


def cfg():
    return CFG.get("voice") or {}


def enabled():
    return EN() and cfg().get("offline_english", True) is not False


def available():
    try:
        import vosk  # noqa: F401
        return True
    except ImportError:
        return False


_failed_at = 0.0


def model():
    """Vosk загвар (≈40 MB, анх хэрэглэхэд нэг удаа татна). Татаж чадахгүй бол 10 минут дахин оролдохгүй."""
    global _model, _failed_at
    import time
    with _lock:
        if _model is None:
            if time.time() - _failed_at < 600:
                raise RuntimeError("Vosk загвар саяхан ачаалж чадаагүй")
            import vosk
            from . import wake
            vosk.SetLogLevel(-1)
            try:
                _model = vosk.Model(str(wake._model_path()))
            except Exception:
                _failed_at = time.time()
                raise
            finally:
                if not wake.enabled() and wake.STATE.get("status") == "loading":
                    wake._set("off")
        return _model


def transcribe(wav_bytes):
    """WAV (16 kHz, mono, 16-bit) → (текст, дундаж итгэл). Танихгүй бол ("", 0)."""
    if not enabled() or not wav_bytes or not available():
        return "", 0.0
    try:
        import vosk
        with wave.open(io.BytesIO(wav_bytes)) as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2:
                return "", 0.0
            rate, frames = w.getframerate(), w.readframes(w.getnframes())
        rec = vosk.KaldiRecognizer(model(), rate)
        rec.SetWords(True)
        toks = []
        for i in range(0, len(frames), 8000):
            if rec.AcceptWaveform(frames[i:i + 8000]):
                toks += json.loads(rec.Result()).get("result") or []
        toks += json.loads(rec.FinalResult()).get("result") or []
    except Exception as e:
        log.warning("Offline дуу таних: %s", e)
        return "", 0.0
    words = [t for t in toks if t.get("word") and t["word"] != "[unk]"]
    if not words:
        return "", 0.0
    confs = [float(t.get("conf", 0)) for t in words]
    avg = sum(confs) / len(confs)
    text = " ".join(t["word"] for t in words)
    min_avg = float(cfg().get("offline_min_confidence", 0.80))
    # Тод англи тушаал: 2-25 үг, дундаж итгэл өндөр, аль ч үг хэт бүдэг биш.
    # Монгол яриаг англи загвар ихэвчлэн бага итгэлтэй таньдаг тул энэ шүүлтүүрээр Gemini руу шилжинэ.
    if not (2 <= len(words) <= 25) or avg < min_avg or min(confs) < 0.45:
        return "", avg
    return text, avg
