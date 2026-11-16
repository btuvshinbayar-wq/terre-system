"""Файл эмхлэгч: Downloads, Desktop, Documents болон мэйлийн хавсралтыг АГУУЛГААР нь ангилж,
<root>/<Ангилал>/ хавтсанд зөөнө. Файлыг хэзээ ч устгахгүй — зөвхөн зөөнө, бүгдийг буцааж болно."""
import logging
import os
import re
import shutil
import sqlite3
import threading
import time

from . import brain
from .config import CFG, DATA, now

log = logging.getLogger("terre.files")
_lock = threading.Lock()
_db = sqlite3.connect(DATA / "terre.db", check_same_thread=False)
_db.row_factory = sqlite3.Row
_db.execute("""CREATE TABLE IF NOT EXISTS files(
    id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE, name TEXT, src TEXT, dest TEXT,
    category TEXT, reason TEXT, origin TEXT, status TEXT, created TEXT)""")
for _col in ("base", "newname"):   # base: ангилсан хавтас үүсэх суурь; newname: шинэ нэр
    try:
        _db.execute(f"ALTER TABLE files ADD COLUMN {_col} TEXT")
    except sqlite3.OperationalError:
        pass
_db.execute("CREATE TABLE IF NOT EXISTS attach(path TEXT PRIMARY KEY, sender TEXT, date TEXT, orig TEXT)")
_db.execute("""CREATE TABLE IF NOT EXISTS folders(
    id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT UNIQUE, mode TEXT, recursive INTEGER, target TEXT, created TEXT)""")
_db.commit()
# status: moved | suggested | ignored | undone

SKIP_EXT = {".crdownload", ".part", ".tmp", ".download", ".lnk", ".url", ".ini", ".partial", ".opdownload"}
DANGEROUS_ATTACH = {".exe", ".bat", ".cmd", ".js", ".vbs", ".scr", ".msi", ".ps1", ".jar", ".com", ".hta"}


def cfg():
    return CFG.get("files", {}) or {}


def X(p):
    return os.path.normpath(os.path.expandvars(os.path.expanduser(p)))


def root():
    return X(cfg().get("root", "~/Documents/Terre"))


def inbox():
    p = os.path.join(root(), "_Ирсэн")
    os.makedirs(p, exist_ok=True)
    return p


def categories():
    return cfg().get("categories") or ["Бусад"]


# ---------------- Агуулга унших ----------------
def extract_text(path, limit=3000):
    ext = os.path.splitext(path)[1].lower()
    try:
        if os.path.getsize(path) > 40_000_000:
            return ""
        if ext == ".pdf":
            from pypdf import PdfReader
            r = PdfReader(path)
            return "\n".join((p.extract_text() or "") for p in r.pages[:3])[:limit]
        if ext == ".docx":
            import docx
            return "\n".join(p.text for p in docx.Document(path).paragraphs)[:limit]
        if ext in (".xlsx", ".xlsm"):
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            try:   # read_only горимд файл нээлттэй үлддэг тул заавал хаана (эс бөгөөс зөөхөд WinError 32)
                rows = []
                for ws in wb.worksheets[:2]:
                    rows.append(f"[{ws.title}]")
                    for row in ws.iter_rows(max_row=25, values_only=True):
                        rows.append(" | ".join(str(c) for c in row if c is not None))
                return "\n".join(rows)[:limit]
            finally:
                wb.close()
        if ext in (".txt", ".csv", ".md", ".json", ".html", ".xml"):
            with open(path, encoding="utf-8", errors="ignore") as f:
                return f.read(limit)
    except Exception as e:
        log.info("Агуулга уншигдсангүй %s: %s", path, e)
    return ""


# ---------------- Скан ----------------
def _key(path):
    st = os.stat(path)
    return f"{path}|{int(st.st_size)}|{int(st.st_mtime)}"


def _known(key):
    with _lock:
        return _db.execute("SELECT 1 FROM files WHERE key=?", (key,)).fetchone() is not None


