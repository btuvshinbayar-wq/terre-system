"""FastAPI сервер: самбар + API + далд давтамжит шалгалт."""
import asyncio
import contextlib
import datetime
import logging
import os
import secrets
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel

from . import brain, engine, files, health, journal, learn, organizer, store, tasks, voice
from .config import CFG, DATA, DEMO, EN, HOME, ROOT, address, gemini_key, greeting, lang, save_config_value, source_enabled

log = logging.getLogger("terre")


def _L(mn, en):
    return en if EN() else mn

LOOP = None


# ======================= Нэвтрэх токен =======================
def dashboard_token():
    p = DATA / "dashboard_token"
    if not p.exists():
        p.write_text(secrets.token_urlsafe(24), encoding="utf-8")
    return p.read_text(encoding="utf-8").strip()


TOKEN = dashboard_token()
LOCKED_PAGE = """<!DOCTYPE html><html lang="mn"><meta charset="utf-8"><title>TED</title>
<body style="background:#050910;color:#d8e6f3;font:16px Segoe UI,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="text-align:center"><div style="font-size:12px;letter-spacing:5px;color:#38d6f5">TED</div>
<h2 style="font-weight:400">Самбарыг tray icon-оос эсвэл Эхлэх цэснээс нээнэ үү</h2>
<p style="color:#7d93ab">Аюулгүй байдлын үүднээс самбарыг зөвхөн TED өөрөө нээж болно.</p></div></body></html>"""


async def _wait_for_internet(timeout=60):
    import socket
    for _ in range(timeout // 3):
        try:
            await asyncio.to_thread(socket.create_connection, ("www.google.com", 443), 3)
            return True
        except OSError:
            await asyncio.sleep(3)
    return False


async def _startup_sequence():
    from . import desktop
    st = CFG.get("startup", {})
    if st.get("open_browser", True):
        desktop.open_window("/")
    try:   # 2026-11-17: дуудах үг худал асаж бичигдсэн яриаг журналаас нэг удаа арилгана (TED-ийн өөрийн бичлэг)
        if learn.kv_get("purged_voice_v1", "") != "1":
            with journal._lock:
                journal._db.execute("DELETE FROM activity WHERE kind='voice'")
                journal._db.commit()
            learn.kv_set("purged_voice_v1", "1")
    except Exception as e:
        log.warning("Дуут бичлэг цэвэрлэх: %s", e)
    if not DEMO:
        try:
            from . import demo
            gone = await asyncio.to_thread(demo.purge)
            if gone:
                log.info("Демо горимын %s бичлэгийг цэвэрлэлээ", gone)
        except Exception as e:
            log.warning("Демо бичлэг цэвэрлэж чадсангүй: %s", e)
    await _wait_for_internet()
    try:
        await engine.run_cycle()
    except Exception:
        log.exception("Эхний шалгалт амжилтгүй")
    if engine.sm_enabled() and CFG.get("school_manager", {}).get("open_at_startup") and not DEMO:
        try:
            await engine.start_school_manager()
        except Exception as e:
            log.warning("School Manager асаасангүй: %s", e)
    await engine.make_briefing(speak=st.get("speak", True))


async def _background_loop():
    minutes = max(2, int(CFG.get("refresh_minutes", 10)))
    while True:
        await asyncio.sleep(minutes * 60)
        try:
            urgent = await engine.run_cycle()
            if urgent:
                msg = (f"{address()}, {len(urgent)} new urgent message{'s' if len(urgent) > 1 else ''}. {urgent[0]['summary']}" if EN()
                       else f"{address()}, яаралтай {len(urgent)} шинэ мессеж ирлээ. {urgent[0]['summary']}")
                await voice.speak(msg, path=voice.ALERT_MP3)
        except Exception:
            log.exception("Далд шалгалт амжилтгүй")


async def _watchdog():
    """Сервер 30 сек-ээс удаан гацвал бүх урсгалын байдлыг data/hang.log-д бичнэ (алдааг олоход)."""
    import faulthandler
    try:
        f = open(DATA / "hang.log", "a", encoding="utf-8")
    except OSError:
        return
    f.write(f"\n=== TED асав {datetime.datetime.now().isoformat(timespec='seconds')} ===\n")
    f.flush()
    try:
        while True:
            faulthandler.dump_traceback_later(30, repeat=True, file=f)   # 5 сек тутам цагийг дахин эхлүүлнэ
            await asyncio.sleep(5)
    finally:
        faulthandler.cancel_dump_traceback_later()


@contextlib.asynccontextmanager
async def lifespan(app):
    global LOOP
    LOOP = asyncio.get_running_loop()
    from . import telegram_bot
    if telegram_bot.start(LOOP):
        health.ok("Telegram bot", "Ажиллаж байна")
    from . import wake
    if wake.start(LOOP, _wake_command):
        log.info("Дуудах үг эхэллээ")
    if source_enabled("app_notifications") and not DEMO:
        from .connectors import notifications
        notifications.start()       # Viber/Discord/Messenger-ийн мэдэгдлийг 15 сек тутам санах ойд авна
    tasks_ = [asyncio.create_task(_startup_sequence()), asyncio.create_task(_background_loop()),
              asyncio.create_task(engine.scheduler_loop()), asyncio.create_task(_watchdog())]
    yield
    for t in tasks_:
        t.cancel()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def auth(request: Request, call_next):
    path = request.url.path
    if request.query_params.get("k") == TOKEN and request.method == "GET" and not path.startswith("/api/"):
        resp = RedirectResponse(str(request.url.remove_query_params("k")), status_code=302)
        resp.set_cookie("terre", TOKEN, httponly=True, samesite="strict", max_age=3600 * 24 * 365)
        return resp
    ok = request.cookies.get("terre") == TOKEN or request.headers.get("x-terre-token") == TOKEN
    if not ok:
        if path.startswith("/api/"):
            return Response('{"detail":"unauthorized"}', status_code=401, media_type="application/json")
        return HTMLResponse(LOCKED_PAGE, status_code=401)
    return await call_next(request)


def _wrap(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))


