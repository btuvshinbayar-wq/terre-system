"""Холболтын эрүүл мэнд: эх сурвалж бүрийн сүүлийн амжилт, алдаа, анхааруулга."""
import os
import shutil
import time

from .config import CFG, DATA, DEMO, gemini_key, now, source_enabled

STATUS = {}      # name -> {"status": ok|error|warn|off, "msg", "last_ok", "last_err", "ts"}


def ok(name, msg=""):
    s = STATUS.setdefault(name, {})
    s.update(status="ok", msg=msg, last_ok=now().strftime("%m-%d %H:%M"), ts=time.time())


def err(name, msg):
    s = STATUS.setdefault(name, {})
    s.update(status="error", msg=str(msg)[:300], last_err=now().strftime("%m-%d %H:%M"), ts=time.time())


def warn(name, msg):
    s = STATUS.setdefault(name, {})
    s.update(status="warn", msg=str(msg)[:300], ts=time.time())


def _hint(msg):
    m = (msg or "").lower()
    if any(w in m for w in ("invalid_grant", "нэвтрээгүй", "expired", "token", "unauthorized", "401", "setup_auth")):
        return "Нэвтрэлт дууссан байж магадгүй → Эхлэх цэс → «Terre System — холболт тохируулах»"
    if any(w in m for w in ("getaddrinfo", "timed out", "connection", "network", "11001")):
        return "Интернэт холболтоо шалгана уу"
    if "хаалттай" in m:
        return "School Manager-ийг нээнэ үү (самбарын «Нээх» товч)"
    if "api key" in m or "api_key" in m or "permission" in m:
        return "Gemini API түлхүүрээ шалгана уу"
    return ""


def report():
    """Самбарт харуулах бүрэн жагсаалт (тохиргоонд байгаа бүх зүйл)."""
    rows = []

    def add(name, enabled, extra_warn=None):
        if not enabled:
            return
        s = dict(STATUS.get(name) or {"status": "pending", "msg": "Хараахан шалгаагүй"})
        if extra_warn and s.get("status") == "ok":
            s.update(status="warn", msg=extra_warn)
        s["hint"] = _hint(s.get("msg")) if s.get("status") in ("error", "warn") else ""
        rows.append({"name": name, **s})

    if DEMO:
        rows.append({"name": "Демо горим", "status": "warn", "msg": "Жинхэнэ холболт идэвхгүй. Тохиргоонд demo_mode: false болгоно",
                     "hint": "Самбарын «Систем» таб → «Демо горимоос гарах»"})
    add("Gemini AI", True if gemini_key() else False)
    if not gemini_key():
        rows.append({"name": "Gemini AI", "status": "warn", "msg": "Түлхүүргүй — энгийн дүрмээр ажиллаж байна",
                     "hint": "config.yaml → gemini.api_key"})
    gw = None
    tok = DATA / "google_token.json"
    if tok.exists():
        days = (time.time() - os.path.getmtime(DATA / "google_login.txt" if (DATA / "google_login.txt").exists() else tok)) / 86400
        if days >= 6 and CFG.get("google_app_testing", True):
            gw = f"Google-д {int(days)} хоногийн өмнө нэвтэрсэн. App 'Testing' төлөвтэй бол 7 хоногт дуусна"
    add("Gmail", source_enabled("gmail"), gw)
    add("Google Calendar", source_enabled("google_calendar"), gw)
    add("Google Chat", source_enabled("google_chat"))
    add("Outlook", source_enabled("outlook"))
    for a in CFG.get("sources", {}).get("other_mail", []) or []:
        add(a.get("name") or a.get("email"), bool(a.get("enabled")))
    add("Telegram", source_enabled("telegram"))
    add("Telegram bot", bool((CFG.get("telegram_bot") or {}).get("enabled")))
    if CFG.get("school_manager", {}).get("enabled"):
        try:
            from .connectors import school_manager as _sm
            st, msg, hint = _sm.diagnose()
            rows.append({"name": "School Manager", "status": st, "msg": msg, "hint": hint})
        except Exception as e:
            rows.append({"name": "School Manager", "status": "error", "msg": str(e), "hint": ""})
    else:
        add("School Manager", False)
    add("Файл эмхлэгч", bool(CFG.get("files", {}).get("enabled", True)))
    add("Файлын хайлт", True)
    add("Дуу", bool(CFG.get("voice", {}).get("enabled")))
    add("Товчлол", bool((CFG.get("desktop") or {}).get("hotkeys", True)))
    try:
        root = os.path.expanduser(CFG.get("files", {}).get("root", "~/Documents"))
        free = shutil.disk_usage(os.path.splitdrive(root)[0] + os.sep if os.name == "nt" else "/").free / 1e9
        if free < 2:
            rows.append({"name": "Дискний зай", "status": "warn", "msg": f"Ердөө {free:.1f} GB үлдсэн", "hint": "Хог файлаа цэвэрлэнэ үү"})
    except Exception:
        pass
    order = {"error": 0, "warn": 1, "pending": 2, "ok": 3}
    rows.sort(key=lambda r: order.get(r["status"], 9))
    worst = rows[0]["status"] if rows else "ok"
    return {"overall": worst, "items": rows}
