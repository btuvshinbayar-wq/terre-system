"""SQLite санах ой: ирсэн мессеж бүр, түүний ангилал, ноорог, төлөв."""
import json
import sqlite3
import threading

from .config import DATA, now

_lock = threading.Lock()
_db = sqlite3.connect(DATA / "terre.db", check_same_thread=False)
_db.row_factory = sqlite3.Row
_db.execute(
    """CREATE TABLE IF NOT EXISTS items(
        id TEXT PRIMARY KEY, source TEXT, sender TEXT, subject TEXT,
        snippet TEXT, body TEXT, received TEXT,
        category TEXT, summary TEXT, reason TEXT, action TEXT, draft TEXT,
        status TEXT, meta TEXT, created TEXT, updated TEXT)"""
)
_db.commit()

# Төлөвүүд:
#   urgent    - яаралтай, таны анхаарал хэрэгтэй
#   pending   - хариу шаардлагатай, ноорог бэлэн, таны зөвшөөрлийг хүлээж байна
#   auto      - Terre "чухал биш" гэж ангилсан (санал болгосон үйлдэл хийгдээгүй)
#   auto_done - Terre өөрөө шийдсэн (архивласан / уншсан болгосон)
#   sent      - хариу илгээгдсэн
#   dismissed - та алгассан


def _row(r):
    d = dict(r)
    d["meta"] = json.loads(d.get("meta") or "{}")
    return d


def exists(item_id):
    with _lock:
        return _db.execute("SELECT 1 FROM items WHERE id=?", (item_id,)).fetchone() is not None


def insert(item, triage, status):
    ts = now().isoformat()
    with _lock:
        _db.execute(
            "INSERT OR IGNORE INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                item["id"], item["source"], item.get("sender", ""), item.get("subject", ""),
                item.get("snippet", ""), item.get("body", ""), item.get("received", ""),
                triage.get("category"), triage.get("summary"), triage.get("reason"),
                triage.get("action"), triage.get("draft"), status,
                json.dumps(item.get("meta", {}), ensure_ascii=False), ts, ts,
            ),
        )
        _db.commit()


def get(item_id):
    with _lock:
        r = _db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    return _row(r) if r else None


def update(item_id, **fields):
    fields["updated"] = now().isoformat()
    cols = ", ".join(f"{k}=?" for k in fields)
    with _lock:
        _db.execute(f"UPDATE items SET {cols} WHERE id=?", (*fields.values(), item_id))
        _db.commit()


def by_status(statuses, limit=50):
    q = ",".join("?" * len(statuses))
    with _lock:
        rows = _db.execute(
            f"SELECT * FROM items WHERE status IN ({q}) ORDER BY received DESC LIMIT ?",
            (*statuses, limit),
        ).fetchall()
    return [_row(r) for r in rows]


def today_counts():
    start = now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    with _lock:
        rows = _db.execute(
            "SELECT status, COUNT(*) n FROM items WHERE created>=? GROUP BY status", (start,)
        ).fetchall()
    c = {r["status"]: r["n"] for r in rows}
    # Хүлээгдэж буй (хуучин ч гэсэн) асуудлууд
    with _lock:
        open_rows = _db.execute(
            "SELECT status, COUNT(*) n FROM items WHERE status IN ('urgent','pending') GROUP BY status"
        ).fetchall()
    for r in open_rows:
        c["open_" + r["status"]] = r["n"]
    return c