async def _awrap(coro):
    try:
        return await coro
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/quick")
def quick():
    return FileResponse(ROOT / "web" / "quick.html", headers={"Cache-Control": "no-store"})


# ======================= Төлөв =======================
@app.get("/api/state")
def state():
    return {
        "owner": address(),
        "greeting": greeting(),
        "lang": lang(),
        "demo": DEMO,
        "auto_actions": bool(CFG.get("auto_actions")),
        "sources": _sources(),
        **engine.STATE,
        "counts": store.today_counts(),
        "urgent": store.by_status(["urgent"], 30),
        "pending": store.by_status(["pending"], 50),
        "auto": store.by_status(["auto", "auto_done"], 40),
        "done": store.by_status(["sent", "dismissed"], 15),
        "sm": DEMO or engine.sm_enabled(),
        "macros": _commands_for_ui(),
        "sm_running": engine.STATE.get("sm_running"),
        "sm_lists": _sm_lists(),
        "files": {"moved": files.recent(["moved"], 15), "suggested": files.recent(["suggested"], 30),
                  "stats": files.stats(), "categories": files.categories(), "root": files.root(),
                  "unconnected_moved": files.unconnected_count()},
        "folders": organizer.folders_overview(),
        "tasks": {"open": tasks.open_tasks(), "done": tasks.done_recent(8)},
        "health": health.report(),
        "has_gemini": bool(gemini_key()),
        "app_notif": source_enabled("app_notifications"),
        "voice_ok": bool(gemini_key()) or _offline_voice(),
    }


def _offline_voice():
    from . import stt
    return stt.enabled() and stt.available()


def _sources():
    names = {"gmail": "Gmail", "google_calendar": "Google Calendar", "google_chat": "Google Chat",
             "outlook": "Outlook", "telegram": "Telegram"}
    out = list(names.values()) if DEMO else [v for k, v in names.items() if source_enabled(k)]
    if not DEMO:
        from .connectors import imap_mail
        out += [a["name"] for a in imap_mail.accounts()]
    if DEMO or engine.sm_enabled():
        out.append("School Manager")
    if files.cfg().get("enabled", True):
        out.append(_L("Файл эмхлэгч", "File organizer"))
    if gemini_key():
        out.append("Gemini AI")
    return out


