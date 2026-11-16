"""Даалгавар, хугацаа, хариу хүлээлт, хурлын санал.

- Мэйл ангилах үед Gemini хугацаа ("Баасан гаригт ирүүлнэ үү"), даалгавар, хурлын урилгыг ялгана (нэмэлт дуудлагагүй).
- Terre-ээр хариу илгээх бүрт "хариу хүлээж байна" гэсэн follow-up үүснэ. Хариу ирвэл өөрөө хаагдана,
  хугацаа өнгөрвөл сануулна.
- Хурлын урилгыг календарьт нэмэх санал болгоно (таны зөвшөөрлөөр).
"""
import datetime
import json
import logging
import time

from . import files
from .config import CFG, now

log = logging.getLogger("terre.tasks")
_db, _lock = files._db, files._lock
_db.execute("""CREATE TABLE IF NOT EXISTS tasks(
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, due TEXT, kind TEXT, source_item TEXT, source_label TEXT,
    track TEXT, status TEXT, created TEXT, done_at TEXT, notified TEXT)""")
_db.commit()
_last_followup_check = 0


def _row(r):
    d = dict(r)
    d["track"] = json.loads(d["track"]) if d.get("track") else None
    if d.get("due"):
        try:
            days = (datetime.date.fromisoformat(d["due"]) - now().date()).days
            d["days_left"] = days
        except ValueError:
            d["days_left"] = None
    return d


def add(title, due="", kind="task", source_item=None, source_label="", track=None):
    with _lock:
        if source_item and _db.execute("SELECT 1 FROM tasks WHERE source_item=? AND kind=? AND title=?",
                                       (source_item, kind, title)).fetchone():
            return None
        cur = _db.execute("INSERT INTO tasks(title,due,kind,source_item,source_label,track,status,created) VALUES (?,?,?,?,?,?,?,?)",
                          (title, due or "", kind, source_item, source_label,
                           json.dumps(track, ensure_ascii=False) if track else None, "open", now().isoformat()))
        _db.commit()
        return cur.lastrowid


def get(tid):
    with _lock:
        r = _db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    return _row(r) if r else None


def set_status(tid, status):
    with _lock:
        _db.execute("UPDATE tasks SET status=?, done_at=? WHERE id=?",
                    (status, now().isoformat() if status != "open" else None, tid))
        _db.commit()


def delete(tid):
    with _lock:
        _db.execute("DELETE FROM tasks WHERE id=?", (tid,))
        _db.commit()


def update(tid, **kw):
    allowed = {k: v for k, v in kw.items() if k in ("title", "due", "track") and v is not None}
    if "track" in allowed:
        allowed["track"] = json.dumps(allowed["track"], ensure_ascii=False)
    if allowed:
        cols = ", ".join(f"{k}=?" for k in allowed)
        with _lock:
            _db.execute(f"UPDATE tasks SET {cols} WHERE id=?", (*allowed.values(), tid))
            _db.commit()


def open_tasks():
    with _lock:
        rows = _db.execute("SELECT * FROM tasks WHERE status='open' ORDER BY CASE WHEN due='' THEN 1 ELSE 0 END, due, id").fetchall()
    return [_row(r) for r in rows]


def done_recent(limit=10):
    with _lock:
        rows = _db.execute("SELECT * FROM tasks WHERE status='done' ORDER BY done_at DESC LIMIT ?", (limit,)).fetchall()
    return [_row(r) for r in rows]


def due_soon(days=1):
    out = []
    for t in open_tasks():
        if t["kind"] == "meeting":
            continue
        if t.get("days_left") is not None and t["days_left"] <= days:
            out.append(t)
    return out


def _valid_date(s):
    try:
        datetime.date.fromisoformat(s)
        return s
    except (TypeError, ValueError):
        return ""


def from_triage(item, t):
    """Ангиллын үр дүнгээс даалгавар / хурал үүсгэнэ. Шинээр үүссэн ID-уудыг буцаана."""
    created = []
    label = f"{item.get('sender', '')}: {item.get('subject', '')}"[:120]
    due = _valid_date(t.get("deadline", ""))
    title = (t.get("task") or "").strip()
    if title or due:
        tid = add(title or f"Хариу/ажил: {item.get('subject', '')}"[:150], due, "task", item["id"], label)
        if tid:
            created.append(tid)
    md = _valid_date(t.get("meeting_date", ""))
    if md:
        meeting = {"date": md, "time": (t.get("meeting_time") or "")[:5], "title": t.get("meeting_title") or item.get("subject", ""),
                   "location": t.get("meeting_location") or ""}
        tid = add(f"📅 {meeting['title']}", md, "meeting", item["id"], label, meeting)
        if tid:
            created.append(tid)
    return created


def add_followup(item, track):
    days = int((CFG.get("tasks") or {}).get("follow_up_days", 3))
    due = (now().date() + datetime.timedelta(days=days)).isoformat()
    track = {**track, "source": item["source"]}
    return add(f"Хариу хүлээж байна: {item.get('sender', '')} — {item.get('subject', '')}"[:160], due, "followup",
               item["id"], item.get("sender", ""), track)


def check_followups():
    """Хариу ирсэн follow-up-уудыг хаана (цагт нэг удаа). Хаагдсан даалгаврын жагсаалт буцаана."""
    global _last_followup_check
    if time.time() - _last_followup_check < 3600:
        return []
    _last_followup_check = time.time()
    from . import engine
    closed = []
    for t in open_tasks():
        if t["kind"] != "followup" or not t.get("track"):
            continue
        try:
            mod = engine._connector(t["track"]["source"])
            if hasattr(mod, "thread_has_reply") and mod.thread_has_reply(t["track"]):
                set_status(t["id"], "done")
                closed.append(t)
        except Exception as e:
            log.info("Follow-up шалгах алдаа %s: %s", t["id"], e)
    return closed


def demo_seed():
    if open_tasks() or done_recent(1):
        return
    d = now().date()
    add("2-р улирлын ирцийн нэгдсэн тайлан ирүүлэх", (d + datetime.timedelta(days=1)).isoformat(), "task", "demo:1",
        "Боловсролын газар")
    add("11б ангийн mock test-ийн дүнг нэгтгэх", (d + datetime.timedelta(days=4)).isoformat(), "task", "demo:5",
        "Г. Энхжаргал")
    add("Хариу хүлээж байна: Б. Сарантуяа — SAT хичээлийн талаар", (d - datetime.timedelta(days=1)).isoformat(),
        "followup", "demo:2", "Б. Сарантуяа", {"source": "gmail"})
    add("📅 ЗАН-ийн нэгдсэн хурал", (d + datetime.timedelta(days=3)).isoformat(), "meeting", "demo:8", "Д. Мөнхзул",
        {"date": (d + datetime.timedelta(days=3)).isoformat(), "time": "14:00", "title": "ЗАН-ийн нэгдсэн хурал",
         "location": "Хурлын заал"})
