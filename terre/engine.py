"""TED-ийн гол мөчлөг: эх сурвалжуудаас татах -> ангилах -> (зөвшөөрөгдсөн бол) шийдэх -> хадгалах."""
import asyncio
import collections
import inspect
import logging

from . import brain, demo, files, health, journal, learn, notify, store, tasks, voice
from .config import CFG, DEMO, now, source_enabled

log = logging.getLogger("terre.engine")
STATE = {"briefing": "", "calendar": [], "metrics": [], "errors": [], "last_run": None, "macro_log": [],
         "sm_state": None, "sm_running": False, "day_report_day": None}
MAX_TRIAGE_PER_CYCLE = 30
_cycle_lock = asyncio.Lock()


def _connector(source):
    if source == "gmail":
        from .connectors import gmail as m
    elif source == "outlook":
        from .connectors import outlook as m
    elif source == "telegram":
        from .connectors import telegram as m
    elif source == "imap":
        from .connectors import imap_mail as m
    else:
        raise RuntimeError(f"{source}-д энэ үйлдэл дэмжигдэхгүй")
    return m


async def _call(fn, *args):
    if inspect.iscoroutinefunction(fn):
        return await fn(*args)
    return await asyncio.to_thread(fn, *args)


async def _safe(label, fn, errors, default, health_name=None):
    try:
        r = await _call(fn)
        health.ok(health_name or label)
        return r
    except Exception as e:
        log.warning("%s: %s", label, e)
        errors.append(f"{label}: {e}")
        health.err(health_name or label, e)
        return default


async def fetch_messages(errors):
    if DEMO:
        return demo.messages()
    items = []
    if source_enabled("gmail"):
        from .connectors import gmail
        items += await _safe("Gmail", gmail.fetch_unread, errors, [])
    if source_enabled("outlook"):
        from .connectors import outlook
        items += await _safe("Outlook", outlook.fetch_unread, errors, [])
    from .connectors import imap_mail
    if imap_mail.accounts():
        items += await _safe("Бусад мэйл", imap_mail.fetch_unread, errors, [])
    if source_enabled("telegram"):
        from .connectors import telegram
        items += await _safe("Telegram", telegram.fetch_unread, errors, [])
    if source_enabled("google_chat"):
        from .connectors import gchat
        items += await _safe("Google Chat", gchat.fetch_recent, errors, [])
    return items


async def fetch_calendar(errors):
    if DEMO:
        return demo.calendar()
    ev = []
    if source_enabled("google_calendar"):
        from .connectors import gcal
        ev += await _safe("Google Calendar", gcal.today_events, errors, [])
    if source_enabled("outlook"):
        from .connectors import outlook
        ev += await _safe("Outlook Calendar", outlook.today_events, errors, [])
    return sorted(ev, key=lambda e: ("0" if e["time"] == "Өдөржин" else e["time"]))


async def fetch_metrics(errors):
    """School Manager-ийн төлөв + тоон үзүүлэлт."""
    if DEMO:
        # Демо горимд School Manager-ийн зохиомол өгөгдөл харуулахгүй
        STATE["sm_state"], STATE["sm_running"] = None, False
        return []
    if not sm_enabled():
        return []
    from .connectors import school_manager as sm
    state = await _safe("School Manager", sm.fetch_state, errors, None)
    STATE["sm_state"], STATE["sm_running"] = state, bool(state and state.get("running"))
    return sm.metrics_from(state)


def sm_enabled():
    return bool(CFG.get("school_manager", {}).get("enabled"))


def commands():
    from . import actions
    out = list(actions.commands())
    if DEMO or sm_enabled():
        from .connectors import school_manager as sm
        out += sm.commands()
    return out


async def _check_mail():
    await run_cycle()
    u, p = store.by_status(["urgent"], 50), store.by_status(["pending"], 50)
    say = f"Мэйл шалгалаа. Яаралтай {len(u)}, таны хариу хүлээж буй {len(p)} мессеж байна."
    if u:
        say += f" Хамгийн яаралтай нь: {u[0].get('summary', '')}"
    return {"log": [say], "say": say}