def _sm_lists():
    """Тушаалын талбарт санал болгох жагсаалт (School Manager-ийн жинхэнэ өгөгдөл + TED-ийн эмхэлсэн файлууд)."""
    st = engine.STATE.get("sm_state") or {}
    out = {k: st.get(k, []) for k in ("teachers", "plans", "evaluations", "observations", "curriculum_teachers")}
    recent = [f.get("dest") or f.get("src") for f in files.recent(["moved"], 200)]
    recent = [p for p in recent if p]
    out["docs"] = [p for p in recent if p.lower().endswith((".docx", ".doc", ".pdf", ".xlsx", ".xls"))][:60]
    out["jsons"] = [p for p in recent if p.lower().endswith(".json")][:40]
    return out


def _commands_for_ui():
    sched = {j["command"]: j["at"] for j in (CFG.get("school_manager", {}).get("schedule") or [])}
    from . import i18n
    return [{**i18n.command_for_ui(c), "schedule": sched.get(c["name"])} for c in engine.commands()]


@app.get("/api/speaking")
def speaking():
    from . import wake
    vp = engine.STATE.get("voice_plan")
    return {"on": voice.SPEAKING["on"], "wake": wake.STATE["status"], "voice_plan_ts": vp["ts"] if vp else 0}


@app.post("/api/wake/pause")
def wake_pause(b: dict):
    from . import wake
    wake.set_paused(bool(b.get("on")))
    return {"ok": True, "status": wake.STATE["status"]}


@app.get("/api/voice-plan")
def voice_plan():
    return engine.STATE.get("voice_plan") or {}


# ======================= Мессеж =======================
class SendBody(BaseModel):
    body: str


class RedraftBody(BaseModel):
    instruction: str


@app.post("/api/items/{item_id:path}/send")
async def send(item_id: str, b: SendBody):
    try:
        r = await engine.send(item_id, b.body)
    except Exception as e:
        raise HTTPException(500, f"Илгээж чадсангүй: {e}")
    return {"ok": True, **(r or {})}


@app.post("/api/items/{item_id:path}/apply")
async def apply(item_id: str):
    await _awrap(engine.apply(item_id))
    return {"ok": True}


@app.post("/api/items/{item_id:path}/dismiss")
def dismiss(item_id: str):
    _wrap(engine.dismiss, item_id)
    return {"ok": True}


@app.post("/api/items/{item_id:path}/read")
async def mark_read(item_id: str):
    await _awrap(engine.mark_read(item_id))
    return {"ok": True}


@app.post("/api/items/{item_id:path}/trash")
async def trash(item_id: str):
    await _awrap(engine.trash(item_id))
    return {"ok": True}


@app.post("/api/items/{item_id:path}/block")
async def block(item_id: str):
    key = await _awrap(engine.block(item_id))
    return {"ok": True, "blocked": key}


@app.get("/api/blocked")
def blocked_list():
    return {"blocked": engine.blocked()}


@app.post("/api/blocked/remove")
def blocked_remove(b: dict):
    key = str(b.get("sender", "")).strip().lower()
    engine._save_blocked([x for x in engine.blocked() if x != key])
    journal.add("mail", f"Блокоос гаргав: {key}"[:200], who="Та")
    return {"ok": True}


@app.post("/api/sm/plan/{plan_id}/status")
async def sm_plan_status(plan_id: str, b: dict):
    r = await _awrap(engine.sm_plan_status(plan_id, b.get("status") or "биелсэн"))
    return {"ok": True, "result": r}


@app.post("/api/items/{item_id:path}/redraft")
async def redraft(item_id: str, b: RedraftBody):
    item = store.get(item_id)
    if not item:
        raise HTTPException(404)
    text = await _awrap(asyncio.to_thread(brain.redraft, item, b.instruction))
    store.update(item_id, draft=text)
    return {"draft": text}


