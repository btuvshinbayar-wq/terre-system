"""FastAPI сервер: самбар + API + далд давтамжит шалгалт."""
import asyncio
import contextlib
import logging
import os
import secrets

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel

from . import brain, engine, files, health, journal, learn, organizer, store, tasks, voice
from .config import CFG, DATA, DEMO, HOME, ROOT, gemini_key, greeting, save_config_value, source_enabled

log = logging.getLogger("terre")
LOOP = None


# ======================= Нэвтрэх токен =======================
def dashboard_token():
    p = DATA / "dashboard_token"
    if not p.exists():
        p.write_text(secrets.token_urlsafe(24), encoding="utf-8")
    return p.read_text(encoding="utf-8").strip()


TOKEN = dashboard_token()
LOCKED_PAGE = """<!DOCTYPE html><html lang="mn"><meta charset="utf-8"><title>Terre System</title>
<body style="background:#050910;color:#d8e6f3;font:16px Segoe UI,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="text-align:center"><div style="font-size:12px;letter-spacing:5px;color:#38d6f5">TERRE SYSTEM</div>
<h2 style="font-weight:400">Самбарыг tray icon-оос эсвэл Эхлэх цэснээс нээнэ үү</h2>
<p style="color:#7d93ab">Аюулгүй байдлын үүднээс самбарыг зөвхөн Terre өөрөө нээж болно.</p></div></body></html>"""


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
                msg = f"{CFG.get('owner_name', '')}, яаралтай {len(urgent)} шинэ мессеж ирлээ. {urgent[0]['summary']}"
                await voice.speak(msg, path=voice.ALERT_MP3)
        except Exception:
            log.exception("Далд шалгалт амжилтгүй")


@contextlib.asynccontextmanager
async def lifespan(app):
    global LOOP
    LOOP = asyncio.get_running_loop()
    from . import telegram_bot
    if telegram_bot.start(LOOP):
        health.ok("Telegram bot", "Ажиллаж байна")
    tasks_ = [asyncio.create_task(_startup_sequence()), asyncio.create_task(_background_loop()),
              asyncio.create_task(engine.scheduler_loop())]
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
        "owner": CFG.get("owner_name", ""),
        "greeting": greeting(),
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
                  "stats": files.stats(), "categories": files.categories(), "root": files.root()},
        "folders": organizer.folders_overview(),
        "tasks": {"open": tasks.open_tasks(), "done": tasks.done_recent(8)},
        "health": health.report(),
        "has_gemini": bool(gemini_key()),
    }


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
        out.append("Файл эмхлэгч")
    if gemini_key():
        out.append("Gemini AI")
    return out


def _sm_lists():
    """Тушаалын талбарт санал болгох жагсаалт (School Manager-ийн жинхэнэ өгөгдөл + Terre-ийн эмхэлсэн файлууд)."""
    st = engine.STATE.get("sm_state") or {}
    out = {k: st.get(k, []) for k in ("teachers", "plans", "evaluations", "observations", "curriculum_teachers")}
    recent = [f.get("dest") or f.get("src") for f in files.recent(["moved"], 200)]
    recent = [p for p in recent if p]
    out["docs"] = [p for p in recent if p.lower().endswith((".docx", ".doc", ".pdf", ".xlsx", ".xls"))][:60]
    out["jsons"] = [p for p in recent if p.lower().endswith(".json")][:40]
    return out


def _commands_for_ui():
    sched = {j["command"]: j["at"] for j in (CFG.get("school_manager", {}).get("schedule") or [])}
    return [{"name": c["name"], "description": c.get("description", ""), "params": c.get("params", []),
             "group": c.get("group", ""), "schedule": sched.get(c["name"])} for c in engine.commands()]


@app.get("/api/speaking")
def speaking():
    return {"on": voice.SPEAKING["on"]}


# ======================= Мессеж =======================
class SendBody(BaseModel):
    body: str


class RedraftBody(BaseModel):
    instruction: str


@app.post("/api/items/{item_id:path}/send")
async def send(item_id: str, b: SendBody):
    try:
        await engine.send(item_id, b.body)
    except Exception as e:
        raise HTTPException(500, f"Илгээж чадсангүй: {e}")
    return {"ok": True}


@app.post("/api/items/{item_id:path}/apply")
async def apply(item_id: str):
    await _awrap(engine.apply(item_id))
    return {"ok": True}


@app.post("/api/items/{item_id:path}/dismiss")
def dismiss(item_id: str):
    _wrap(engine.dismiss, item_id)
    return {"ok": True}


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
    if not gemini_key():
        raise HTTPException(400, "Дуугаар командлахад Gemini API түлхүүр хэрэгтэй (config.yaml → gemini.api_key)")
    text = await asyncio.to_thread(brain.transcribe, audio, request.headers.get("content-type", "audio/wav"))
    if not text:
        return {"text": "", "plan": {"type": "answer", "say": "Сонсогдсонгүй. Дахин оролдоно уу."}}
    journal.add("voice", f"Дуут тушаал: «{text}»", who="Та")
    return {"text": text, "plan": await _awrap(_plan(text))}


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
    """Файлыг Windows дээр нээх / Explorer-т харуулах (зөвхөн индекслэсэн эсвэл Terre-ийн мэдэх файл)."""
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
        return {"path": await asyncio.to_thread(desktop.pick_folder)}
    except Exception as e:
        raise HTTPException(400, f"Хавтас сонгох цонх нээгдсэнгүй ({e}). Замыг гараар бичнэ үү.")


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