async def save_attachments(item, errors):
    if DEMO or not files.cfg().get("attachments", True) or item["source"] not in ("gmail", "outlook", "imap"):
        return 0
    try:
        got = await _call(_connector(item["source"]).download_attachments, item)
        return sum(1 for name, data in got if files.save_attachment(name, data, item.get("sender", ""), item.get("received")))
    except Exception as e:
        errors.append(f"Хавсралт ({item['source']}): {e}")
        return 0


async def run_cycle():
    """Нэг удаагийн шалгалт. Шинэ яаралтай зүйлсийн жагсаалтыг буцаана."""
    async with _cycle_lock:
        errors = []
        items = await fetch_messages(errors)
        new_urgent = []
        fresh = [i for i in items if not store.exists(i["id"])]
        bl = set(blocked())
        if bl and not DEMO:
            for it in [i for i in fresh if sender_key(i) in bl]:
                await _handle_blocked(it, errors)
            fresh = [i for i in fresh if sender_key(i) not in bl]
        fresh = fresh[:MAX_TRIAGE_PER_CYCLE]
        for it in fresh:
            t = await asyncio.to_thread(brain.triage, it)
            status = {"auto": "auto", "approve": "pending", "urgent": "urgent"}[t["category"]]
            if status == "auto" and CFG.get("auto_actions") and t["action"] != "none" and not DEMO:
                try:
                    await _call(_connector(it["source"]).apply_action, it, t["action"])
                    status = "auto_done"
                except Exception as e:
                    errors.append(f"Автомат үйлдэл ({it['source']}): {e}")
            store.insert(it, t, status)
            if status == "auto_done":
                journal.add("archive", f"{'Архивлав' if t['action'] == 'archive' else 'Уншсан болгов'}: {it.get('sender')} — {it.get('subject')}"[:200],
                            t.get("reason", ""), undo={"type": "msg_status", "item": it["id"], "prev": "auto",
                                                       "unarchive": t["action"] == "archive"})
            if status != "auto":
                await save_attachments(it, errors)
                for tid in tasks.from_triage(it, t):
                    tk = tasks.get(tid)
                    journal.add("task", f"Даалгавар үүсгэв: {tk['title']}" + (f" (хугацаа {tk['due']})" if tk.get("due") else ""),
                                tk.get("source_label", ""), undo={"type": "task", "id": tid, "delete": True})
            if status == "urgent":
                new_urgent.append({**it, **t})
        if DEMO:
            try:
                files.demo_seed()
                tasks.demo_seed()
                from . import organizer
                organizer.demo_seed()
            except Exception as e:
                log.warning("Демо өгөгдөл үүсгэж чадсангүй: %s", e)
        else:
            await _safe("Файл эмхлэгч", files.scan, errors, (0, 0))
            for t in await asyncio.to_thread(tasks.check_followups):
                journal.add("task", f"Хариу ирлээ → хаав: {t['title']}")
        from . import search
        await _safe("Файлын хайлт", lambda: search.index_once(), errors, 0)
        STATE["calendar"] = await fetch_calendar(errors)
        STATE["metrics"] = await fetch_metrics(errors)
        STATE["errors"] = errors
        STATE["last_run"] = now().isoformat()
        log.info("Мөчлөг: %d шинэ, %d яаралтай, %d алдаа", len(fresh), len(new_urgent), len(errors))
        for u in new_urgent:
            notify.urgent(u)
        return new_urgent


def _sm_brief():
    st = STATE.get("sm_state")
    if not st:
        return "School Manager-ийн өгөгдөл олдсонгүй" if sm_enabled() else None
    s = st["summary"]
    ag = st.get("agenda") or {}
    return {"absent_teachers": s["teachers"]["absent"],
            "overdue_plans_count": len(ag.get("overdue", s["plans"]["overdue"])),   # нэрийг уншихгүй, зөвхөн тоо
            "today_plans": [p["activity"] for p in ag.get("today", [])][:6],
            "upcoming_plans_7d": [f"{p['startDate']} {p['activity']}" for p in (ag.get("upcoming") or s["plans"]["upcoming"])][:6],
            "notes_this_month": s["notes"]["month"]}


