"""Үйлдлийн журнал: TED-ийн хийсэн бүх зүйл, мөр бүрийг буцаах боломжтой."""
import asyncio
import json
import logging

from . import files
from .config import now

log = logging.getLogger("terre.journal")
_db, _lock = files._db, files._lock
_db.execute("""CREATE TABLE IF NOT EXISTS activity(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, icon TEXT, title TEXT, detail TEXT,
    undo TEXT, status TEXT, who TEXT)""")
_db.commit()

ICONS = {"mail": "✉", "archive": "🗄", "file": "🗂", "folder": "📁", "sm": "⚙", "task": "✅", "calendar": "📅",
         "report": "📝", "voice": "🎙", "telegram": "📱", "learn": "🧠", "system": "🔧"}


def add(kind, title, detail="", undo=None, who="TED"):
    """undo: {"type": ..., ...} эсвэл None (буцаах боломжгүй)."""
    with _lock:
        cur = _db.execute("INSERT INTO activity(ts,kind,icon,title,detail,undo,status,who) VALUES (?,?,?,?,?,?,?,?)",
                          (now().isoformat(timespec="seconds"), kind, ICONS.get(kind, "•"), title, detail,
                           json.dumps(undo, ensure_ascii=False) if undo else None, "done", who))
        _db.commit()
        return cur.lastrowid


def recent(limit=80, day=None):
    q, args = "SELECT * FROM activity", []
    if day:
        q += " WHERE ts LIKE ?"
        args.append(day + "%")
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with _lock:
        rows = [dict(r) for r in _db.execute(q, args).fetchall()]
    for r in rows:
        r["can_undo"] = bool(r["undo"]) and r["status"] == "done"
        r.pop("undo", None)
    return rows


def today():
    return recent(500, now().strftime("%Y-%m-%d"))


def _set(aid, status):
    with _lock:
        _db.execute("UPDATE activity SET status=? WHERE id=?", (status, aid))
        _db.commit()


async def undo(aid):
    with _lock:
        r = _db.execute("SELECT * FROM activity WHERE id=?", (aid,)).fetchone()
    if not r or not r["undo"] or r["status"] != "done":
        raise ValueError("Энэ үйлдлийг буцаах боломжгүй")
    u = json.loads(r["undo"])
    t = u["type"]
    from . import engine, organizer, store, tasks
    if t == "file":
        await asyncio.to_thread(files.undo, u["id"])
    elif t == "org_job":
        await asyncio.to_thread(organizer.undo, u["id"])
    elif t == "msg_status":
        item = store.get(u["item"])
        if u.get("unarchive") and item:
            mod = engine._connector(item["source"])
            if hasattr(mod, "unarchive"):
                await engine._call(mod.unarchive, item)
        store.update(u["item"], status=u["prev"])
    elif t == "msg_action":
        await engine.revert_msg_action(u)
    elif t == "sm":
        from .connectors import school_manager as sm
        await asyncio.to_thread(sm.call, u["action"], u["params"])
    elif t == "task":
        tasks.delete(u["id"]) if u.get("delete") else tasks.set_status(u["id"], u.get("prev", "open"))
    elif t == "calendar":
        from . import calendar_write
        await asyncio.to_thread(calendar_write.delete_event, u)
    else:
        raise ValueError(f"Үл мэдэх буцаалт: {t}")
    _set(aid, "undone")
    add("system", f"Буцаалаа: {r['title']}", who="Та")
    return {"ok": True}