def _candidates():
    c = cfg()
    min_age = float(c.get("min_age_minutes", 3)) * 60
    since = time.time() - float(c.get("since_days", 30)) * 86400
    r = root()
    # Downloads, Desktop, Documents зэрэг хавтсыг ӨӨРӨӨ цэгцлэхгүй. Зөвхөн Terre-ийн өөрийн хавсралтын хавтас
    # болон хэрэглэгч самбарын «📁 Холбосон хавтсууд»-д зааж тохируулсан хавтсууд (config-ийн files.sources-ийг үл тооно).
    sources = [(inbox(), "auto", "Хавсралт", r)]
    # Самбараас холбосон хавтсууд (шинээр орж ирсэн файлыг хянах)
    for f in connected_folders():
        if f["mode"] in ("auto", "suggest"):
            sources.append((f["path"], f["mode"], os.path.basename(f["path"]) or f["path"],
                            f["path"] if f["target"] == "inside" else r))
    for folder, mode, origin, base in sources:
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            p = os.path.join(folder, name)
            if not os.path.isfile(p) or name.startswith((".", "~$")) or name.lower() == "desktop.ini":
                continue
            if os.path.splitext(name)[1].lower() in SKIP_EXT:
                continue
            if folder != inbox() and _inside(p, r):
                continue
            mt = os.path.getmtime(p)
            if time.time() - mt < min_age or (mt < since and folder != inbox()):
                continue
            yield p, mode, origin, base


def connected_folders():
    with _lock:
        return [dict(r) for r in _db.execute("SELECT * FROM folders ORDER BY id").fetchall()]


def _journal_move(key, shown, newname, cat, origin, who="Terre"):
    from . import journal
    with _lock:
        r = _db.execute("SELECT id FROM files WHERE key=?", (key,)).fetchone()
    title = f"Зөөв: {shown} → {cat}" + (f" («{newname}»)" if newname and newname != shown else "")
    journal.add("file", title[:220], f"{origin}", undo={"type": "file", "id": r["id"]} if r else None, who=who)


def _inside(p, r):
    try:
        return os.path.commonpath([X(p), r]) == r
    except ValueError:      # өөр диск
        return False


def _unique(dest):
    base, ext = os.path.splitext(dest)
    i = 2
    while os.path.exists(dest):
        dest = f"{base} ({i}){ext}"
        i += 1
    return dest


def _record(key, name, src, dest, cat, reason, origin, status, base=None, newname=None):
    with _lock:
        _db.execute("INSERT OR IGNORE INTO files(key,name,src,dest,category,reason,origin,status,created,base,newname) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (key, name, src, dest, cat, reason, origin, status, now().isoformat(), base, newname))
        _db.commit()


# ---------------- Нэр солих ----------------
# АНХААР: давталт дотор давталт (жишээ нь (\d+)*) бүү бич — олон цифртэй нэр дээр regex хязгааргүй удаан
# ажиллаж, Python-ийг бүхэлд нь түгждэг (2026-11-16-нд Terre бүхэлдээ гацсан шалтгаан).
MESSY = re.compile(r"""^(
    img|dsc|dcim|pxl|photo|image|scan|scanned|скан|document|doc|file|untitled|download|attachment|new|noname|
    новый|документ|шинэ|баримт|файл|copy|хуулбар|screenshot|screen\s?shot|capture|whatsapp|telegram|viber|cam|vid
    )?(\(\d+\)|\d|[\s_\-.]|copy|хуулбар|microsoft|word|excel|баримт|документ|document|ажлын|хуудас)*$|^[0-9a-f\-]{16,}$|^\d[\d_\-\s]{5,}$""",
    re.I | re.X)


def rcfg():
    return {"enabled": True, "only_messy": True, "use_ai": True, "file_template": "{name}",
            "attachment_template": "{date} {sender} - {name}", **(cfg().get("rename") or {})}


def is_messy(stem):
    s = stem.strip()
    return len(s) < 3 or bool(MESSY.match(s))


def clean_name(s, limit=80):
    s = re.sub(r"[/\\]", "-", str(s or ""))
    s = re.sub(r'[<>:"|?*\x00-\x1f]', " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .-_")
    return s[:limit].rstrip(" .-_")


def final_name(path, category, ai_name=None):
    """Зөөх үед өгөх файлын нэр. Gemini нэрийг ангиллын дуудлагатай хамт өгдөг тул нэмэлт зардалгүй."""
    name = os.path.basename(path)
    stem, ext = os.path.splitext(name)
    r = rcfg()
    meta = _attach_meta(path)
    if not r["enabled"]:
        return meta["orig"] if meta else name
    base_stem = os.path.splitext(meta["orig"])[0] if meta else stem
    new_stem = base_stem
    tpl = r["attachment_template"] if meta else r["file_template"]
    if not r["only_messy"] or is_messy(base_stem):
        if r["use_ai"] and ai_name and clean_name(ai_name):
            new_stem = clean_name(ai_name, 70)
        elif is_messy(base_stem):
            d = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(path)))
            new_stem = category if "{date}" in tpl else f"{category} {d}"
    date = meta["date"] if meta else time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(path)))
    sender = clean_name(meta["sender"], 30) if meta else ""
    out = clean_name(tpl.format(name=new_stem, date=date, sender=sender, category=category).replace(" -  ", " ").replace("  ", " "), 120)
    return (out or new_stem or stem) + ext.lower()


