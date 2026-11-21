"""Viber, Discord (компьютерийн апп), Facebook Messenger (браузер) — Windows-ийн мэдэгдлээр унших.

Эдгээр программд хувийн чатыг унших албан ёсны API байхгүй. Харин мессеж ирэхэд Windows мэдэгдэл гаргадаг бөгөөд
Windows түүнийгээ таны профайл дахь мэдэгдлийн санд (wpndatabase.db) хадгалдаг. TED тэр санг ЗӨВХӨН УНШИНА
(хуулбар дээр), юу ч өөрчлөхгүй, дансанд нэвтрэхгүй — тиймээс дансны дүрэм зөрчихгүй.

Хариу: TED ноорог бичнэ → та «Copy & open» дарна → ноорог санах ойд хуулагдаж, тухайн программ нээгдэнэ →
та Ctrl+V дараад өөрөө илгээнэ. TED хэзээ ч өөрөө илгээхгүй.

Анхаар: мэдэгдэлд мессежийн урьдчилсан текст (preview) харагдах тохиргоо апп/браузерт асаалттай байх ёстой.
Messenger-ийн хувьд браузерт messenger.com-д мэдэгдэл зөвшөөрсөн байна.
"""
import datetime
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import xml.etree.ElementTree as ET

from ..config import CFG, DATA, TZ

log = logging.getLogger("terre.notif")

APPS = {
    "viber":     {"label": "Viber",     "match": ["viber"],                         "open": "viber://"},
    "discord":   {"label": "Discord",   "match": ["discord"],                       "open": "discord://"},
    "messenger": {"label": "Messenger", "match": ["messenger.com", "messenger"],    "open": "https://www.messenger.com/"},
}
SOURCES = tuple(APPS)
_SEEN_FILE = DATA / "notif_seen.json"
_BUF = {}            # notification id -> dict
_lock = threading.Lock()
_started = False
_status = {"ok": None, "msg": "", "at": 0}


def cfg():
    c = (CFG.get("sources") or {}).get("app_notifications") or {}
    return c if isinstance(c, dict) else {}


def enabled_apps():
    want = cfg().get("apps") or list(APPS)
    return [a for a in want if a in APPS]


def _db_path():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    return os.path.join(base, "Microsoft", "Windows", "Notifications", "wpndatabase.db")


def _read_db():
    """Санг хуулбарлаж уншина (Windows ашиглаж байгаа үед түгжээтэй байдаг)."""
    src = _db_path()
    if not os.path.exists(src):
        raise RuntimeError("Windows-ийн мэдэгдлийн сан олдсонгүй")
    tmp = tempfile.mkdtemp(prefix="ted-wpn-")
    try:
        for suf in ("", "-wal", "-shm"):
            if os.path.exists(src + suf):
                shutil.copy2(src + suf, os.path.join(tmp, "wpn.db" + suf))
        con = sqlite3.connect(os.path.join(tmp, "wpn.db"))
        try:
            rows = con.execute(
                "SELECT n.Id, n.Payload, n.ArrivalTime, h.PrimaryId FROM Notification n "
                "JOIN NotificationHandler h ON h.RecordId = n.HandlerId "
                "WHERE n.Type = 'toast' ORDER BY n.Id DESC LIMIT 400").fetchall()
        finally:
            con.close()
        return rows
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _filetime(ft):
    try:
        return datetime.datetime.fromtimestamp(int(ft) / 10_000_000 - 11644473600, TZ)
    except Exception:
        return datetime.datetime.now(TZ)


def _texts(payload):
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", "ignore")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return [], ""
    texts, attribution = [], ""
    for t in root.iter("text"):
        v = (t.text or "").strip()
        if not v:
            continue
        if t.get("placement") == "attribution":
            attribution = v
        else:
            texts.append(v)
    return texts, attribution


def _classify(aumid, texts, attribution):
    hay = " ".join([aumid or "", attribution] + texts).lower()
    for app in enabled_apps():
        if app == "messenger":
            # Браузерийн мэдэгдэл (Edge/Chrome) эсвэл Messenger апп — messenger.com гэж заасан байх ёстой
            if "messenger.com" in hay or "messenger" in (aumid or "").lower():
                return app
            continue
        if any(m in hay for m in APPS[app]["match"]):
            return app
    return None


def _load_seen():
    try:
        return set(json.loads(_SEEN_FILE.read_text("utf-8")))
    except Exception:
        return set()


def _save_seen(seen):
    try:
        _SEEN_FILE.write_text(json.dumps(sorted(seen)[-3000:]), "utf-8")
    except Exception:
        pass


