"""Сурах: таны засваруудыг жишээ болгон хадгалж, дараагийн ангилал, нооргод ашиглана.

- Мэйлийн ангиллыг сольвол (жишээ нь "чухал биш"-ийг "хариу бичих" болговол) → дараа ижил төрлийн мэйлийг зөв ангилна
- Файлын ангиллыг сольвол → ижил төрлийн файлыг тэр ангилалд оруулна
- Ноорогийг засаад илгээвэл → таны бичих хэв маягийг сурч, "хэв маягийн профайл" үүсгэнэ
Бүгд таны компьютер дээр хадгалагдана. Самбарын "Систем" табаас харж, засаж, устгаж болно.
"""
import difflib
import json
import logging

from . import files
from .config import gemini_key, now

log = logging.getLogger("terre.learn")
_db, _lock = files._db, files._lock
_db.execute("CREATE TABLE IF NOT EXISTS examples(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, input TEXT, output TEXT, ts TEXT)")
_db.execute("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT)")
_db.commit()
CAT_MN = {"auto": "чухал биш", "approve": "хариу шаардлагатай", "urgent": "яаралтай"}


def _add(kind, inp, out):
    with _lock:
        _db.execute("INSERT INTO examples(kind,input,output,ts) VALUES (?,?,?,?)", (kind, inp[:600], out[:2000], now().isoformat()))
        _db.execute("DELETE FROM examples WHERE kind=? AND id NOT IN (SELECT id FROM examples WHERE kind=? ORDER BY id DESC LIMIT 200)",
                    (kind, kind))
        _db.commit()


def _last(kind, n):
    with _lock:
        return [dict(r) for r in _db.execute("SELECT * FROM examples WHERE kind=? ORDER BY id DESC LIMIT ?", (kind, n))]


def kv_get(k, default=""):
    with _lock:
        r = _db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def kv_set(k, v):
    with _lock:
        _db.execute("INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)", (k, v))
        _db.commit()


# ---------------- Бүртгэх ----------------
def record_triage(item, category):
    _add("triage", f"{item.get('sender', '')} | {item.get('subject', '')} | {(item.get('snippet') or item.get('body') or '')[:150]}", category)


def record_file(name, snippet, category):
    _add("file", f"{name} | {(snippet or '')[:150]}", category)


def record_draft(item, draft, final):
    if not draft or not final:
        return
    ratio = difflib.SequenceMatcher(None, draft, final).ratio()
    if ratio > 0.97:          # бараг өөрчлөөгүй
        return
    _add("draft", json.dumps({"from": item.get("sender", ""), "subject": item.get("subject", ""), "draft": draft[:900]},
                             ensure_ascii=False), final)
    n = int(kv_get("drafts_since_profile", "0")) + 1
    kv_set("drafts_since_profile", str(n))
    if n >= 5:
        try:
            update_style_profile()
        except Exception as e:
            log.warning("Хэв маягийн профайл шинэчлэх алдаа: %s", e)


# ---------------- Prompt-д оруулах ----------------
def triage_examples(n=8):
    ex = _last("triage", n)
    if not ex:
        return ""
    lines = "\n".join(f"- {e['input'][:160]} → {e['output']}" for e in ex)
    return f"\nЭзэн өмнө нь ингэж зассан (ижил төрлийн мэйлд үүнийг дага):\n{lines}\n"


def file_examples(n=10):
    ex = _last("file", n)
    if not ex:
        return ""
    lines = "\n".join(f"- {e['input'][:120]} → {e['output']}" for e in ex)
    return f"\nЭзэн өмнө нь файлыг ингэж ангилсан (ижил төрлийн файлд үүнийг дага):\n{lines}\n"


def style_block():
    p = kv_get("style_profile")
    ex = _last("draft", 2)
    out = ""
    if p:
        out += f"\nЭзний бичих хэв маяг (заавал дага):\n{p}\n"
    for e in ex:
        try:
            d = json.loads(e["input"])
            out += f"\nЖишээ — эзний засаж илгээсэн хариу ({d['subject'][:60]}):\n{e['output'][:500]}\n"
        except Exception:
            pass
    return out


def update_style_profile():
    ex = _last("draft", 12)
    if len(ex) < 3 or not gemini_key():
        return kv_get("style_profile")
    from . import brain
    pairs = []
    for e in ex:
        d = json.loads(e["input"])
        pairs.append(f"НООРОГ:\n{d['draft']}\nЭЗНИЙ ИЛГЭЭСЭН:\n{e['output']}")
    prompt = ("Доорх хосуудад AI-ийн ноорог болон эзний засаж илгээсэн хувилбар байна. Эзний бичих хэв маягийг "
              "5-8 богино дүрмээр (монголоор, '- ' эхлэлтэй) тодорхойл: мэндчилгээ, хаяглалт, урт, албан ёсны түвшин, "
              "гарын үсэг, байнга хэрэглэдэг хэллэг, юуг хасдаг. Зөвхөн дүрмүүдийг буцаа.\n\n" + "\n\n---\n\n".join(pairs))
    text = brain._gen(brain._model(), prompt, temperature=0.2).text.strip()
    kv_set("style_profile", text)
    kv_set("drafts_since_profile", "0")
    return text


def summary():
    with _lock:
        counts = {r["kind"]: r["n"] for r in _db.execute("SELECT kind, COUNT(*) n FROM examples GROUP BY kind")}
    return {"counts": counts, "style_profile": kv_get("style_profile"),
            "recent": [{"kind": e["kind"], "input": e["input"][:140], "output": e["output"][:140], "ts": e["ts"][:16]}
                       for kind in ("triage", "file", "draft") for e in _last(kind, 5)]}


def reset(kind=None):
    with _lock:
        if kind:
            _db.execute("DELETE FROM examples WHERE kind=?", (kind,))
        else:
            _db.execute("DELETE FROM examples")
            _db.execute("DELETE FROM kv WHERE k IN ('style_profile','drafts_since_profile')")
        _db.commit()