async def make_briefing(speak=True):
    urgent = store.by_status(["urgent"], 5)
    pending = store.by_status(["pending"], 5)
    text = await asyncio.to_thread(
        brain.compose_briefing, STATE["calendar"],
        {**store.today_counts(), "files_today": files.stats(), "school_manager": _sm_brief(),
         "tasks_due_soon": [{"title": t["title"], "due": t["due"], "days_left": t.get("days_left")} for t in tasks.due_soon(2)][:6]},
        urgent, pending, STATE["metrics"], STATE["errors"],
    )
    STATE["briefing"] = text
    await voice.speak(text, play=speak)
    return text


# ---------- Самбараас ирэх үйлдлүүд ----------
async def send(item_id, body, who="Та"):
    item = store.get(item_id)
    if not item:
        raise KeyError(item_id)
    track = None
    if not DEMO:
        track = await _call(_connector(item["source"]).send_reply, item, body)
    learn.record_draft(item, item.get("draft") or "", body)
    store.update(item_id, status="sent", draft=body)
    journal.add("mail", f"Хариу илгээв: {item.get('sender')} — {item.get('subject')}"[:200], body[:300], who=who)
    if isinstance(track, dict) and (CFG.get("tasks") or {}).get("follow_up", True) and item["source"] in ("gmail", "outlook", "imap"):
        tasks.add_followup(item, track)


async def apply(item_id, who="Та"):
    item = store.get(item_id)
    prev = item["status"]
    if not DEMO and item["action"] and item["action"] != "none":
        res = await _call(_connector(item["source"]).apply_action, item, item["action"])
        if isinstance(res, dict) and res.get("archived_id"):
            store.update(item_id, meta=__import__("json").dumps({**item["meta"], **res}, ensure_ascii=False))
    store.update(item_id, status="auto_done")
    journal.add("archive", f"{'Архивлав' if item['action'] == 'archive' else 'Шийдэв'}: {item.get('sender')} — {item.get('subject')}"[:200],
                undo={"type": "msg_status", "item": item_id, "prev": prev, "unarchive": item["action"] == "archive"}, who=who)


def dismiss(item_id, who="Та"):
    item = store.get(item_id)
    store.update(item_id, status="dismissed")
    journal.add("mail", f"Алгасав: {item.get('sender')} — {item.get('subject')}"[:200],
                undo={"type": "msg_status", "item": item_id, "prev": item["status"]}, who=who)


# ---------- Мэйлийн нэмэлт үйлдлүүд: уншсан, устгах, блоклох ----------
class _Skip(Exception):
    pass


BLOCK_KEY = "blocked_senders"


def blocked():
    import json
    try:
        return json.loads(learn.kv_get(BLOCK_KEY, "[]")) or []
    except ValueError:
        return []


def _save_blocked(lst):
    import json
    learn.kv_set(BLOCK_KEY, json.dumps(sorted(set(lst)), ensure_ascii=False))


def sender_key(item):
    """Блоклох түлхүүр: мэйл хаяг (байхгүй бол илгээгчийн нэр)."""
    return ((item.get("meta") or {}).get("from_addr") or item.get("sender") or "").strip().lower()


def _merge_meta(item_id, item, res):
    if isinstance(res, dict) and res:
        import json
        store.update(item_id, meta=json.dumps({**item["meta"], **res}, ensure_ascii=False))


async def mark_read(item_id, who="Та"):
    item = store.get(item_id)
    if not item:
        raise KeyError(item_id)
    if not DEMO and item["source"] != "gchat":      # Google Chat-д "уншсан" тэмдэглэх API байхгүй — зөвхөн TED-д
        mod = _connector(item["source"])
        await _call(getattr(mod, "mark_read", None) or (lambda it: mod.apply_action(it, "mark_read")), item)
    store.update(item_id, status="read")
    journal.add("mail", f"Уншсан болгов: {item.get('sender')} — {item.get('subject')}"[:200],
                undo={"type": "msg_action", "item": item_id, "prev": item["status"], "revert": "mark_unread"}, who=who)