def _attach_meta(path):
    with _lock:
        r = _db.execute("SELECT * FROM attach WHERE path=?", (os.path.normcase(path),)).fetchone()
    return dict(r) if r else None


def _move(src, cat, base=None, newname=None):
    dest = _unique(os.path.join(base or root(), cat, newname or os.path.basename(src)))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.move(src, dest)
    return dest


def scan():
    """Нэг удаагийн скан. (зөөсөн, санал болгосон) тоо буцаана."""
    if not cfg().get("enabled", True):
        return 0, 0
    moved = suggested = 0
    limit = int(cfg().get("max_per_cycle", 25))
    for path, mode, origin, base in _candidates():
        if moved + suggested >= limit:
            break
        try:
            key = _key(path)
            if _known(key):
                continue
            name = os.path.basename(path)
            ext = os.path.splitext(name)[1].lower()
            meta = _attach_meta(path)
            c = brain.classify_file(meta["orig"] if meta else name, ext, extract_text(path), categories())
            newname = final_name(path, c["category"], c.get("name"))
            shown = meta["orig"] if meta else name
            if mode == "auto":
                dest = _move(path, c["category"], base, newname)
                _record(key, shown, path, dest, c["category"], c["reason"], origin, "moved", base, newname)
                moved += 1
                _journal_move(key, shown, newname, c["category"], origin)
            else:
                _record(key, shown, path, "", c["category"], c["reason"], origin, "suggested", base, newname)
                suggested += 1
        except Exception as e:
            log.warning("Файл боловсруулж чадсангүй %s: %s", path, e)
    return moved, suggested


# ---------------- Самбарын үйлдлүүд ----------------
def get(fid):
    with _lock:
        r = _db.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
    return dict(r) if r else None


def _set(fid, **kw):
    cols = ", ".join(f"{k}=?" for k in kw)
    with _lock:
        _db.execute(f"UPDATE files SET {cols} WHERE id=?", (*kw.values(), fid))
        _db.commit()


def approve(fid, category=None, newname=None):
    f = get(fid)
    if not f or f["status"] != "suggested":
        raise ValueError("Санал болгосон файл биш")
    if not os.path.exists(f["src"]):
        _set(fid, status="ignored", reason="Файл байхгүй болсон")
        raise FileNotFoundError(f["src"])
    cat = category or f["category"]
    nn = clean_name(newname) if newname else f.get("newname")
    if nn and not os.path.splitext(nn)[1]:
        nn += os.path.splitext(f["src"])[1].lower()
    if cat != f["category"]:
        from . import learn
        learn.record_file(f["name"], "", cat)
    dest = _move(f["src"], cat, f.get("base"), nn)
    _set(fid, status="moved", dest=dest, category=cat, newname=os.path.basename(dest))
    _journal_move(f["key"], f["name"], os.path.basename(dest), cat, f["origin"], who="Та")
    return dest


def ignore(fid):
    _set(fid, status="ignored")


def undo(fid):
    f = get(fid)
    if not f or f["status"] != "moved":
        raise ValueError("Зөөгдсөн файл биш")
    if not os.path.exists(f["dest"]):
        raise FileNotFoundError(f["dest"])
    back = _unique(f["src"])
    os.makedirs(os.path.dirname(back), exist_ok=True)
    shutil.move(f["dest"], back)
    _set(fid, status="undone")


def _unconnected_moves():
    """Холбоогүй хавтаснаас (Downloads, Desktop, Documents…) өмнөх тохиргоогоор зөөгдсөн файлууд."""
    allowed = [X(inbox())] + [X(f["path"]) for f in connected_folders()]
    with _lock:
        rows = [dict(r) for r in _db.execute("SELECT * FROM files WHERE status='moved' AND key NOT GLOB 'demo[0-9]*'").fetchall()]
    return [r for r in rows if r.get("src") and not any(_inside(X(r["src"]), a) for a in allowed)]


def unconnected_count():
    try:
        return len(_unconnected_moves())
    except Exception:
        return 0


