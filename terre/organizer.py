"""Хавтас цэгцлэгч: компьютер дээрх дурын хавтсыг холбож, доторх бүх файлыг (дэд хавтас оруулаад)
агуулгаар нь ангилж цэгцэлнэ.

Ажиллах дараалал:  холбох → ТӨЛӨВЛӨГӨӨ гаргах (юу хаашаа очихыг харуулна, юу ч хөдлөхгүй)
                    → та зөвшөөрвөл ХЭРЭГЖҮҮЛЭХ → хүсвэл бүгдийг нэг товчоор БУЦААХ.

Аюулгүй байдал:
- Файл хэзээ ч устгахгүй. Давхардсан файлыг "_Давхардсан" хавтас руу зөөнө.
- Програмын код (.git, package.json, node_modules...) агуулсан хавтсанд огт хүрэхгүй.
- Windows, Program Files, AppData, дискний үндэс (C:\\) зэрэг системийн хавтсыг холбохыг хориглоно.
- Хоосон хавтсыг зөвхөн та сонгосон үед, бүрэн хоосон бол л устгана (буцаахад дахин үүснэ).
"""
import hashlib
import json
import logging
import os
import shutil
import threading
import time

from . import brain, files
from .config import DATA, now

log = logging.getLogger("terre.organizer")
_db, _lock = files._db, files._lock
_db.execute("""CREATE TABLE IF NOT EXISTS jobs(
    id INTEGER PRIMARY KEY AUTOINCREMENT, folder_id INTEGER, path TEXT, status TEXT, options TEXT,
    progress TEXT, summary TEXT, created TEXT)""")
_db.execute("""CREATE TABLE IF NOT EXISTS plan(
    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER, kind TEXT, src TEXT, dest TEXT, category TEXT,
    reason TEXT, status TEXT, error TEXT)""")
_db.commit()
# job.status: planning | ready | applying | applied | undoing | undone | cancelled | failed
# plan.kind:  move | dup | rmdir        plan.status: planned | done | undone | error | skipped

DUP_DIR = "_Давхардсан"
PROJECT_MARKERS = {".git", ".svn", ".hg", "package.json", "node_modules", ".venv", "venv", "pyproject.toml",
                   "requirements.txt", ".sln", "pom.xml", "build.gradle", "Cargo.toml", "go.mod", ".idea", ".vscode"}