async def trash(item_id, who="Та"):
    item = store.get(item_id)
    if not item:
        raise KeyError(item_id)
    if not DEMO:
        mod = _connector(item["source"])
        if not hasattr(mod, "trash"):
            raise RuntimeError("Энэ эх сурвалжийн мессежийг устгах боломжгүй (зөвхөн мэйл)")
        _merge_meta(item_id, item, await _call(mod.trash, item))
    store.update(item_id, status="trashed")
    journal.add("mail", f"Хогийн сав руу зөөв: {item.get('sender')} — {item.get('subject')}"[:200],
                undo={"type": "msg_action", "item": item_id, "prev": item["status"], "revert": "untrash"}, who=who)


async def block(item_id, who="Та"):
    item = store.get(item_id)
    if not item:
        raise KeyError(item_id)
    key = sender_key(item)
    if not key:
        raise RuntimeError("Илгээгчийн хаяг тодорхойгүй")
    trashed = False
    if not DEMO:
        mod = _connector(item["source"]) if item["source"] != "gchat" else None
        if mod is None:
            pass
        elif hasattr(mod, "trash"):
            _merge_meta(item_id, item, await _call(mod.trash, item))
            trashed = True
        else:
            await _call(getattr(mod, "mark_read", None) or (lambda it: mod.apply_action(it, "mark_read")), item)
    _save_blocked(blocked() + [key])
    store.update(item_id, status="blocked")
    journal.add("mail", f"Блоклов: {key}"[:200],
                "Цаашид энэ илгээгчийн мэйлийг TED автоматаар хогийн сав руу зөөнө",
                undo={"type": "msg_action", "item": item_id, "prev": item["status"],
                      "revert": "untrash" if trashed else "mark_unread", "unblock": key}, who=who)
    return key


async def revert_msg_action(u):
    """journal.undo-оос дуудагдана."""
    item = store.get(u["item"])
    if item and not DEMO and u.get("revert"):
        mod = _connector(item["source"])
        fn = getattr(mod, u["revert"], None)
        if fn:
            await _call(fn, item)
    if u.get("unblock"):
        _save_blocked([b for b in blocked() if b != u["unblock"]])
    if item:
        store.update(u["item"], status=u["prev"])


async def _handle_blocked(it, errors):
    """Блоклосон илгээгчийн шинэ мэйл: Gemini-д илгээхгүй (токен хэмнэнэ), хогийн сав руу зөөнө."""
    try:
        if it["source"] == "gchat":
            raise _Skip()
        mod = _connector(it["source"])
        if hasattr(mod, "trash"):
            res = await _call(mod.trash, it)
            if isinstance(res, dict):
                it["meta"] = {**it.get("meta", {}), **res}
        else:
            await _call(getattr(mod, "mark_read", None) or (lambda x: mod.apply_action(x, "mark_read")), it)
    except _Skip:
        pass
    except Exception as e:
        errors.append(f"Блоклосон мэйл ({it['source']}): {e}")
        return
    store.insert(it, {"category": "auto", "summary": f"{it.get('sender')}: {it.get('subject')}", "reason": "Блоклосон илгээгч",
                      "action": "none", "draft": ""}, "blocked")
    journal.add("mail", f"Блоклосон илгээгчийн мэйлийг хогийн сав руу зөөв: {it.get('sender')} — {it.get('subject')}"[:200],
                who="TED", undo={"type": "msg_action", "item": it["id"], "prev": "auto", "revert": "untrash"})


async def sm_plan_status(plan_id, status="биелсэн", who="Та"):
    """School Manager-ийн төлөвлөгөөний төлөвийг id-аар солино (самбарын «Яаралтай» хэсгээс)."""
    from .connectors import school_manager as sm
    if not sm.is_running():
        await asyncio.to_thread(sm.start)
    r = await asyncio.to_thread(sm.call, "set_plan_status", {"id": plan_id, "status": status})
    undo = (r or {}).pop("undo", None)
    journal.add("sm", f"School Manager: «{(r or {}).get('activity', '')}» → {status}"[:200], who=who,
                undo={"type": "sm", "action": undo["action"], "params": undo["params"]} if undo else None)
    try:   # самбарын жагсаалтыг шууд шинэчилнэ
        STATE["sm_state"] = await asyncio.to_thread(sm.fetch_state)
    except Exception:
        pass
    return r


