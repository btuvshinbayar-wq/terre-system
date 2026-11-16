"""School Manager (таны Electron програм) холболт — Terre Bridge-ээр.

School Manager асахдаа %APPDATA%\\TerreBridge\\school-manager.json-д порт, нууц token бичнэ.
Terre үүнийг уншаад 127.0.0.1 дээрх bridge рүү тушаал илгээнэ. Бүх өөрчлөлт програмын
өөрийн React state-ээр дамжиж хадгалагдана — товч дарах, өгөгдлийн санд шууд бичих зүйл байхгүй.
"""
import glob
import json
import os
import subprocess
import time

import requests

from ..config import CFG, now

STATUS = ["Ирсэн", "Өвчтэй", "Чөлөөтэй", "Тасалсан", "Хоцорсон"]
PLAN_STATUS = ["төлөвлөсөн", "хийгдэж байгаа", "биелсэн", "хойшилсон"]
NOTE_CATEGORIES = ["бүртгэл", "хурал цуглаан", "уулзалт", "зөвлөн туслах", "цахим систем", "сургалт",
                   "хөтөлбөр хэрэгжүүлэх", "өөрийн хөгжил", "тодорхойлолт", "шилжилт хөдөлгөөн", "амжилт", "бусад"]
TABS = {"Нүүр": "dashboard", "Календарь": "calendar", "Төлөвлөгөө": "plan", "Тэмдэглэл": "notes",
        "Хөтөлбөр шинжилгээ": "curriculum", "Тайлан": "report", "Ирц": "attendance", "Нэгтгэл": "consolidation"}

OPT = {"optional": True}
COMMANDS = [
    {"name": "Багшийн ирц тэмдэглэх", "action": "set_attendance",
     "description": "Багшийн өнөөдрийн (эсвэл заасан өдрийн) ирцийг тэмдэглэнэ",
     "params": [{"name": "teacher", "label": "Багш", "suggest": "teachers"},
                {"name": "status", "label": "Төлөв", "choices": STATUS},
                {"name": "date", "label": "Огноо (хоосон = өнөөдөр)", **OPT},
                {"name": "note", "label": "Тайлбар", **OPT}]},
    {"name": "Ажлын тэмдэглэл нэмэх", "action": "add_note",
     "description": "Хийсэн ажлаа тэмдэглэлд бүртгэнэ",
     "params": [{"name": "title", "label": "Юу хийсэн"},
                {"name": "category", "label": "Ангилал", "choices": NOTE_CATEGORIES},
                {"name": "hours", "label": "Зарцуулсан цаг", **OPT},
                {"name": "participants", "label": "Оролцогчийн тоо", **OPT},
                {"name": "result", "label": "Үр дүн, дүгнэлт", **OPT},
                {"name": "plan", "label": "Холбогдох төлөвлөгөө", "suggest": "plans", **OPT},
                {"name": "date", "label": "Огноо (хоосон = өнөөдөр)", **OPT}]},
    {"name": "Төлөвлөгөөний төлөв солих", "action": "set_plan_status",
     "description": "Төлөвлөгөөг биелсэн, хойшилсон гэх мэтээр тэмдэглэнэ",
     "params": [{"name": "plan", "label": "Төлөвлөгөө", "suggest": "plans"},
                {"name": "status", "label": "Төлөв", "choices": PLAN_STATUS}]},
    {"name": "Төлөвлөгөө нэмэх", "action": "add_plan",
     "description": "Сарын төлөвлөгөөнд шинэ ажил нэмнэ",
     "params": [{"name": "activity", "label": "Үйл ажиллагаа"},
                {"name": "startDate", "label": "Эхлэх огноо (YYYY-MM-DD)", **OPT},
                {"name": "endDate", "label": "Дуусах огноо", **OPT},
                {"name": "goal", "label": "Зорилго", **OPT}]},
    {"name": "Сарын ажлын тайлан (Word)", "action": "export", "kind": "report_docx", "folder": "Тайлан",
     "file": "Ажлын тайлан {month}.docx", "description": "Сарын ажлын тайланг Word-оор гаргаж Тайлан хавтсанд хадгална",
     "params": [{"name": "month", "label": "Сар (YYYY-MM, хоосон = энэ сар)", **OPT}]},
    {"name": "Багшийн ирцийн хүснэгт (Excel)", "action": "export", "kind": "attendance_xlsx", "folder": "Тайлан",
     "file": "Багшийн ирц {month}.xlsx", "description": "Сарын ирц, цагийн тооцоог Excel-ээр гаргана",
     "params": [{"name": "month", "label": "Сар (YYYY-MM, хоосон = энэ сар)", **OPT}]},
    {"name": "Төлөвлөгөө Excel-ээр", "action": "export", "kind": "plans_xlsx", "folder": "Тайлан",
     "file": "Төлөвлөгөө {date}.xlsx", "description": "Бүх төлөвлөгөөг Excel-ээр гаргана", "params": []},
    {"name": "Бүрэн нөөцлөл хийх", "action": "export", "kind": "backup", "folder": "Нөөцлөл",
     "file": "School Manager нөөц {date} {time}.json", "description": "Бүх өгөгдлийн нөөц хуулбар хадгална", "params": []},
    {"name": "Цонх нээх", "action": "navigate", "description": "School Manager-ийн тухайн цонхыг нээж харуулна",
     "params": [{"name": "tab", "label": "Цонх", "choices": list(TABS)}]},
]


