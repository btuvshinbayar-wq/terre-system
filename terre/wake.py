"""Дуудах үг: "Терри / Terre" гэж дуудахад сонсож, хэлсэн тушаалыг биелүүлнэ (утасны Siri шиг).

Нууцлал, зардал:
- Дуудах үгийг компьютер дээрээ, интернэтгүйгээр Vosk-оор таньдаг. Өрөөний яриа гадагш гарахгүй, токен зарцуулахгүй.
- Дуудсаны ДАРАА хэлсэн тушаалын бичлэгийг л Gemini-д илгээж текст болгоно.

Хэрэгцээ: pip install vosk sounddevice  (README 3.10). Загварыг (≈40 MB) анх асаахад өөрөө татна.
Тохиргоо: config.yaml → voice.wake (enabled, words, auto_run).
"""
import array
import asyncio
import io
import json
import logging
import math
import os
import queue
import threading
import time
import wave
import zipfile

from .config import CFG, DATA

log = logging.getLogger("terre.wake")

MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
RATE = 16000
BLOCK = 1600                     # 0.1 сек
# "Terre" монгол дуудлагаараа англи загварт "terry / terra"-тай ойролцоо сонсогддог
DEFAULT_WORDS = ["terry", "terra"]

STATE = {"status": "off", "msg": "", "heard": ""}   # off | loading | idle | listening | thinking | error
_thread = None
_stop = threading.Event()


def cfg():
    return (CFG.get("voice") or {}).get("wake") or {}


def enabled():
    return bool(cfg().get("enabled"))


def _set(status, msg=""):
    STATE.update(status=status, msg=msg)


def _model_path():
    p = DATA / MODEL_NAME
    if (p / "am").exists() or (p / "conf").exists():
        return p
    _set("loading", "Дуудах үгийн загварыг татаж байна (≈40 MB, нэг удаа)…")
    import urllib.request
    tmp = DATA / (MODEL_NAME + ".zip.part")
    with urllib.request.urlopen(MODEL_URL, timeout=60) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
    with zipfile.ZipFile(tmp) as z:
        z.extractall(DATA)
    try:
        os.remove(tmp)       # Terre-ийн өөрийн түр файл
    except OSError:
        pass
    return p


def _rms(chunk):
    a = array.array("h", chunk)
    if not a:
        return 0.0
    return math.sqrt(sum(x * x for x in a) / len(a))


def _beep(freq=1150, ms=110):
    try:
        import winsound
        winsound.Beep(freq, ms)
    except Exception:
        pass


def _wav(chunks):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(chunks))
    return buf.getvalue()


def _record_command(q):
    """Дуудсаны дараах яриаг чимээгүй болох хүртэл (эсвэл 9 сек) бичнэ."""
    chunks, started, silent, t0 = [], False, 0, time.time()
    noise = None
    while time.time() - t0 < 9:
        try:
            c = q.get(timeout=1)
        except queue.Empty:
            continue
        chunks.append(c)
        lvl = _rms(c)
        noise = lvl if noise is None else min(noise * 0.95 + lvl * 0.05, noise + 50)
        loud = lvl > max(450.0, (noise or 0) * 2.2)
        if loud:
            started, silent = True, 0
        elif started:
            silent += 1
            if silent >= 12:            # 1.2 сек чимээгүй
                break
        elif time.time() - t0 > 4:      # 4 сек юу ч хэлээгүй
            return None
    return _wav(chunks) if started else None


def _loop(loop, handler):
    try:
        import sounddevice as sd
        import vosk
    except ImportError:
        _set("error", "vosk, sounddevice суугаагүй (README 3.10)")
        return
    try:
        vosk.SetLogLevel(-1)
        model = vosk.Model(str(_model_path()))
    except Exception as e:
        _set("error", f"Загвар ачаалж чадсангүй: {e}")
        return
    words = [w.lower() for w in (cfg().get("words") or DEFAULT_WORDS)]
    rec = vosk.KaldiRecognizer(model, RATE, json.dumps(words + ["[unk]"]))
    q = queue.Queue(maxsize=400)

    def cb(data, frames, t, status):
        try:
            q.put_nowait(bytes(data))
        except queue.Full:
            pass

    from . import voice
    try:
        with sd.RawInputStream(samplerate=RATE, blocksize=BLOCK, dtype="int16", channels=1, callback=cb):
            _set("idle", "«Терри» гэж дуудаарай")
            log.info("Дуудах үг идэвхжлээ: %s", words)
            while not _stop.is_set():
                try:
                    data = q.get(timeout=1)
                except queue.Empty:
                    continue
                if voice.SPEAKING.get("on"):        # Terre өөрөө ярьж байхад сонсохгүй
                    rec.Reset()
                    continue
                if rec.AcceptWaveform(data):
                    text = json.loads(rec.Result()).get("text", "")
                else:
                    text = json.loads(rec.PartialResult()).get("partial", "")
                if not any(w in text.split() for w in words):
                    continue
                rec.Reset()
                _set("listening", "Сонсож байна…")
                _beep()
                wav = _record_command(q)
                if wav:
                    _set("thinking", "Ойлгож байна…")
                    try:
                        asyncio.run_coroutine_threadsafe(handler(wav), loop).result(timeout=180)
                    except Exception as e:
                        log.warning("Дуут тушаал алдаа: %s", e)
                else:
                    _beep(700, 90)
                while not q.empty():                 # хариу ярьж байх хооронд хуримтлагдсаныг хаяна
                    q.get_nowait()
                _set("idle", "«Терри» гэж дуудаарай")
    except Exception as e:
        _set("error", f"Микрофон нээгдсэнгүй: {e}")
        log.warning("Дуудах үг: %s", e)


def start(loop, handler):
    """handler: async def(wav_bytes) — main.py-д тушаалыг гүйцэтгэнэ."""
    global _thread
    if not enabled() or (_thread and _thread.is_alive()):
        return False
    _stop.clear()
    _set("loading", "Эхэлж байна…")
    _thread = threading.Thread(target=_loop, args=(loop, handler), daemon=True, name="terre-wake")
    _thread.start()
    return True


def stop():
    _stop.set()