def promote(item_id, draft):
    item = store.get(item_id)
    learn.record_triage(item, "хариу шаардлагатай (эзэн зассан)")
    store.update(item_id, status="pending", draft=draft)
    journal.add("learn", f"Ангилал засав → хариу бичих: {item.get('subject')}"[:200],
                "TED дараа ижил төрлийн мэйлийг ингэж ангилна", undo={"type": "msg_status", "item": item_id, "prev": item["status"]})


# ---------- School Manager тушаал ----------
async def run_command(name, params, who="Та"):
    entry = {"time": now().strftime("%H:%M"), "macro": name, "params": params, "who": who}
    try:
        from . import actions
        if name in actions.NAMES:
            if name == "Мэйл шалгах":
                r = await _check_mail()
            elif DEMO:
                r = {"log": [f"✓ {name} (демо: жинхэнэ үйлдэл хийгээгүй)"]}
            else:
                r = await asyncio.to_thread(actions.run, name, params, files.root())
            entry["log"], entry["say"] = r["log"], r.get("say", "")
            if r.get("file"):
                files.register_generated(r["file"], "Google Drive")
            if name != "Мэйл шалгах":
                journal.add("system", name, " ".join(r["log"])[:300], undo=r.get("undo"), who=who)
        elif DEMO:
            await asyncio.sleep(1.2)
            shown = ", ".join(f"{k}: {v}" for k, v in params.items() if v) or "параметргүй"
            entry["log"] = [f"→ School Manager: {name} ({shown})", "✓ Амжилттай (демо: жинхэнэ өгөгдөлд хүрээгүй)"]
            journal.add("sm", f"School Manager: {name}", shown, who=who)
        else:
            from .connectors import school_manager as sm
            r = await asyncio.to_thread(sm.run_command, name, params, files.root())
            entry["log"] = r["log"]
            if r.get("file"):
                files.register_generated(r["file"], "School Manager")
            journal.add("sm", f"School Manager: {name}", " ".join(entry["log"])[:300], undo=r.get("undo"), who=who)
        entry["ok"] = True
    except Exception as e:
        entry.update(ok=False, log=[str(e)])
    STATE["macro_log"] = ([entry] + STATE["macro_log"])[:20]
    if entry["ok"] and not DEMO:
        errs = []
        STATE["metrics"] = await fetch_metrics(errs)
    return entry


async def start_school_manager():
    if DEMO:
        return {"ok": True}
    from .connectors import school_manager as sm
    await asyncio.to_thread(sm.start)
    STATE["metrics"] = await fetch_metrics([])
    return {"ok": True}


async def day_report(force=False):
    from . import dayreport
    rep = await asyncio.to_thread(dayreport.build, STATE["calendar"])
    STATE["day_report_day"] = rep["date"]
    if not force:
        notify.day_report(rep)
    return rep


async def scheduler_loop():
    """Хуваарьт ажлууд: өдрийн тайлан, даалгаврын сануулга, School Manager-ийн тушаалууд."""
    from . import dayreport
    done = set()
    while True:
        await asyncio.sleep(30)
        try:
            if dayreport.due_now(STATE.get("day_report_day")) and not (dayreport.get() or {}).get("items"):
                await day_report()
            elif dayreport.due_now(STATE.get("day_report_day")):
                STATE["day_report_day"] = now().strftime("%Y-%m-%d")
            hm, day = now().strftime("%H:%M"), now().strftime("%Y-%m-%d")
            remind_at = (CFG.get("tasks") or {}).get("remind_at", "08:30")
            if hm == remind_at and (day, "remind") not in done:
                done.add((day, "remind"))
                soon = tasks.due_soon(1)
                if soon:
                    notify.tasks_due(soon)
        except Exception:
            log.exception("Хуваарьт ажил алдаа")
        if DEMO or not sm_enabled():
            continue
        hm, day = now().strftime("%H:%M"), now().strftime("%Y-%m-%d")
        for job in CFG.get("school_manager", {}).get("schedule") or []:
            if job.get("at") == hm and (day, job["command"]) not in done:
                done.add((day, job["command"]))
                log.info("Хуваарьт тушаал: %s", job["command"])
                await run_command(job["command"], job.get("params", {}), who="Хуваарь")