def SM():
    return CFG.get("school_manager", {}) or {}


def commands():
    return COMMANDS


def get_command(name):
    for c in COMMANDS:
        if c["name"] == name:
            return c
    raise KeyError(f"Тушаал олдсонгүй: {name}")


# ---------------- Bridge холболт ----------------
def _info():
    path = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "TerreBridge", "school-manager.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _req(method, url, info, **kw):
    return requests.request(method, f"http://127.0.0.1:{info['port']}{url}",
                            headers={"X-Terre-Token": info["token"]}, timeout=kw.pop("timeout", 30), **kw)


def is_running():
    info = _info()
    if not info:
        return False
    try:
        return _req("GET", "/ping", info, timeout=3).ok
    except requests.RequestException:
        return False


def call(action, params=None, timeout=90):
    info = _info()
    if not info:
        raise RuntimeError("School Manager хаалттай байна")
    try:
        r = _req("POST", "/action", info, json={"action": action, "params": params or {}}, timeout=timeout)
    except requests.RequestException:
        raise RuntimeError("School Manager хаалттай байна (эсвэл Terre Bridge-гүй хуучин хувилбар)")
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "Тодорхойгүй алдаа"))
    return data.get("result")


def find_exe():
    cand = [SM().get("exe")] if SM().get("exe") else []
    cand += [r"C:\Program Files\School Manager\School Manager.exe",
             os.path.expandvars(r"%LOCALAPPDATA%\Programs\school-manager\School Manager.exe"),
             os.path.expandvars(r"%LOCALAPPDATA%\Programs\School Manager\School Manager.exe")]
    cand += glob.glob(r"C:\Program Files*\School*Manager*\*.exe")
    for c in cand:
        if c and os.path.exists(os.path.expandvars(c)) and "uninstall" not in c.lower():
            return os.path.expandvars(c)
    return None


def start(wait=45):
    if is_running():
        call("focus")
        return True
    exe = find_exe()
    if not exe:
        raise RuntimeError("School Manager.exe олдсонгүй. config.yaml → school_manager.exe-д замыг бичнэ үү")
    subprocess.Popen([exe], cwd=os.path.dirname(exe))
    for _ in range(wait):
        time.sleep(1)
        if is_running():
            time.sleep(2)   # React ачаалагдах хугацаа
            return True
    raise RuntimeError("School Manager асаалаа, гэвч Terre Bridge хариу өгсөнгүй (шинэ хувилбар суулгасан эсэхийг шалгана уу)")


