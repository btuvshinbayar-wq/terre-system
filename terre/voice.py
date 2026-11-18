"""Ярих: Microsoft Edge-ийн үнэгүй TTS (API түлхүүргүй) -> mp3 -> тоглуулах. Англи эсвэл монгол хоолой (config: language)."""
import asyncio
import logging

from .config import CFG, DATA

log = logging.getLogger("terre.voice")
BRIEFING_MP3 = DATA / "briefing.mp3"
ALERT_MP3 = DATA / "alert.mp3"
SPEAKING = {"on": False, "text": ""}   # самбар дээрх реакторын анимацад


def enabled():
    return bool(CFG.get("voice", {}).get("enabled"))


async def synth(text, path):
    import edge_tts
    from .config import EN
    v = CFG.get("voice", {}) or {}
    # Англи горимд англи хоолой (Британи эр хоолой — JARVIS маягийн), монгол горимд монгол хоолой
    voice = v.get("name_en", "en-GB-RyanNeural") if EN() else v.get("name", "mn-MN-YesuiNeural")
    await edge_tts.Communicate(text, voice).save(str(path))


async def speak(text, path=BRIEFING_MP3, play=True):
    if not enabled() or not text:
        return
    try:
        await synth(text, path)
        from . import health
        health.ok("Дуу")
        if play:
            from playsound3 import playsound
            SPEAKING.update(on=True, text=text)
            await asyncio.to_thread(playsound, str(path))
    except Exception as e:
        log.warning("Дуу гаргаж чадсангүй: %s", e)
        from . import health
        health.err("Дуу", e)
    finally:
        SPEAKING["on"] = False