@app.post("/api/items/{item_id:path}/promote")
async def promote(item_id: str):
    item = store.get(item_id)
    if not item:
        raise HTTPException(404)
    draft = item.get("draft") or await _awrap(asyncio.to_thread(brain.redraft, item, "Энэ мессежид товч, эелдэг хариу бич"))
    engine.promote(item_id, draft)
    return {"ok": True}


@app.post("/api/refresh")
async def refresh():
    await engine.run_cycle()
    await engine.make_briefing(speak=False)
    return {"ok": True}


# ======================= Тушаал, дуу =======================
class CommandBody(BaseModel):
    text: str


class MacroBody(BaseModel):
    name: str
    params: dict = {}


def _cmd_context():
    st = engine.STATE.get("sm_state") or {}
    import datetime
    s = st.get("summary") or {}
    return {"teachers": st.get("teachers", []), "plans": st.get("plans", [])[:80], "today": datetime.date.today().isoformat(),
            "evaluations": st.get("evaluations", [])[:120], "observations": st.get("observations", [])[:80],
            "curriculum_teachers": st.get("curriculum_teachers", []),
            "sm_summary": {k: s.get(k) for k in ("teachers", "notes", "plans", "curriculum", "observations")} if s else {},
            "tasks": [t["title"] + (f" ({t['due']})" if t.get("due") else "") for t in tasks.open_tasks()][:20],
            "calendar": engine.STATE.get("calendar", [])}


async def _plan(text):
    plan = await asyncio.to_thread(brain.plan_command, text, engine.commands(), engine.STATE["metrics"], _cmd_context())
    if plan.get("type") == "files":
        from . import search
        r = await asyncio.to_thread(search.ask, plan.get("query") or text)
        plan = {"type": "files", "query": plan.get("query") or text, "say": r["answer"], "sources": r["sources"]}
    return plan


@app.post("/api/command")
async def command(b: CommandBody):
    return await _awrap(_plan(b.text))


@app.post("/api/voice")
async def voice_command(request: Request):
    """Самбар/quick цонхны микрофоноос ирсэн WAV → текст → тушаал."""
    audio = await request.body()
    from . import stt
    if not gemini_key() and not (stt.enabled() and stt.available()):
        raise HTTPException(400, _L("Дуугаар командлахад Gemini API түлхүүр хэрэгтэй (config.yaml → gemini.api_key)",
                                    "Voice commands need a Gemini API key or offline English (pip install vosk)"))
    text = await _transcribe(audio, request.headers.get("content-type", "audio/wav"))
    if not text:
        return {"text": "", "plan": {"type": "answer", "say": _L("Сонсогдсонгүй. Дахин оролдоно уу.", "Sorry, I didn't catch that. Please try again.")}}
    journal.add("voice", f"Дуут тушаал: «{text}»", who="Та")
    return {"text": text, "plan": await _awrap(_plan(text))}


async def _transcribe(audio, mime="audio/wav"):
    """Англиар хэлсэн бол компьютер дээрээ (Vosk, API-гүй), бусад үед Gemini-ээр текст болгоно."""
    from . import stt
    if "wav" in (mime or "") and stt.enabled():
        text, conf = await asyncio.to_thread(stt.transcribe, audio)
        if text:
            log.info("Offline англи таних (%.2f): %s", conf, text)
            return text
    if not gemini_key():
        return ""
    return await asyncio.to_thread(brain.transcribe, audio, mime)