def poll_once():
    rows = _read_db()
    cutoff = datetime.datetime.now(TZ) - datetime.timedelta(hours=24)
    got = 0
    with _lock:
        for nid, payload, arrival, aumid in rows:
            if nid in _BUF:
                continue
            texts, attribution = _texts(payload)
            app = _classify(aumid, texts, attribution)
            if not app or not texts:
                continue
            when = _filetime(arrival)
            if when < cutoff:
                continue
            sender = texts[0]
            body = "\n".join(texts[1:]) or texts[0]
            # Браузерийн мэдэгдлийн гарчигт "Messenger" эсвэл "(3) Messenger" гэх мэт ирж болно
            sender = re.sub(r"^\(\d+\)\s*", "", sender)
            _BUF[nid] = {"nid": nid, "app": app, "sender": sender[:120], "text": body[:2000], "at": when}
            got += 1
        # 24 цагаас хуучныг санах ойгоос цэвэрлэнэ
        for k in [k for k, v in _BUF.items() if v["at"] < cutoff]:
            _BUF.pop(k, None)
    return got


def _watch():
    """Зарим апп мессежийг уншмагц мэдэгдлээ арилгадаг тул 15 секунд тутамд шалгаж санах ойд авна."""
    while True:
        try:
            poll_once()
            _status.update(ok=True, msg="", at=time.time())
        except Exception as e:
            _status.update(ok=False, msg=str(e), at=time.time())
            log.debug("Мэдэгдэл унших: %s", e)
        time.sleep(int(cfg().get("poll_seconds", 15)))


def start():
    global _started
    if _started or os.name != "nt":
        return
    _started = True
    threading.Thread(target=_watch, daemon=True, name="app-notifications").start()


def fetch_recent():
    """Шинэ мэдэгдлүүдийг илгээгчээр нь бүлэглэж TED-ийн мессеж болгоно."""
    if os.name != "nt":
        return []
    start()
    poll_once()
    seen = _load_seen()
    groups = {}
    with _lock:
        for n in sorted(_BUF.values(), key=lambda x: x["nid"]):
            if str(n["nid"]) in seen:
                continue
            groups.setdefault((n["app"], n["sender"]), []).append(n)
    out = []
    for (app, sender), ns in groups.items():
        last = ns[-1]
        lines = [n["text"] for n in ns]
        out.append({
            "id": f"notif:{app}:{last['nid']}",
            "source": app,
            "sender": sender,
            "subject": APPS[app]["label"] + (f" ({len(ns)} messages)" if len(ns) > 1 else ""),
            "snippet": lines[-1][:200],
            "body": "\n".join(lines),
            "received": last["at"].isoformat(),
            "meta": {"app": app, "nids": [n["nid"] for n in ns], "from_addr": f"{app}:{sender.lower()}"},
        })
        seen.update(str(n["nid"]) for n in ns)
    _save_seen(seen)
    return out


def status():
    return dict(_status)


# ---- Хариу: санах ойд хуулж, программыг нээнэ (илгээхийг хэрэглэгч өөрөө) ----

def copy_to_clipboard(text):
    if os.name != "nt":
        raise RuntimeError("Зөвхөн Windows дээр")
    import ctypes
    from ctypes import wintypes
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalAlloc.restype = wintypes.HGLOBAL
    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    u32.SetClipboardData.restype = wintypes.HANDLE
    u32.OpenClipboard.argtypes = [wintypes.HWND]
    data = (text or "").replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-16-le") + b"\x00\x00"
    for _ in range(10):
        if u32.OpenClipboard(None):
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("Санах ойг (clipboard) нээж чадсангүй")
    try:
        u32.EmptyClipboard()
        h = k32.GlobalAlloc(0x0042, len(data))          # GMEM_MOVEABLE | GMEM_ZEROINIT
        p = k32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        k32.GlobalUnlock(h)
        if not u32.SetClipboardData(13, h):             # CF_UNICODETEXT
            raise RuntimeError("Санах ойд хуулж чадсангүй")
    finally:
        u32.CloseClipboard()


def handoff(text, target):
    copy_to_clipboard(text)
    try:
        os.startfile(target)
    except Exception as e:
        log.warning("Нээж чадсангүй %s: %s", target, e)
        return {"handoff": True, "opened": False}
    return {"handoff": True, "opened": True}


def send_reply(item, body):
    app = (item.get("meta") or {}).get("app") or item["source"]
    return handoff(body, APPS.get(app, {}).get("open", "https://www.messenger.com/"))


def mark_read(item):
    """Энэ апп-уудад гаднаас «уншсан» тэмдэглэх боломжгүй — зөвхөн TED-ийн жагсаалтаас хасна."""
    return None


def apply_action(item, action):
    return None