def undo_unconnected():
    """Тэдгээрийг анхны газар, анхны нэрээр нь буцаана. (буцаасан тоо, алдаатай файлууд)"""
    done, failed = 0, []
    for r in _unconnected_moves():
        try:
            undo(r["id"])
            done += 1
        except Exception as e:
            failed.append(f"{r['name']}: {e}")
    if done:
        from . import journal
        journal.add("file", f"Холбоогүй хавтаснаас зөөсөн {done} файлыг анхны газарт нь буцаав", "; ".join(failed)[:300])
    return done, failed


def recent(statuses, limit=30):
    q = ",".join("?" * len(statuses))
    with _lock:
        rows = _db.execute(f"SELECT * FROM files WHERE status IN ({q}) ORDER BY id DESC LIMIT ?",
                           (*statuses, limit)).fetchall()
    return [dict(r) for r in rows]


def stats():
    start = now().replace(hour=0, minute=0, second=0).isoformat()
    with _lock:
        rows = _db.execute("SELECT status, COUNT(*) n FROM files WHERE created>=? GROUP BY status", (start,)).fetchall()
    return {r["status"]: r["n"] for r in rows}


def save_attachment(filename, data, sender="", date=None):
    """Мэйлийн хавсралтыг _Ирсэн рүү хадгална (дараагийн скан ангилж, нэрлэж, зөөнө). Токен зарцуулахгүй."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in DANGEROUS_ATTACH:
        log.info("Аюултай төрлийн хавсралт алгаслаа: %s", filename)
        return None
    safe = "".join(ch for ch in filename if ch not in '<>:"/\\|?*').strip() or "attachment"
    dest = _unique(os.path.join(inbox(), safe))
    with open(dest, "wb") as f:
        f.write(data)
    # Шинэ файл min_age шүүлтэд баригдахгүйн тулд хугацааг нь хуучруулна
    old = time.time() - 3600
    os.utime(dest, (old, old))
    with _lock:
        _db.execute("INSERT OR REPLACE INTO attach(path,sender,date,orig) VALUES (?,?,?,?)",
                    (os.path.normcase(dest), sender or "", (date or now().isoformat())[:10], safe))
        _db.commit()
    return dest


def register_generated(path, origin):
    """Terre-ийн өөрөө гаргасан файлыг (тайлан, нөөц) 'эмхэлсэн' жагсаалтад харуулна."""
    try:
        name = os.path.basename(path)
        cat = os.path.basename(os.path.dirname(path))
        _record(_key(path), name, path, path, cat, "School Manager-аас гаргасан", origin, "moved")
    except OSError:
        pass


def demo_seed():
    """Демо: хэдэн файлын бичлэг."""
    if recent(["moved", "suggested"], 1):
        return
    samples = [
        ("2-р улирлын ирцийн нэгдсэн тайлан.xlsx", "Тайлан", "Улирлын ирцийн нэгдсэн хүснэгт", "Хавсралт", "moved"),
        ("A-145 тушаал хичээлийн хуваарь.pdf", "Тушаал, шийдвэр", "Захирлын тушаал", "Downloads", "moved"),
        ("SAT_mock_11b_results.xlsx", "Шалгалт, дүн", "11б ангийн mock test-ийн дүн", "Downloads", "moved"),
        ("IMG_20261114_0932.jpg", "Зураг", "Файлын төрлөөр", "Downloads", "moved"),
        ("scan0001.pdf", "Албан бичиг", "Боловсролын газрын албан бичиг", "Хавсралт", "moved"),
        ("Эцэг эхийн хурлын төлөвлөгөө.docx", "Хурал, төлөвлөгөө", "Хурлын хөтөлбөр, хэлэлцэх асуудал", "Desktop", "suggested"),
        ("budget_2027_draft.xlsx", "Санхүү", "2027 оны төсвийн төсөл", "Documents", "suggested"),
    ]
    renames = {"scan0001.pdf": "2026-11-14 Боловсролын газар - БГ-ын А-215 албан бичиг багшийн сургалт.pdf",
               "Эцэг эхийн хурлын төлөвлөгөө.docx": "Эцэг эхийн хурлын төлөвлөгөө 2026-11-20.docx"}
    for i, (n, c, r, o, s) in enumerate(samples):
        nn = renames.get(n, n)
        _record(f"demo{i}", n, f"C:/Users/You/{o}/{n}", f"C:/Users/You/Documents/Terre/{c}/{nn}" if s == "moved" else "",
                c, r, o, s, None, nn)