async def _wake_command(wav):
    """«Хэй Тэд» гэж дуудсаны дараах тушаал: текст болгох → ойлгох → (бүрэн бол) биелүүлэх → дуугаар хариулах."""
    from . import wake
    text = await _transcribe(wav, "audio/wav")
    if not text:
        return            # тушаал биш (өөр хүнтэй ярьж буй яриа г.м.) — юу ч бичихгүй, хэлэхгүй
    wake.STATE["heard"] = ""
    try:
        plan = await _plan(text)
    except Exception as e:
        await voice.speak(_L("Ойлгож чадсангүй.", "Sorry, I didn't understand."), path=DATA / "say.mp3")
        log.warning("Дуут тушаал: %s", e)
        return
    say = plan.get("say") or ""
    if plan.get("type") == "macro":
        cmd = next((c for c in engine.commands() if c["name"] == plan.get("macro")), None)
        params = {k: v for k, v in (plan.get("params") or {}).items() if str(v).strip()}
        missing = [p["label"] for p in (cmd or {}).get("params", []) if not p.get("optional") and p["name"] not in params]
        auto = (CFG.get("voice") or {}).get("wake", {}).get("auto_run", True)
        if cmd and not missing and auto and not cmd.get("confirm"):
            entry = await engine.run_command(cmd["name"], params, who="Дуут тушаал")
            lines = [l.lstrip("✓→ ").strip() for l in entry.get("log", []) if l]
            lines = [l for l in lines if ":\\" not in l and "http" not in l and not l.startswith("School Manager дээр")]
            if entry.get("ok"):
                say = entry.get("say") or (_L("Хийлээ. " + ". ".join(lines[:2]), "Done."))
            else:
                say = _L("Чадсангүй. " + " ".join(lines[:1]), "Sorry, that did not work. Please check the dashboard.")
        else:
            engine.STATE["voice_plan"] = {"text": text, "plan": {**plan, "params": params}, "ts": time.time()}
            if missing:
                say = _L(f"{plan.get('macro')} — {', '.join(missing)} хэлээгүй байна. Самбар дээр бөглөөд ажиллуулна уу.",
                         "Some details are missing. Please fill them in on the dashboard and run it.")
            elif cmd and cmd.get("confirm"):
                say = _L(f"{plan.get('macro')} бэлэн. Бусдад мэдэгдэл очих тул самбар дээр шалгаад ажиллуулна уу.",
                         "It's ready. Other people will be notified, so please check it on the dashboard and run it.")
            else:
                say = _L(f"{plan.get('macro')} бэлэн. Самбар дээр ажиллуулна уу.", "It's ready. Please run it on the dashboard.")
            try:
                from . import desktop
                desktop.open_window("/")
            except Exception:
                pass
    else:
        engine.STATE["voice_plan"] = {"text": text, "plan": plan, "ts": time.time()}
    await voice.speak(say[:450], path=DATA / "say.mp3")


@app.get("/api/tts")
async def tts(text: str):
    path = DATA / "say.mp3"
    try:
        await voice.synth(text[:600], path)
    except Exception as e:
        raise HTTPException(400, f"Дуу үүсгэж чадсангүй: {e}")
    return FileResponse(path, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/macros/run")
async def run_macro(b: MacroBody):
    return await engine.run_command(b.name, b.params)


@app.post("/api/sm/start")
async def sm_start():
    return await _awrap(engine.start_school_manager())


# ======================= Файл =======================
class FileBody(BaseModel):
    category: str | None = None
    newname: str | None = None


@app.post("/api/files/undo-unconnected")
async def files_undo_unconnected():
    done, failed = await asyncio.to_thread(files.undo_unconnected)
    return {"ok": True, "done": done, "failed": failed}


@app.post("/api/files/{fid}/{action}")
async def file_action(fid: int, action: str, b: FileBody | None = None):
    try:
        if DEMO:
            new = {"approve": "moved", "ignore": "ignored", "undo": "undone"}[action]
            files._set(fid, status=new, **({"category": b.category} if b and b.category else {}),
                       **({"newname": b.newname} if b and b.newname else {}))
        elif action == "approve":
            await asyncio.to_thread(files.approve, fid, b.category if b else None, b.newname if b else None)
        elif action == "ignore":
            files.ignore(fid)
        elif action == "undo":
            await asyncio.to_thread(files.undo, fid)
        else:
            raise HTTPException(404)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True}


@app.post("/api/open")
def open_path(b: dict):
    """Файлыг Windows дээр нээх / Explorer-т харуулах (зөвхөн индекслэсэн эсвэл TED-ийн мэдэх файл)."""
    from . import search
    p = b.get("path", "")
    if not (search.is_indexed(p) or p.startswith(files.root())):
        raise HTTPException(403, "Энэ файлыг нээх эрхгүй")
    if os.name != "nt":
        raise HTTPException(400, "Зөвхөн Windows дээр")
    import subprocess
    if b.get("reveal"):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(p)])
    else:
        os.startfile(p)
    return {"ok": True}