# ---------------- Өгөгдөл ----------------
def fetch_state():
    """Самбар, өглөөний мэдээнд хэрэгтэй бүх зүйл. Хаалттай бол None."""
    if not is_running():
        return None
    s = call("summary")
    plans = call("plans", {"limit": 150})
    return {"summary": s, "plans": [p["activity"] for p in plans], "teachers": s.get("teacherNames", [])}


def metrics_from(state):
    if not state:
        return []
    s = state["summary"]
    c, total = s["teachers"]["counts"], s["teachers"]["total"]
    by = s["plans"]["byStatus"]
    out = [
        {"label": "Багшийн ирц өнөөдөр", "value": c.get("И", 0) + c.get("Х", 0), "total": total or None, "unit": "багш"},
        {"label": "Өвчтэй / чөлөөтэй", "value": c.get("Ө", 0) + c.get("Ч", 0), "total": None, "unit": "багш"},
        {"label": "Тасалсан", "value": c.get("Т", 0), "total": None, "unit": "багш"},
        {"label": f"Энэ сарын тэмдэглэл · {s['notes']['monthHours']} цаг", "value": s["notes"]["month"], "total": None, "unit": "ажил"},
        {"label": "Сарын төлөвлөгөө биелсэн", "value": by.get("биелсэн", 0), "total": s["plans"]["month"] or None, "unit": ""},
        {"label": "Хугацаа хэтэрсэн төлөвлөгөө", "value": len(s["plans"]["overdue"]), "total": None, "unit": ""},
    ]
    return out


# ---------------- Тушаал гүйцэтгэх ----------------
def _fill(template, month):
    n = now()
    return template.format(month=month, date=n.strftime("%Y-%m-%d"), time=n.strftime("%H%M"))


def run_command(name, params, files_root):
    cmd = get_command(name)
    params = {k: v for k, v in (params or {}).items() if str(v).strip()}
    for p in cmd.get("params", []):
        if not p.get("optional") and p["name"] not in params:
            raise ValueError(f"'{p['label']}' хоосон байна")
        if p.get("choices") and p["name"] in params and params[p["name"]] not in p["choices"]:
            raise ValueError(f"'{p['label']}' нь {p['choices']}-ийн нэг байх ёстой")
    if not is_running():
        start()
    act = cmd["action"]
    if act == "navigate":
        call("focus")
        return {"log": [f"«{params['tab']}» цонхыг нээлээ"], "result": call("navigate", {"tab": TABS[params["tab"]]})}
    if act == "export":
        month = params.get("month") or now().strftime("%Y-%m")
        path = os.path.join(files_root, cmd["folder"], _fill(cmd["file"], month))
        r = call("export", {"kind": cmd["kind"], "month": month, "path": path}, timeout=120)
        return {"log": [f"✓ Хадгалагдлаа: {r['path']}"], "result": r, "file": r["path"]}
    r = call(act, params) or {}
    undo = None
    if act == "set_attendance" and r.get("prev"):
        undo = {"type": "sm", "action": "set_attendance", "params": {"teacher": r["teacher"], "status": r["prev"], "date": r["date"]}}
    elif act == "set_plan_status" and r.get("prev"):
        undo = {"type": "sm", "action": "set_plan_status", "params": {"id": r.get("id"), "status": r["prev"]}}
    elif act == "add_note" and r.get("id"):
        undo = {"type": "sm", "action": "delete_note", "params": {"id": r["id"]}}
    elif act == "add_plan" and r.get("id"):
        undo = {"type": "sm", "action": "delete_plan", "params": {"id": r["id"]}}
    shown = " · ".join(str(v) for k, v in r.items() if k not in ("id", "prev"))
    return {"log": ["✓ " + shown], "result": r, "undo": undo}