SKIP_DIRS = {"$recycle.bin", "system volume information", "__pycache__", ".cache", ".tmp", "appdata"}
TEXT_EXT = {".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".csv", ".md"}
MAX_FILES = 5000
PROGRESS = {}          # job_id -> {"stage", "done", "total"} (самбарт 1 сек тутам)


# ======================= Холбох =======================
def _forbidden(path):
    p = os.path.normcase(os.path.abspath(path))
    if os.path.dirname(p) == p:                       # C:\ гэх мэт дискний үндэс
        return "Дискний үндсийг бүхэлд нь холбох боломжгүй"
    home = os.path.normcase(os.path.expanduser("~"))
    if p == home:
        return "Хэрэглэгчийн үндсэн хавтсыг бүхэлд нь холбох боломжгүй (Documents, Desktop гэх мэт дэд хавтсыг сонгоно уу)"
    bad = [os.environ.get(k, "") for k in ("WINDIR", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA", "APPDATA", "LOCALAPPDATA")]
    bad.append(str(DATA.parent))                      # TED өөрөө
    for b in filter(None, bad):
        b = os.path.normcase(os.path.abspath(b))
        if p == b or p.startswith(b + os.sep):
            return f"Системийн/програмын хавтсанд хүрэхгүй: {b}"
    if _is_project(path):
        return "Энэ хавтас програмын код агуулж байна (.git, package.json…) — цэгцлэвэл эвдэрнэ"
    return None


def _is_project(d):
    try:
        names = set(os.listdir(d))
    except OSError:
        return False
    return bool(names & PROJECT_MARKERS) or any(n.endswith((".sln", ".csproj")) for n in names)


def add_folder(path, mode="off", target="inside", recursive=True):
    path = os.path.normpath(os.path.expandvars(os.path.expanduser(path.strip().strip('"'))))
    if not os.path.isdir(path):
        raise ValueError(f"Хавтас олдсонгүй: {path}")
    why = _forbidden(path)
    if why:
        raise ValueError(why)
    with _lock:
        _db.execute("INSERT OR IGNORE INTO folders(path,mode,recursive,target,created) VALUES (?,?,?,?,?)",
                    (path, mode, int(recursive), target, now().isoformat()))
        _db.commit()
        return dict(_db.execute("SELECT * FROM folders WHERE path=?", (path,)).fetchone())


def update_folder(fid, **kw):
    allowed = {k: v for k, v in kw.items() if k in ("mode", "target", "recursive") and v is not None}
    if not allowed:
        return
    cols = ", ".join(f"{k}=?" for k in allowed)
    with _lock:
        _db.execute(f"UPDATE folders SET {cols} WHERE id=?", (*allowed.values(), fid))
        _db.commit()


def remove_folder(fid):
    """Зөвхөн холболтыг салгана, файлд хүрэхгүй."""
    with _lock:
        _db.execute("DELETE FROM folders WHERE id=?", (fid,))
        _db.commit()


def folder(fid):
    with _lock:
        r = _db.execute("SELECT * FROM folders WHERE id=?", (fid,)).fetchone()
    return dict(r) if r else None


def pick_folder_dialog():
    from . import desktop
    return desktop.pick_folder()


# ======================= Төлөвлөгөө гаргах =======================
def _job_set(jid, **kw):
    for k in ("options", "progress", "summary"):
        if k in kw and not isinstance(kw[k], str):
            kw[k] = json.dumps(kw[k], ensure_ascii=False)
    cols = ", ".join(f"{k}=?" for k in kw)
    with _lock:
        _db.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*kw.values(), jid))
        _db.commit()


def job(jid):
    with _lock:
        r = _db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    for k in ("options", "progress", "summary"):
        d[k] = json.loads(d[k]) if d.get(k) else None
    d["live"] = PROGRESS.get(jid)
    return d


def jobs_for(fid, limit=3):
    with _lock:
        ids = [r[0] for r in _db.execute("SELECT id FROM jobs WHERE folder_id=? ORDER BY id DESC LIMIT ?", (fid, limit))]
    return [job(i) for i in ids]


def plan_items(jid, limit=400):
    with _lock:
        rows = _db.execute("SELECT * FROM plan WHERE job_id=? ORDER BY kind, category, src LIMIT ?", (jid, limit)).fetchall()
    return [dict(r) for r in rows]


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _walk(base, recursive, cats, target):
    """(файлууд, алгассан төслүүд, бүх хавтсууд)"""
    out, projects, dirs = [], [], []
    for dp, dn, fn in os.walk(base):
        keep = []
        for d in dn:
            full = os.path.join(dp, d)
            if d.startswith((".", "~", "$")) or d.lower() in SKIP_DIRS or d == DUP_DIR:
                continue
            if target == "inside" and dp == base and d in cats:
                continue                                   # аль хэдийн цэгцэлсэн ангиллын хавтас
            if _is_project(full):
                projects.append(full)
                continue
            keep.append(d)
        dn[:] = keep if recursive else []
        if dp != base:
            dirs.append(dp)
        for f in fn:
            if f.startswith(("~$", ".")) or f.lower() in ("desktop.ini", "thumbs.db"):
                continue
            if os.path.splitext(f)[1].lower() in files.SKIP_EXT:
                continue
            out.append(os.path.join(dp, f))
            if len(out) >= MAX_FILES:
                return out, projects, dirs
    return out, projects, dirs


def create_plan(fid, remove_empty=False):
    f = folder(fid)
    if not f:
        raise KeyError(fid)
    with _lock:
        cur = _db.execute("INSERT INTO jobs(folder_id,path,status,options,created) VALUES (?,?,?,?,?)",
                          (fid, f["path"], "planning", json.dumps({"remove_empty": remove_empty}), now().isoformat()))
        _db.commit()
        jid = cur.lastrowid
    threading.Thread(target=_plan_worker, args=(jid, f, remove_empty), daemon=True).start()
    return jid


def _plan_worker(jid, f, remove_empty):
    try:
        _build_plan(jid, f, remove_empty)
    except Exception as e:
        log.exception("Төлөвлөгөө гаргахад алдаа")
        _job_set(jid, status="failed", summary={"error": str(e)})
    finally:
        PROGRESS.pop(jid, None)


def _build_plan(jid, f, remove_empty):
    base, target, cats = f["path"], f["target"] or "inside", files.categories()
    dest_base = base if target == "inside" else files.root()
    PROGRESS[jid] = {"stage": "Файлуудыг тоолж байна", "done": 0, "total": 0}
    paths, projects, dirs = _walk(base, bool(f["recursive"]), cats, target)
    rows = []

    # 1) Давхардсан файл (хэмжээ ижил → SHA1 ижил)
    PROGRESS[jid] = {"stage": "Давхардсан файл хайж байна", "done": 0, "total": len(paths)}
    by_size = {}
    for p in paths:
        try:
            by_size.setdefault(os.path.getsize(p), []).append(p)
        except OSError:
            pass
    dups, dup_bytes = set(), 0
    for size, group in by_size.items():
        if len(group) < 2 or size == 0 or size > 500_000_000:
            continue
        by_hash = {}
        for p in group:
            try:
                by_hash.setdefault(_sha1(p), []).append(p)
            except OSError:
                pass
        for same in by_hash.values():
            if len(same) < 2:
                continue
            same.sort(key=lambda p: (os.path.getmtime(p), len(p)))   # хамгийн хуучныг үлдээнэ
            for p in same[1:]:
                dups.add(p)
                dup_bytes += size
                rows.append(("dup", p, os.path.join(base, DUP_DIR, os.path.basename(p)), DUP_DIR,
                             f"«{os.path.relpath(same[0], base)}»-тэй яг ижил"))

    # 2) Агуулгаар ангилах
    todo = [p for p in paths if p not in dups]
    PROGRESS[jid] = {"stage": "Агуулгаар ангилж байна", "done": 0, "total": len(todo)}
    for k in range(0, len(todo), 20):
        chunk = todo[k:k + 20]
        entries = []
        for i, p in enumerate(chunk):
            ext = os.path.splitext(p)[1].lower()
            entries.append({"i": i, "name": os.path.basename(p), "ext": ext,
                            "text": files.extract_text(p, 600) if ext in TEXT_EXT else ""})
        res = brain.classify_files_batch(entries, cats)
        for i, p in enumerate(chunk):
            c = res.get(i) or {"category": cats[-1], "reason": ""}
            dest_dir = os.path.join(dest_base, c["category"])
            newname = files.final_name(p, c["category"], c.get("name"))
            if os.path.normcase(os.path.dirname(p)) == os.path.normcase(dest_dir) and newname == os.path.basename(p):
                continue
            rows.append(("move", p, os.path.join(dest_dir, newname), c["category"], c["reason"]))
        PROGRESS[jid]["done"] = min(len(todo), k + 20)

    # 3) Цэгцэлсний дараа хоосрох хавтсууд
    if remove_empty:
        moving = {os.path.normcase(r[1]) for r in rows}
        for d in sorted(dirs, key=len, reverse=True):
            try:
                left = [n for n in os.listdir(d)
                        if os.path.normcase(os.path.join(d, n)) not in moving and n.lower() not in ("desktop.ini", "thumbs.db")]
            except OSError:
                continue
            left = [n for n in left if not (os.path.isdir(os.path.join(d, n)) and
                                            any(r[0] == "rmdir" and os.path.normcase(r[1]) == os.path.normcase(os.path.join(d, n)) for r in rows))]
            if not left:
                rows.append(("rmdir", d, "", "", "Цэгцэлсний дараа хоосорно"))

    with _lock:
        _db.executemany("INSERT INTO plan(job_id,kind,src,dest,category,reason,status) VALUES (?,?,?,?,?,?,'planned')",
                        [(jid, *r) for r in rows])
        _db.commit()
    by_cat = {}
    for r in rows:
        if r[0] == "move":
            by_cat[r[3]] = by_cat.get(r[3], 0) + 1
    summary = {"scanned": len(paths), "moves": sum(1 for r in rows if r[0] == "move"), "by_category": by_cat,
               "renames": sum(1 for r in rows if r[0] == "move" and os.path.basename(r[2]) != os.path.basename(r[1])),
               "dups": len(dups), "dup_mb": round(dup_bytes / 1e6, 1), "rmdirs": sum(1 for r in rows if r[0] == "rmdir"),
               "projects_skipped": [os.path.relpath(p, base) for p in projects][:20],
               "truncated": len(paths) >= MAX_FILES, "dest_base": dest_base}
    _job_set(jid, status="ready", summary=summary)


# ======================= Хэрэгжүүлэх / буцаах =======================
def set_item_category(item_id, category):
    with _lock:
        r = _db.execute("SELECT p.*, j.status js FROM plan p JOIN jobs j ON j.id=p.job_id WHERE p.id=?", (item_id,)).fetchone()
        if not r or r["kind"] != "move" or r["js"] != "ready":
            raise ValueError("Өөрчлөх боломжгүй")
        dest = os.path.join(os.path.dirname(os.path.dirname(r["dest"])), category, os.path.basename(r["dest"]))
        _db.execute("UPDATE plan SET category=?, dest=? WHERE id=?", (category, dest, item_id))
        _db.commit()
    from . import learn
    learn.record_file(os.path.basename(r["src"]), "", category)


def rename_item(item_id, newname):
    nn = files.clean_name(newname)
    if not nn:
        raise ValueError("Нэр хоосон байна")
    with _lock:
        r = _db.execute("SELECT p.*, j.status js FROM plan p JOIN jobs j ON j.id=p.job_id WHERE p.id=?", (item_id,)).fetchone()
        if not r or r["kind"] != "move" or r["js"] != "ready":
            raise ValueError("Өөрчлөх боломжгүй")
        ext = os.path.splitext(r["src"])[1].lower()
        if not nn.lower().endswith(ext):
            nn += ext
        _db.execute("UPDATE plan SET dest=? WHERE id=?", (os.path.join(os.path.dirname(r["dest"]), nn), item_id))
        _db.commit()


def skip_item(item_id):
    with _lock:
        _db.execute("UPDATE plan SET status='skipped' WHERE id=? AND status='planned'", (item_id,))
        _db.commit()


def apply(jid):
    j = job(jid)
    if not j or j["status"] != "ready":
        raise ValueError("Хэрэгжүүлэх төлөвлөгөө биш")
    _job_set(jid, status="applying")
    threading.Thread(target=_apply_worker, args=(jid,), daemon=True).start()


def _apply_worker(jid):
    with _lock:
        rows = [dict(r) for r in _db.execute(
            "SELECT * FROM plan WHERE job_id=? AND status='planned' ORDER BY CASE kind WHEN 'rmdir' THEN 1 ELSE 0 END, id", (jid,))]
    PROGRESS[jid] = {"stage": "Зөөж байна", "done": 0, "total": len(rows)}
    ok = err = 0
    for n, r in enumerate(rows, 1):
        try:
            if r["kind"] == "rmdir":
                os.rmdir(r["src"])            # зөвхөн хоосон бол амжилттай
                dest = ""
            else:
                if not os.path.exists(r["src"]):
                    raise FileNotFoundError("файл байхгүй болсон")
                dest = files._unique(r["dest"])
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.move(r["src"], dest)
            with _lock:
                _db.execute("UPDATE plan SET status='done', dest=? WHERE id=?", (dest or r["dest"], r["id"]))
            ok += 1
        except Exception as e:
            with _lock:
                _db.execute("UPDATE plan SET status='error', error=? WHERE id=?", (str(e)[:200], r["id"]))
            err += 1
        if n % 25 == 0:
            with _lock:
                _db.commit()
        PROGRESS[jid]["done"] = n
    with _lock:
        _db.commit()
    s = job(jid)["summary"] or {}
    s.update(applied=ok, errors=err, applied_at=now().strftime("%Y-%m-%d %H:%M"))
    _job_set(jid, status="applied", summary=s)
    from . import journal
    journal.add("folder", f"Хавтас цэгцлэв: {os.path.basename(job(jid)['path'])} — {ok} файл", job(jid)["path"],
                undo={"type": "org_job", "id": jid}, who="Та")
    PROGRESS.pop(jid, None)


def undo(jid):
    j = job(jid)
    if not j or j["status"] != "applied":
        raise ValueError("Буцаах боломжгүй")
    _job_set(jid, status="undoing")
    threading.Thread(target=_undo_worker, args=(jid,), daemon=True).start()


def _undo_worker(jid):
    with _lock:
        rows = [dict(r) for r in _db.execute("SELECT * FROM plan WHERE job_id=? AND status='done' ORDER BY id DESC", (jid,))]
    PROGRESS[jid] = {"stage": "Буцааж байна", "done": 0, "total": len(rows)}
    # Эхлээд устгасан хоосон хавтсуудыг сэргээнэ
    for r in rows:
        if r["kind"] == "rmdir":
            os.makedirs(r["src"], exist_ok=True)
    for n, r in enumerate(rows, 1):
        try:
            if r["kind"] != "rmdir" and os.path.exists(r["dest"]):
                back = files._unique(r["src"])
                os.makedirs(os.path.dirname(back), exist_ok=True)
                shutil.move(r["dest"], back)
            with _lock:
                _db.execute("UPDATE plan SET status='undone' WHERE id=?", (r["id"],))
        except Exception as e:
            with _lock:
                _db.execute("UPDATE plan SET error=? WHERE id=?", (f"буцаах: {e}"[:200], r["id"]))
        PROGRESS[jid]["done"] = n
    # Цэгцлэх үед үүсгэсэн, одоо хоосон болсон ангиллын хавтсуудыг цэвэрлэнэ
    j = job(jid)
    base = (j["summary"] or {}).get("dest_base")
    if base:
        for c in files.categories() + [DUP_DIR]:
            d = os.path.join(base, c)
            try:
                if os.path.isdir(d) and not os.listdir(d):
                    os.rmdir(d)
            except OSError:
                pass
    with _lock:
        _db.commit()
    _job_set(jid, status="undone")
    PROGRESS.pop(jid, None)


def cancel(jid):
    j = job(jid)
    if j and j["status"] == "ready":
        _job_set(jid, status="cancelled")


def folders_overview():
    out = []
    for f in files.connected_folders():
        js = jobs_for(f["id"], 1)
        out.append({**f, "exists": os.path.isdir(f["path"]), "name": os.path.basename(f["path"]) or f["path"],
                    "last_job": js[0] if js else None})
    return out


# ======================= Демо =======================
DEMO_FILES = {
    "2-р улирлын ирцийн тайлан.txt": "2-р улирлын багш нарын ирцийн нэгдсэн тайлан. Нийт 46 багш.",
    "Тушаал А-145 хичээлийн хуваарь.txt": "Захирлын тушаал. Хичээлийн хуваарь батлах тухай.",
    "ЗАН хурлын тэмдэглэл 11-12.txt": "Заах аргын нэгдлийн хурал. Хэлэлцсэн асуудал: семинар төлөвлөгөө.",
    "Хуучин/2-р улирлын ирцийн тайлан (1).txt": "2-р улирлын багш нарын ирцийн нэгдсэн тайлан. Нийт 46 багш.",
    "Хуучин/math_worksheet_7.txt": "Lesson worksheet grade 7 fractions exercises.",
    "Хуучин/Шалгалт/11б mock дүн.txt": "SAT mock test score 11б анги дүн.",
    "Шинэ хавтас/төсөв 2027 санал.txt": "2027 оны санхүүгийн төсвийн санал.",
    "Шинэ хавтас/IMG_0932.jpg": "jpg",
    "scan0001.txt": "Боловсролын газрын 2026 оны 11-р сарын 10-ны өдрийн А/215 тоот албан бичиг: багшийн хөгжлийн сургалтын тухай.",
    "Document (3).txt": "Эцэг эхийн хурлын хөтөлбөр 2026.11.20. Хэлэлцэх асуудал: улирлын дүн.",
    "Албан бичиг БГ-д.txt": "Боловсролын газарт явуулах албан бичиг.",
}


def demo_seed():
    import pathlib
    import tempfile
    base = pathlib.Path(tempfile.gettempdir()) / "TerreDemo" / "Миний баримтууд"
    if not base.exists():
        for rel, text in DEMO_FILES.items():
            p = base / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            old = time.time() - 86400 * (5 if "(1)" in rel else 10)
            os.utime(p, (old, old))
    if not files.connected_folders():
        add_folder(str(base), mode="off", target="inside")