# ======================= Хавтас =======================
class FolderBody(BaseModel):
    path: str | None = None
    newname: str | None = None
    mode: str | None = None
    target: str | None = None
    remove_empty: bool = False
    category: str | None = None


@app.post("/api/folders/pick")
async def folder_pick():
    from . import desktop
    try:
        paths = await asyncio.to_thread(desktop.pick_folders)
        return {"paths": paths, "path": paths[0] if paths else ""}
    except Exception as e:
        log.warning("Хавтас сонгох цонх: %s", e)
        raise HTTPException(400, _L(f"Хавтас сонгох цонх нээгдсэнгүй ({e}). Замыг гараар бичнэ үү.",
                                    f"The folder window did not open ({e}). Please type the path instead."))


@app.post("/api/folders")
def folder_add(b: FolderBody):
    return _wrap(organizer.add_folder, b.path or "", b.mode or "off", b.target or "inside")


@app.post("/api/folders/{fid}/update")
def folder_update(fid: int, b: FolderBody):
    _wrap(organizer.update_folder, fid, mode=b.mode, target=b.target)
    return {"ok": True}


@app.post("/api/folders/{fid}/remove")
def folder_remove(fid: int):
    organizer.remove_folder(fid)
    return {"ok": True}


@app.post("/api/folders/{fid}/plan")
def folder_plan(fid: int, b: FolderBody):
    return {"job": _wrap(organizer.create_plan, fid, b.remove_empty)}


@app.get("/api/jobs/{jid}")
def job_get(jid: int):
    j = organizer.job(jid)
    if not j:
        raise HTTPException(404)
    return {**j, "items": organizer.plan_items(jid) if j["status"] in ("ready", "applied", "undone") else []}


@app.post("/api/jobs/{jid}/{action}")
def job_action(jid: int, action: str):
    fn = {"apply": organizer.apply, "undo": organizer.undo, "cancel": organizer.cancel}.get(action)
    if not fn:
        raise HTTPException(404)
    _wrap(fn, jid)
    return {"ok": True}


@app.post("/api/plan/{item_id}/{action}")
def plan_item(item_id: int, action: str, b: FolderBody | None = None):
    if action == "category":
        _wrap(organizer.set_item_category, item_id, b.category if b else None)
    elif action == "rename":
        _wrap(organizer.rename_item, item_id, b.newname if b else "")
    elif action == "skip":
        organizer.skip_item(item_id)
    else:
        raise HTTPException(404)
    return {"ok": True}


# ======================= Хайлт =======================
@app.get("/api/search")
def search_files(q: str):
    from . import search
    return {"results": search.search(q, 25), "stats": search.stats()}


@app.post("/api/ask")
async def ask_files(b: CommandBody):
    from . import search
    return await _awrap(asyncio.to_thread(search.ask, b.text))


@app.post("/api/search/reindex")
async def reindex():
    from . import search
    n = await asyncio.to_thread(search.index_once, 2000)
    return {"indexed": n, **search.stats()}


# ======================= Даалгавар =======================
class TaskBody(BaseModel):
    title: str | None = None
    due: str | None = None
    date: str | None = None
    time: str | None = None
    location: str | None = None


@app.post("/api/tasks")
def task_add(b: TaskBody):
    tid = tasks.add(b.title or "Шинэ даалгавар", b.due or "")
    journal.add("task", f"Даалгавар нэмэв: {b.title}", undo={"type": "task", "id": tid, "delete": True}, who="Та")
    return {"id": tid}


