"""Өдрийн төгсгөлийн тайлан: өнөөдрийн мэйл, хурал, хийсэн ажлаас School Manager-ийн ажлын тэмдэглэлийн
ноорог бэлдэнэ. Та сонгосныг нь л School Manager-т оруулна."""
import json
import logging

from . import journal, learn, store, tasks
from .config import CFG, DEMO, gemini_key, now

log = logging.getLogger("terre.dayreport")
CATS = ["бүртгэл", "хурал цуглаан", "уулзалт", "зөвлөн туслах", "цахим систем", "сургалт",
        "хөтөлбөр хэрэгжүүлэх", "өөрийн хөгжил", "тодорхойлолт", "шилжилт хөдөлгөөн", "амжилт", "бусад"]


def _key(day=None):
    return "day_report:" + (day or now().strftime("%Y-%m-%d"))


def get(day=None):
    raw = learn.kv_get(_key(day))
    return json.loads(raw) if raw else None


def _save(rep):
    learn.kv_set(_key(rep["date"]), json.dumps(rep, ensure_ascii=False))


def gather(calendar):
    day = now().strftime("%Y-%m-%d")
    sent = [i for i in store.by_status(["sent"], 100) if (i.get("updated") or "").startswith(day)]
    acts = journal.today()
    done = [t for t in tasks.done_recent(50) if (t.get("done_at") or "").startswith(day)]
    return {
        "date": day,
        "calendar": calendar,
        "sent_replies": [{"to": i["sender"], "subject": i["subject"], "summary": i.get("summary")} for i in sent],
        "activities": [{"time": a["ts"][11:16], "kind": a["kind"], "title": a["title"]} for a in reversed(acts)
                       if a["kind"] not in ("system", "learn")][:60],
        "tasks_done": [t["title"] for t in done],
    }


def _heuristic(data):
    out = []
    for e in data["calendar"]:
        if e.get("time") and e["time"] != "Өдөржин":
            t = e["title"].lower()
            cat = "хурал цуглаан" if "хурал" in t else "уулзалт" if "уулзалт" in t else "сургалт" if ("сургалт" in t or "анги" in t) else "бусад"
            out.append({"title": e["title"], "category": cat, "hours": 1, "participants": 0, "result": "", "time": e["time"]})
    if data["sent_replies"]:
        out.append({"title": f"Албан бичиг, мэйлд хариу өгсөн ({len(data['sent_replies'])})", "category": "бүртгэл",
                    "hours": 0.5, "participants": 0, "result": "; ".join(s["subject"] for s in data["sent_replies"][:5])})
    sm = [a for a in data["activities"] if a["kind"] == "sm"]
    if sm:
        out.append({"title": "School Manager-т бүртгэл хийсэн", "category": "цахим систем", "hours": 0.5, "participants": 0,
                    "result": "; ".join(a["title"] for a in sm[:5])})
    return out


def build(calendar):
    data = gather(calendar)
    if gemini_key():
        from . import brain
        prompt = f"""Чи сургалтын менежерийн туслах TED. Доорх өнөөдрийн өгөгдлөөс School Manager-ийн "ажлын тэмдэглэл"-д
оруулах 3-8 бичлэгийн НООРОГ бэлд. Ижил төрлийн жижиг ажлыг нэгтгэ. Зөвхөн өгөгдөлд байгааг бич, зохиохгүй.
JSON массив буцаа: [{{"title": "юу хийсэн (товч)", "category": "{'|'.join(CATS)}-ийн нэг", "hours": тоо,
"participants": тоо (мэдэхгүй бол 0), "result": "үр дүн, дүгнэлт 1 өгүүлбэр", "time": "HH:MM эсвэл \\"\\""}}]

Өгөгдөл: {json.dumps(data, ensure_ascii=False)}"""
        try:
            items = json.loads(brain._gen(brain._model(), prompt, response_mime_type="application/json", temperature=0.3).text)
        except Exception as e:
            log.warning("Өдрийн тайлан Gemini алдаа: %s", e)
            items = _heuristic(data)
    else:
        items = _heuristic(data)
    clean = []
    for i, it in enumerate(items[:10]):
        cat = it.get("category") if it.get("category") in CATS else "бусад"
        clean.append({"id": i, "title": str(it.get("title", ""))[:200], "category": cat, "hours": float(it.get("hours") or 1),
                      "participants": int(it.get("participants") or 0), "result": str(it.get("result", ""))[:400],
                      "time": str(it.get("time") or "")[:5], "status": "pending"})
    rep = {"date": data["date"], "created": now().strftime("%H:%M"), "items": clean,
           "stats": {"sent": len(data["sent_replies"]), "activities": len(data["activities"]), "tasks_done": len(data["tasks_done"]),
                     "events": len(calendar)}}
    _save(rep)
    return rep


def add_items(ids, edits=None):
    """Сонгосон бичлэгүүдийг School Manager-т тэмдэглэл болгон оруулна."""
    rep = get()
    if not rep:
        raise ValueError("Өнөөдрийн тайлан хараахан бэлдээгүй")
    edits = edits or {}
    from .connectors import school_manager as sm
    added = []
    for it in rep["items"]:
        if it["id"] not in ids or it["status"] != "pending":
            continue
        it.update({k: v for k, v in (edits.get(str(it["id"])) or {}).items() if k in ("title", "category", "hours", "result")})
        params = {"title": it["title"], "category": it["category"], "hours": it["hours"], "participants": it["participants"],
                  "result": it["result"], "date": rep["date"]}
        if it.get("time"):
            params["startTime"] = it["time"]
        if DEMO:
            r = {"id": f"note_demo{it['id']}"}
        else:
            r = sm.call("add_note", params)
        it["status"] = "added"
        it["note_id"] = r.get("id")
        journal.add("report", f"Өдрийн тайлан → тэмдэглэл: {it['title']}", it["category"],
                    undo=None if DEMO else {"type": "sm", "action": "remove_terre_note", "params": {"id": r.get("id")}}, who="Та")
        added.append(it["title"])
    _save(rep)
    return added


def skip_item(iid):
    rep = get()
    for it in rep["items"]:
        if it["id"] == iid:
            it["status"] = "skipped"
    _save(rep)


def due_now(last_run_day):
    """config day_report.at цаг болсон бөгөөд өнөөдөр хараахан бэлдээгүй бол True."""
    cfg = CFG.get("day_report") or {}
    if not cfg.get("enabled", True):
        return False
    at = cfg.get("at", "17:00")
    n = now()
    return n.strftime("%H:%M") >= at and last_run_day != n.strftime("%Y-%m-%d") and n.weekday() < (7 if cfg.get("weekends") else 5)
