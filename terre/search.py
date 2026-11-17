"""Файлаас хайх, асуух.

TED-ийн эмхэлсэн хавтас болон холбосон хавтсуудын файлын агуулгыг таны компьютер дээр индекслэнэ
(SQLite FTS5, токен зарцуулахгүй). "Асуух" үед л хамгийн тохирох 6 файлын хэсгийг Gemini-д өгч хариулна.
"""
import logging
import os
import re
import time

from . import files
from .config import gemini_key

log = logging.getLogger("terre.search")
_db, _lock = files._db, files._lock
_db.execute("CREATE TABLE IF NOT EXISTS docs(path TEXT PRIMARY KEY, name TEXT, folder TEXT, mtime REAL, size INTEGER, indexed REAL)")
_db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(path UNINDEXED, name, folder, body, tokenize='unicode61 remove_diacritics 0')")
_db.commit()

TEXT_EXT = {".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".csv", ".md", ".html", ".json", ".xml"}
STOP = {"юу", "вэ", "бэ", "уу", "үү", "хаана", "байна", "байгаа", "байсан", "гэж", "нь", "энэ", "тэр", "ямар", "хэзээ",
        "хэн", "ба", "болон", "бол", "юм", "хэд", "хэдэн", "файл", "баримт", "дээр", "дотор", "the", "a", "of", "in", "and",
        "what", "where", "is", "find", "олох", "олж", "өг", "хайх", "хай", "надад", "миний"}
MAX_PER_RUN = 150
_last_cleanup = 0


def roots():
    out = [files.root()] + [f["path"] for f in files.connected_folders()]
    return [r for r in dict.fromkeys(out) if os.path.isdir(r)]


def _skip_dir(d):
    from .organizer import SKIP_DIRS, _is_project
    n = os.path.basename(d)
    return n.startswith((".", "~", "$")) or n.lower() in SKIP_DIRS or _is_project(d)


def index_once(limit=MAX_PER_RUN):
    """Шинэ/өөрчлөгдсөн файлуудыг индекслэнэ. Индекслэсэн тоог буцаана."""
    global _last_cleanup
    with _lock:
        known = {r["path"]: (r["mtime"], r["size"]) for r in _db.execute("SELECT path, mtime, size FROM docs")}
    done = 0
    seen = set()
    for root in roots():
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if not _skip_dir(os.path.join(dp, d))]
            for f in fn:
                if f.startswith(("~$", ".")) or f.lower() in ("desktop.ini", "thumbs.db"):
                    continue
                p = os.path.join(dp, f)
                seen.add(p)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                if known.get(p) == (st.st_mtime, st.st_size):
                    continue
                if done >= limit:
                    continue
                ext = os.path.splitext(f)[1].lower()
                body = files.extract_text(p, 20000) if ext in TEXT_EXT else ""
                folder = os.path.basename(dp)
                with _lock:
                    _db.execute("DELETE FROM docs_fts WHERE path=?", (p,))
                    _db.execute("INSERT INTO docs_fts(path,name,folder,body) VALUES (?,?,?,?)", (p, f, folder, body))
                    _db.execute("INSERT OR REPLACE INTO docs VALUES (?,?,?,?,?,?)", (p, f, folder, st.st_mtime, st.st_size, time.time()))
                done += 1
                if done % 25 == 0:
                    with _lock:
                        _db.commit()
    with _lock:
        _db.commit()
    if time.time() - _last_cleanup > 3600 and done < limit:     # устгагдсан/зөөгдсөн файлыг индексээс хасна
        _last_cleanup = time.time()
        gone = [p for p in known if p not in seen]
        with _lock:
            for p in gone:
                _db.execute("DELETE FROM docs WHERE path=?", (p,))
                _db.execute("DELETE FROM docs_fts WHERE path=?", (p,))
            _db.commit()
    return done


def _terms(q):
    words = [w for w in re.findall(r"[\w\-]+", q.lower()) if w not in STOP and len(w) >= 2]
    out = []
    for w in words:
        w = w.replace('"', "")
        # Монгол нөхцөл залгаврыг ойролцоогоор хасна: "тайлангаа" → "тайлан*"
        stem = w if len(w) <= 4 else w[:max(4, len(w) - 3)]
        out.append(f'"{stem}"*')
    return out


def search(q, limit=20):
    terms = _terms(q)
    if not terms:
        return []
    rows = []
    for joiner in (" AND ", " OR "):
        expr = joiner.join(terms)
        try:
            with _lock:
                rows = _db.execute(
                    "SELECT d.path, d.name, d.folder, snippet(docs_fts, 3, '[', ']', '…', 18) snip, bm25(docs_fts, 0, 6.0, 2.0, 1.0) score, "
                    "m.mtime FROM docs_fts d LEFT JOIN docs m ON m.path=d.path WHERE docs_fts MATCH ? ORDER BY score LIMIT ?",
                    (expr, limit)).fetchall()
        except Exception as e:
            log.info("FTS алдаа: %s", e)
            rows = []
        if rows:
            break
    return [{"path": r["path"], "name": r["name"], "folder": r["folder"], "snippet": r["snip"] or "",
             "date": time.strftime("%Y-%m-%d", time.localtime(r["mtime"])) if r["mtime"] else ""} for r in rows]


def _body(path, q, size=1500):
    with _lock:
        r = _db.execute("SELECT body FROM docs_fts WHERE path=?", (path,)).fetchone()
    body = (r["body"] if r else "") or ""
    terms = [t.strip('"*') for t in _terms(q)]
    pos = min([body.lower().find(t) for t in terms if body.lower().find(t) >= 0] or [0])
    start = max(0, pos - size // 3)
    return body[start:start + size]


def ask(question):
    hits = search(question, 6)
    if not hits:
        from .config import EN
        return {"answer": "No matching files found. Try other words (file contents are often in Mongolian)." if EN()
                else "Холбогдох файл олдсонгүй. Өөр үгээр асууж үзнэ үү.", "sources": []}
    if not gemini_key():
        from .config import EN
        return {"answer": f"I found {len(hits)} files:" if EN() else f"{len(hits)} файл олдлоо (Gemini түлхүүргүй үед хариу зохиохгүй):", "sources": hits}
    from . import brain
    from .config import EN
    ctx = "\n\n".join(f"[{i + 1}] {h['name']} ({h['folder']}, {h['date']}):\n{_body(h['path'], question)}" for i, h in enumerate(hits))
    lang = "АНГЛИАР (энгийн, B2 түвшний англи; монгол эх текстийг утгаар нь орчуул)" if EN() else "МОНГОЛООР"
    prompt = f"""Доорх файлуудын хэсгээс асуултад {lang} товч, үнэн зөв хариул. Зөвхөн өгсөн текстэд үндэслэ.
Хариултын төгсгөлд эх сурвалжийг [1], [2] гэж заа. Олдохгүй бол олдсонгүй гэж шударгаар хэл.

{ctx}

Асуулт: {question}"""
    ans = brain._gen(brain._fast(), prompt, temperature=0.2).text.strip()
    return {"answer": ans, "sources": hits}


def is_indexed(path):
    with _lock:
        return _db.execute("SELECT 1 FROM docs WHERE path=?", (path,)).fetchone() is not None


def stats():
    with _lock:
        n = _db.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    return {"indexed": n, "roots": roots()}