@app.post("/api/tasks/{tid}/{action}")
async def task_action(tid: int, action: str, b: TaskBody | None = None):
    t = tasks.get(tid)
    if not t:
        raise HTTPException(404)
    if action == "done":
        tasks.set_status(tid, "done")
        journal.add("task", f"Хийсэн: {t['title']}", undo={"type": "task", "id": tid, "prev": "open"}, who="Та")
    elif action == "dismiss":
        tasks.set_status(tid, "dismissed")
        journal.add("task", f"Хаав: {t['title']}", undo={"type": "task", "id": tid, "prev": "open"}, who="Та")
    elif action == "update" and b:
        tasks.update(tid, title=b.title, due=b.due)
    elif action == "calendar":
        from . import calendar_write
        m = dict(t.get("track") or {})
        if b:
            m.update({k: v for k, v in {"date": b.date, "time": b.time, "title": b.title, "location": b.location}.items() if v})
        m.setdefault("date", t.get("due"))
        m.setdefault("title", t["title"].lstrip("📅 "))
        ev = await _awrap(asyncio.to_thread(calendar_write.create_event, m))
        tasks.set_status(tid, "done")
        journal.add("calendar", f"Календарьт нэмэв: {m['title']} ({m['date']} {m.get('time', '')})", undo=ev, who="Та")
        engine.STATE["calendar"] = await engine.fetch_calendar([])
    else:
        raise HTTPException(404)
    return {"ok": True}


# ======================= Өдрийн тайлан =======================
class ReportBody(BaseModel):
    ids: list[int] = []
    edits: dict = {}


@app.get("/api/dayreport")
def dayreport_get():
    from . import dayreport
    return dayreport.get() or {}


@app.post("/api/dayreport/build")
async def dayreport_build():
    return await _awrap(engine.day_report(force=True))


@app.post("/api/dayreport/add")
async def dayreport_add(b: ReportBody):
    from . import dayreport
    added = await _awrap(asyncio.to_thread(dayreport.add_items, b.ids, b.edits))
    return {"added": added}


@app.post("/api/dayreport/{iid}/skip")
def dayreport_skip(iid: int):
    from . import dayreport
    dayreport.skip_item(iid)
    return {"ok": True}


# ======================= Журнал, эрүүл мэнд, сурах, тохиргоо =======================
@app.get("/api/journal")
def journal_list(limit: int = 100):
    return {"items": journal.recent(limit)}


@app.post("/api/journal/{aid}/undo")
async def journal_undo(aid: int):
    return await _awrap(journal.undo(aid))


@app.get("/api/health")
def health_get():
    from . import desktop, telegram_bot
    return {**health.report(), "desktop": desktop.STATUS, "telegram_bot": telegram_bot.STATUS, "home": str(HOME)}


@app.get("/api/learn")
def learn_get():
    return learn.summary()


class StyleBody(BaseModel):
    text: str = ""
    kind: str | None = None


@app.post("/api/learn/style")
def learn_style(b: StyleBody):
    learn.kv_set("style_profile", b.text.strip())
    return {"ok": True}


@app.post("/api/learn/rebuild")
async def learn_rebuild():
    return {"style_profile": await _awrap(asyncio.to_thread(learn.update_style_profile))}


@app.post("/api/learn/reset")
def learn_reset(b: StyleBody):
    learn.reset(b.kind)
    return {"ok": True}


@app.post("/api/settings/demo")
def settings_demo(b: dict):
    save_config_value(["demo_mode"], bool(b.get("on")))
    return {"ok": True, "restart": True}


@app.post("/api/system/{action}")
def system_action(action: str):
    from . import desktop
    if action == "config":
        if os.name == "nt":
            os.startfile(str(HOME / "config.yaml"))
    elif action == "setup":
        desktop.run_setup()
    elif action == "folder":
        if os.name == "nt":
            os.startfile(str(HOME))
    elif action == "restart":
        import subprocess
        import sys
        from .config import python_exe
        subprocess.Popen([python_exe(), "-m", "terre", "--restart"], cwd=str(ROOT))
        LOOP.call_later(0.5, lambda: os._exit(0))
    else:
        raise HTTPException(404)
    return {"ok": True}


@app.get("/api/audio")
def audio():
    if not voice.BRIEFING_MP3.exists():
        raise HTTPException(404, "Дуу хараахан үүсээгүй")
    return FileResponse(voice.BRIEFING_MP3, media_type="audio/mpeg")
