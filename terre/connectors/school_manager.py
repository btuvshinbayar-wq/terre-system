"""School Manager Lite холболт — TED Bridge (файлын шуудангийн хайрцаг).

School Manager Lite (Neutralino) асахдаа %APPDATA%\\TerreBridge\\school-manager.json-д нууц token,
хайрцгийн замыг бичиж, 5 секунд тутам "heartbeat" шинэчилнэ. TED тушаалаа inbox\\<id>.json-д бичээд,
outbox\\<id>.json-оос хариуг уншина. Бүх өөрчлөлт програмын өөрийн React state-ээр дамжиж хадгалагдана.

Програм хаалттай үед ч TED өгөгдлийн файлаас (sm-data-mirror.json) зөвхөн УНШИНА:
самбарын тоо, багш, төлөвлөгөөний жагсаалт. Өгөгдлийн файлд хэзээ ч бичихгүй.
Лиценз, Machine ID, Gemini түлхүүрийг уншихгүй, хадгалахгүй.
"""
import datetime
import glob
import json
import os
import secrets
import subprocess
import time

from ..config import CFG, now

STATUS = ["Ирсэн", "Өвчтэй", "Чөлөөтэй", "Тасалсан", "Хоцорсон"]
STATUS_CODE = {"И": "Ирсэн", "Ө": "Өвчтэй", "Ч": "Чөлөөтэй", "Т": "Тасалсан", "Х": "Хоцорсон"}
PLAN_STATUS = ["төлөвлөсөн", "хийгдэж байгаа", "биелсэн", "хойшилсон"]
NOTE_CATEGORIES = ["бүртгэл", "хурал цуглаан", "уулзалт", "зөвлөн туслах", "цахим систем", "сургалт",
                   "хөтөлбөр хэрэгжүүлэх", "өөрийн хөгжил", "тодорхойлолт", "шилжилт хөдөлгөөн", "амжилт", "бусад"]
TABS = {"Хяналтын самбар": "dashboard", "Календар": "calendar", "Төлөвлөгөө": "plan", "Тэмдэглэл": "notes",
        "Хөтөлбөрийн шинжилгээ": "curriculum", "Тайлан": "report", "Ирц & Цагийн хуваарь": "attendance",
        "Нэгтгэл": "consolidation", "Тохиргоо": "settings"}
PERIODS = {"Сар": "month", "7 хоног": "7days", "Улирал": "term", "Жил": "year"}
EVAL_TYPES = {"Жилийн төлөвлөгөө": "annual_plan", "Нэгж хичээл": "unit_plan", "Ээлжит хичээл": "lesson_plan"}
EVAL_TYPE_LABEL = {v: k for k, v in EVAL_TYPES.items()}
DAY_TYPES = {"Бүх нийтийн амралт": "official_holiday", "Сурагчдын амралт (багш ажиллана)": "vacation_workday",
             "Нөхөж хичээллэх өдөр": "teaching_workday"}
WORD_PDF = ["Word", "PDF"]

OPT = {"optional": True}
MONTH = {"name": "month", "label": "Сар (YYYY-MM, хоосон = энэ сар)", **OPT}
DATE = {"name": "date", "label": "Огноо (YYYY-MM-DD, хоосон = өнөөдөр)", **OPT}

# group: самбар дээр товчийг бүлэглэх; kind=export бол файл TED-ийн хавтаст хадгалагдана
COMMANDS = [
    # ---------- Ирц & цаг ----------
    {"group": "Ирц & цаг", "name": "Багшийн ирц тэмдэглэх", "action": "set_attendance",
     "description": "Багшийн өдрийн ирцийг тэмдэглэнэ (шалтгаан, хоцорсон минут, ороогүй цагтай)",
     "params": [{"name": "teacher", "label": "Багш", "suggest": "teachers"},
                {"name": "status", "label": "Төлөв", "choices": STATUS}, DATE,
                {"name": "note", "label": "Тайлбар", **OPT},
                {"name": "lateMinutes", "label": "Хоцорсон минут", **OPT},
                {"name": "excusedHours", "label": "Зайлшгүй шалтгаанаар ороогүй цаг", **OPT},
                {"name": "excusedReason", "label": "Зайлшгүй шалтгаан (олимпиад, сургалт…)", **OPT},
                {"name": "unexcusedHours", "label": "Шалтгаангүй ороогүй цаг", **OPT}]},
    {"group": "Ирц & цаг", "name": "Бүгд ирсэн гэж бүртгэх", "action": "set_attendance_all_present",
     "description": "Тухайн өдөр ирц бүртгэгдээгүй бүх багшийг «Ирсэн» болгоно (бүртгэлтэйг өөрчлөхгүй)",
     "params": [DATE]},
    {"group": "Ирц & цаг", "name": "Сарын нэмэлт цаг оруулах", "action": "set_month_adjustment",
     "description": "Орлон заасан, нэмэлт илүү цаг, өмнөх сарын зөрүүг тухайн сард оруулна",
     "params": [{"name": "teacher", "label": "Багш", "suggest": "teachers"}, MONTH,
                {"name": "substitutedHours", "label": "Орлон заасан цаг", **OPT},
                {"name": "overtimeHours", "label": "Нэмэлт заасан (илүү) цаг", **OPT},
                {"name": "priorAdjustmentHours", "label": "Өмнөх сарын зөрүү цаг (+/-)", **OPT},
                {"name": "note", "label": "Тайлбар", **OPT}]},
    {"group": "Ирц & цаг", "name": "Цагийн тооцоо (Excel)", "action": "export_timesheet", "kind": "export",
     "folder": "Тайлан", "file": "Цагийн тооцоо {month}.xlsx",
     "description": "Сарын багш нарын цагийн тооцоог програмын дэлгэцтэй ижил тоогоор Excel-ээр гаргана",
     "params": [MONTH]},
    {"group": "Ирц & цаг", "name": "Сарын цагийн тооцоо хаах", "action": "lock_month",
     "description": "Цагийн тооцоог хаасан өдрийг тэмдэглэнэ (дараа сарын хаалтын зөрүүнд ашиглана)",
     "params": [MONTH, {"name": "date", "label": "Хаах өдөр (хоосон = тухайн сарын 25)", **OPT},
                {"name": "note", "label": "Тайлбар", **OPT}]},
    {"group": "Ирц & цаг", "name": "Сарын хаалт цуцлах", "action": "unlock_month",
     "description": "Тухайн сарын цагийн тооцооны хаалтыг цуцалж дахин засах боломжтой болгоно",
     "params": [MONTH]},

    # ---------- Тэмдэглэл & төлөвлөгөө ----------
    {"group": "Тэмдэглэл & төлөвлөгөө", "name": "Ажлын тэмдэглэл нэмэх", "action": "add_note",
     "description": "Хийсэн ажлаа өдрийн тэмдэглэлд бүртгэнэ",
     "params": [{"name": "title", "label": "Юу хийсэн"},
                {"name": "category", "label": "Ангилал", "choices": NOTE_CATEGORIES},
                {"name": "hours", "label": "Зарцуулсан цаг", **OPT},
                {"name": "participants", "label": "Оролцогчийн тоо", **OPT},
                {"name": "result", "label": "Үр дүн, дүгнэлт", **OPT},
                {"name": "caution", "label": "Анхаарах зүйл", **OPT},
                {"name": "suggestion", "label": "Сайжруулах санал", **OPT},
                {"name": "plan", "label": "Холбогдох төлөвлөгөө", "suggest": "plans", **OPT},
                DATE, {"name": "startTime", "label": "Эхэлсэн цаг (HH:MM)", **OPT}]},
    {"group": "Тэмдэглэл & төлөвлөгөө", "name": "Төлөвлөгөө нэмэх", "action": "add_plan",
     "description": "Сарын эсвэл жилийн төлөвлөгөөнд шинэ ажил нэмнэ",
     "params": [{"name": "activity", "label": "Үйл ажиллагаа"},
                {"name": "type", "label": "Төрөл", "choices": ["сарын", "жилийн"], **OPT},
                {"name": "startDate", "label": "Эхлэх огноо (YYYY-MM-DD)", **OPT},
                {"name": "endDate", "label": "Дуусах огноо", **OPT},
                {"name": "goal", "label": "Зорилго", **OPT},
                {"name": "responsibleUnit", "label": "Хариуцах нэгж", **OPT},
                {"name": "expectedResult", "label": "Хүрэх үр дүн", **OPT}]},
    {"group": "Тэмдэглэл & төлөвлөгөө", "name": "Төлөвлөгөөний төлөв солих", "action": "set_plan_status",
     "description": "Төлөвлөгөөг биелсэн, хойшилсон гэх мэтээр тэмдэглэнэ",
     "params": [{"name": "plan", "label": "Төлөвлөгөө", "suggest": "plans"},
                {"name": "status", "label": "Төлөв", "choices": PLAN_STATUS}]},
    {"group": "Тэмдэглэл & төлөвлөгөө", "name": "Төлөвлөгөө (Excel)", "action": "export_plans_xlsx", "kind": "export",
     "folder": "Тайлан", "file": "Төлөвлөгөө {month_or_all}.xlsx",
     "description": "Төлөвлөгөөг Excel-ээр гаргана (сар заавал бүгдийг)",
     "params": [{"name": "month", "label": "Сар (YYYY-MM, хоосон = бүгд)", **OPT}]},

    # ---------- Тайлан ----------
    {"group": "Тайлан", "name": "Нэгдсэн ажлын тайлан", "action": "export_report", "kind": "export",
     "folder": "Тайлан", "file": "Ажлын тайлан {period_label} {month}.{ext}", "formats": ["Word", "PDF", "PowerPoint"],
     "description": "Тайлан цэсний нэгдсэн тайланг (тэмдэглэл, төлөвлөгөө, хөтөлбөр, ирц) гаргана",
     "params": [{"name": "period", "label": "Хугацаа", "choices": list(PERIODS), **OPT}, MONTH,
                {"name": "format", "label": "Хэлбэр", "choices": ["Word", "PDF", "PowerPoint"], **OPT}]},

    # ---------- Хөтөлбөрийн шинжилгээ ----------
    {"group": "Хөтөлбөр & ажиглалт", "name": "Төлөвлөгөөний файл шинжлэх", "action": "curriculum_open_file",
     "description": "Багшийн нэгж/ээлжит/жилийн төлөвлөгөөний Word/PDF файлыг шинжилгээний цонхонд ачаална. "
                    "«Шинжилгээ», «Хадгалах» товчийг та School Manager дээр дарна",
     "params": [{"name": "file", "label": "Файлын зам (.docx / .pdf)", "suggest": "docs"},
                {"name": "teacher", "label": "Багш", "suggest": "teachers", **OPT},
                {"name": "type", "label": "Төрөл", "choices": list(EVAL_TYPES), **OPT}]},
    {"group": "Хөтөлбөр & ажиглалт", "name": "Хөтөлбөр импортлох", "action": "curriculum_import_file",
     "description": "Word/Excel/PDF хөтөлбөрийг импортын цонхонд задлан ачаална (хадгалахыг та шийднэ)",
     "params": [{"name": "file", "label": "Файлын зам (.docx / .xlsx / .pdf)", "suggest": "docs"}]},
    {"group": "Хөтөлбөр & ажиглалт", "name": "Хөтөлбөрийн шинжилгээ (Word)", "action": "export_curriculum_eval",
     "kind": "export", "folder": "Тайлан", "file": "Хөтөлбөрийн шинжилгээ - {label}.{ext}", "formats": WORD_PDF,
     "description": "Хадгалсан хөтөлбөрийн шинжилгээг албан ёсны Word/PDF болгоно",
     "params": [{"name": "evaluation", "label": "Хөтөлбөр", "suggest": "evaluations"},
                {"name": "format", "label": "Хэлбэр", "choices": WORD_PDF, **OPT}]},
    {"group": "Хөтөлбөр & ажиглалт", "name": "Ажиглалтын хуудас (Word)", "action": "export_observation",
     "kind": "export", "folder": "Тайлан", "file": "Хичээлийн ажиглалт - {label}.{ext}", "formats": WORD_PDF,
     "description": "Хичээлийн ажиглалтын албан ёсны хуудсыг (11 шалгуур) Word/PDF болгоно",
     "params": [{"name": "observation", "label": "Ажиглалт", "suggest": "observations"},
                {"name": "format", "label": "Хэлбэр", "choices": WORD_PDF, **OPT}]},
    {"group": "Хөтөлбөр & ажиглалт", "name": "Давтагдсан сул тал (Word)", "action": "export_weakness_audit",
     "kind": "export", "folder": "Тайлан", "file": "Давтагдсан сул тал - {label}.{ext}", "formats": WORD_PDF,
     "description": "Багшийн хөтөлбөр, ажиглалтаас давтагдсан сул талын тайланг гаргана",
     "params": [{"name": "teacher", "label": "Багш", "suggest": "curriculum_teachers"},
                {"name": "format", "label": "Хэлбэр", "choices": WORD_PDF, **OPT}]},
    {"group": "Хөтөлбөр & ажиглалт", "name": "Ажиглалтын хуудас нээх", "action": "open_observation_form",
     "description": "School Manager дээр хичээлийн ажиглалтын шинэ хуудсыг нээнэ",
     "params": [{"name": "teacher", "label": "Багш", "suggest": "teachers", **OPT}]},

    # ---------- Нэгтгэл ----------
    {"group": "Нэгтгэл", "name": "Өөрийн тайлангийн багц (.json)", "action": "consolidation_export_self",
     "kind": "export", "folder": "Тайлан", "file": "Менежерийн тайлан {date}.json",
     "description": "Ахлах менежерт илгээх өөрийн тайлангийн файлыг гаргана", "params": []},
    {"group": "Нэгтгэл", "name": "Менежерүүдийн тайлан нэгтгэх", "action": "consolidation_merge", "kind": "export",
     "folder": "Тайлан", "file": "Нэгдсэн тайлан {date}.{ext}", "formats": WORD_PDF,
     "description": "Бусад менежерийн .json файлуудыг өөрийнхтэйгээ нэгтгэж давхардалгүй тайлан гаргана",
     "params": [{"name": "files", "label": "Файлуудын зам (; тусгаарлана)", "suggest": "jsons"},
                {"name": "format", "label": "Хэлбэр", "choices": WORD_PDF, **OPT}]},

    # ---------- Тохиргоо & нөөц ----------
    {"group": "Тохиргоо & нөөц", "name": "Амралтын өдөр нэмэх", "action": "add_day_override",
     "description": "Бүх нийтийн амралт, сурагчдын амралт, нөхөж хичээллэх өдрийг тохиргоонд нэмнэ",
     "params": [{"name": "date", "label": "Огноо (YYYY-MM-DD)"},
                {"name": "type", "label": "Төрөл", "choices": list(DAY_TYPES)},
                {"name": "title", "label": "Тайлбар (баярын нэр г.м.)"}]},
    {"group": "Тохиргоо & нөөц", "name": "Бүрэн нөөцлөл хийх", "action": "export_backup", "kind": "export",
     "folder": "Нөөцлөл", "file": "School Manager нөөц {date} {time}.json",
     "description": "Бүх өгөгдлийн нөөц хуулбар хадгална (лицензийн мэдээлэлгүй)", "params": []},
    {"group": "Тохиргоо & нөөц", "name": "Багшийн хуваарь (JSON)", "action": "export_weekly_schedule", "kind": "export",
     "folder": "Тайлан", "file": "Багшийн 7 хоногийн хуваарь {date}.json",
     "description": "Багш нарын гарагийн хичээлийн цагийн хуваарийг JSON-оор гаргана", "params": []},
    {"group": "Тохиргоо & нөөц", "name": "Цонх нээх", "action": "navigate",
     "description": "School Manager-ийн тухайн цэсийг нээж харуулна",
     "params": [{"name": "tab", "label": "Цэс", "choices": list(TABS)}]},
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


# ======================= Bridge (файлын хайрцаг) =======================
HEARTBEAT_MAX_AGE = 30  # сек


def _appdata():
    return os.environ.get("APPDATA") or os.path.expanduser("~")


def _info_path():
    return os.path.join(_appdata(), "TerreBridge", "school-manager.json")


def _read_json(path, tries=3):
    for i in range(tries):
        try:
            with open(path, encoding="utf-8-sig") as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, OSError):
            if i == tries - 1:
                return None
            time.sleep(0.15)   # програм яг бичиж байх үед
    return None


def _info():
    info = _read_json(_info_path())
    if not info or info.get("transport") != "file" or not info.get("token"):
        return None
    return info


def _alive(info):
    try:
        hb = datetime.datetime.fromisoformat(str(info.get("heartbeat", "")).replace("Z", "+00:00"))
    except ValueError:
        return False
    age = (datetime.datetime.now(datetime.timezone.utc) - hb).total_seconds()
    return age < HEARTBEAT_MAX_AGE


def is_running():
    info = _info()
    return bool(info and _alive(info))


def call(action, params=None, timeout=90):
    info = _info()
    if not info or not _alive(info):
        raise RuntimeError("School Manager хаалттай байна (эсвэл TED Bridge-тэй шинэ хувилбар суугаагүй)")
    inbox, outbox = info["inbox"], info["outbox"]
    cid = f"t{int(time.time() * 1000)}_{secrets.token_hex(4)}"
    msg = {"id": cid, "token": info["token"], "ts": int(time.time() * 1000), "action": action, "params": params or {}}
    tmp, req = os.path.join(inbox, cid + ".tmp"), os.path.join(inbox, cid + ".json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(msg, f, ensure_ascii=False)
    os.replace(tmp, req)
    out = os.path.join(outbox, cid + ".json")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(out):
            data = _read_json(out)
            if data is not None:
                try:
                    os.remove(out)   # TED-ийн өөрийн түр хариу файл
                except OSError:
                    pass
                if not data.get("ok"):
                    raise RuntimeError(data.get("error", "Тодорхойгүй алдаа"))
                return data.get("result")
        time.sleep(0.2)
    try:
        if os.path.exists(req):
            os.remove(req)   # гүйцэтгэгдээгүй өөрийн тушаалыг буцааж авна
    except OSError:
        pass
    raise RuntimeError("School Manager хариу өгсөнгүй (програм гацсан эсвэл лицензийн цонх нээлттэй байж магадгүй)")


def find_exe():
    cand = [SM().get("exe")] if SM().get("exe") else []
    cand += [r"C:\Program Files\SchoolManager\SchoolManager.exe",
             r"C:\Program Files (x86)\SchoolManager\SchoolManager.exe",
             os.path.expandvars(r"%LOCALAPPDATA%\Programs\SchoolManager\SchoolManager.exe")]
    cand += glob.glob(r"C:\Program Files*\School*Manager*\*.exe")
    for c in cand:
        if c and os.path.exists(os.path.expandvars(c)) and "unins" not in c.lower():
            return os.path.expandvars(c)
    return None


def start(wait=60):
    if is_running():
        call("focus")
        return True
    exe = find_exe()
    if not exe:
        raise RuntimeError("SchoolManager.exe олдсонгүй. config.yaml → school_manager.exe-д замыг бичнэ үү")
    subprocess.Popen([exe], cwd=os.path.dirname(exe))
    for _ in range(wait):
        time.sleep(1)
        if is_running():
            try:
                call("ping", timeout=15)
                return True
            except RuntimeError:
                pass
    raise RuntimeError("School Manager асаалаа, гэвч TED Bridge хариу өгсөнгүй (TED-тэй хувилбар суулгасан эсэхийг шалгана уу)")


# ======================= Өгөгдлийн файл (зөвхөн унших) =======================
MIRROR = "sm-data-mirror.json"
_cache = {"path": None, "mtime": None, "data": None}


def data_dir():
    """Өгөгдлийн хавтас: config → програмын мэдээлэл → data-location.json → анхдагч."""
    if SM().get("data_dir"):
        return os.path.expandvars(os.path.expanduser(SM()["data_dir"]))
    info = _read_json(_info_path()) or {}
    if info.get("dataDir"):
        return info["dataDir"]
    bases = [os.path.join(_appdata(), n) for n in ("school-manager", "School Manager")]
    for base in bases:
        loc = _read_json(os.path.join(base, "data-location.json")) or {}
        if isinstance(loc.get("dir"), str) and loc["dir"].strip() and os.path.isdir(loc["dir"].strip()):
            return loc["dir"].strip()
    for base in bases:
        if os.path.exists(os.path.join(base, MIRROR)):
            return base
    return bases[0]


def diagnose():
    """'Систем' табын эрүүл мэндэд: (төлөв, тайлбар, засах заавар)."""
    info = _read_json(_info_path())
    f = data_file()
    if info and info.get("transport") == "file" and _alive(info):
        return "ok", "Програм нээлттэй, TED Bridge холбогдсон", ""
    where = f"Өгөгдөл: {f}" if f else f"Өгөгдлийн файл олдсонгүй ({data_dir()})"
    if not info:
        return ("warn" if f else "error"), f"Програм TED Bridge-гүй эсвэл хэзээ ч асаагүй. {where}", \
            "School Manager-ийн шинэ кодоор (git pull → build-neutralino.bat) Lite installer хийж суулгаад програмаа нээнэ үү" \
            + ("" if f else ". config.yaml → school_manager.data_dir-д өгөгдлийн хавтсыг бичнэ үү")
    return ("warn" if f else "error"), f"Програм хаалттай. {where}", \
        "School Manager-ийг нээнэ үү" + ("" if f else ". config.yaml → school_manager.data_dir-д өгөгдлийн хавтсыг бичнэ үү")


def data_file():
    d = data_dir()
    for name in (MIRROR, MIRROR + ".prev"):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def read_data():
    """sm-data-mirror.json-ийн 'data' хэсэг (лиценз, түлхүүргүй). Файл байхгүй бол None."""
    p = data_file()
    if not p:
        return None
    try:
        mtime = os.path.getmtime(p)
    except OSError:
        return None
    if _cache["path"] == p and _cache["mtime"] == mtime:
        return _cache["data"]
    raw = _read_json(p)
    if not raw:
        return _cache["data"] if _cache["path"] == p else None
    data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    st = dict(data.get("settings") or {})
    for k in ("geminiApiKey", "licenseKey", "licenseValidUntil", "machineId", "managerSignature"):
        st.pop(k, None)
    out = {k: data.get(k) or [] for k in ("plans", "notes", "teachers", "curriculumEvaluations", "lessonObservations")}
    out["settings"] = st
    out["exportDate"] = raw.get("exportDate")
    _cache.update(path=p, mtime=mtime, data=out)
    return out


def eval_label(e):
    return f"{e.get('teacherName', '')} · {EVAL_TYPE_LABEL.get(e.get('type'), e.get('type', ''))} · {e.get('topic', '')} ({e.get('date', '')})"


def obs_label(o):
    return f"{o.get('teacherName', '')} · {o.get('className', '')} · {o.get('topic', '')} ({o.get('date', '')})"


def _overlaps(p, start, end):
    s = p.get("startDate") or p.get("endDate") or ""
    e = p.get("endDate") or p.get("startDate") or ""
    return bool(s) and s <= end and e >= start


def summary_from_data(data, date=None):
    """Програм хаалттай үед файлаас тооцох товч (bridge-ийн summary-тэй ижил бүтэц)."""
    date = date or now().strftime("%Y-%m-%d")
    counts = {"И": 0, "Ө": 0, "Ч": 0, "Т": 0, "Х": 0}
    absent = []
    for t in data["teachers"]:
        s = (t.get("attendanceRecords") or {}).get(date) or "И"
        counts[s] = counts.get(s, 0) + 1
        if s != "И":
            absent.append({"name": t.get("fullName", ""), "status": STATUS_CODE.get(s, s)})
    m0 = date[:7] + "-01"
    y, m = int(date[:4]), int(date[5:7])
    nxt = datetime.date(y + (m == 12), m % 12 + 1, 1)
    m1 = (nxt - datetime.timedelta(days=1)).isoformat()
    month_notes = [n for n in data["notes"] if m0 <= (n.get("startDate") or "")[:10] <= m1]
    month_plans = [p for p in data["plans"] if _overlaps(p, m0, m1)]
    by = {}
    for p in month_plans:
        by[p.get("status")] = by.get(p.get("status"), 0) + 1
    in7 = (datetime.date.fromisoformat(date) + datetime.timedelta(days=7)).isoformat()
    overdue = sorted([p for p in data["plans"] if p.get("endDate") and p["endDate"] < date
                      and p.get("status") not in ("биелсэн", "хойшилсон")], key=lambda p: p["endDate"])
    upcoming = sorted([p for p in data["plans"] if date <= (p.get("startDate") or "") <= in7
                       and p.get("status") != "биелсэн"], key=lambda p: p["startDate"])
    evals = data["curriculumEvaluations"]
    return {
        "date": date,
        "teachers": {"total": len(data["teachers"]), "counts": counts, "absent": absent},
        "notes": {"month": len(month_notes), "monthHours": round(sum(float(n.get("spentHours") or 0) for n in month_notes), 1),
                  "today": sum(1 for n in data["notes"] if (n.get("startDate") or "").startswith(date))},
        "plans": {"month": len(month_plans), "byStatus": by,
                  "overdue": [{"activity": p.get("activity"), "endDate": p.get("endDate")} for p in overdue[:15]],
                  "upcoming": [{"activity": p.get("activity"), "startDate": p.get("startDate")} for p in upcoming[:15]]},
        "curriculum": {"total": len(evals), "needsRevision": sum(1 for e in evals if e.get("status") == "needs_revision")},
        "observations": {"total": len(data["lessonObservations"])},
    }


def agenda_from_data(data, date=None, days=7):
    """Самбарын «Яаралтай» хэсэгт: өнөөдрийн, ойрын 7 хоногийн, хугацаа хэтэрсэн төлөвлөгөө (биелээгүй)."""
    date = date or now().strftime("%Y-%m-%d")
    until = (datetime.date.fromisoformat(date) + datetime.timedelta(days=days)).isoformat()
    closed = ("биелсэн", "хойшилсон")

    def row(p):
        return {"id": p.get("id"), "activity": p.get("activity", ""), "startDate": p.get("startDate", ""),
                "endDate": p.get("endDate", ""), "status": (p.get("status") or "").replace("_", " ")}
    open_ = [p for p in data["plans"] if p.get("status") not in closed and p.get("activity")]
    today = [p for p in open_ if _overlaps(p, date, date)]
    upcoming = [p for p in open_ if date < (p.get("startDate") or "") <= until]
    overdue = [p for p in open_ if (p.get("endDate") or p.get("startDate") or "9") < date]
    key = lambda p: (p.get("startDate") or "", p.get("activity") or "")
    return {"today": [row(p) for p in sorted(today, key=key)],
            "upcoming": [row(p) for p in sorted(upcoming, key=key)],
            "overdue": [row(p) for p in sorted(overdue, key=lambda p: p.get("endDate") or "")]}


def _lists(data):
    if not data:
        return {}
    cur_teachers = sorted({(x.get("teacherName") or "").strip() for x in data["curriculumEvaluations"] + data["lessonObservations"]} - {""})
    evals = sorted(data["curriculumEvaluations"], key=lambda e: e.get("date") or "", reverse=True)
    obs = sorted(data["lessonObservations"], key=lambda o: o.get("date") or "", reverse=True)
    return {
        "teachers": [t.get("fullName", "") for t in data["teachers"] if t.get("fullName")],
        "plans": [p.get("activity", "") for p in data["plans"] if p.get("activity")],
        "evaluations": [eval_label(e) for e in evals[:300]],
        "observations": [obs_label(o) for o in obs[:300]],
        "curriculum_teachers": cur_teachers,
    }


def fetch_state():
    """Самбар, өглөөний мэдээнд хэрэгтэй бүх зүйл. Өгөгдөлгүй бол None."""
    running = is_running()
    data = read_data()
    summary = None
    if running:
        try:
            summary = call("summary", timeout=20)
        except RuntimeError:
            summary = None
    if summary is None and data:
        summary = summary_from_data(data)
    if summary is None:
        return None
    return {"summary": summary, "running": running, "source": "app" if running else "file",
            "data_file": data_file(), "agenda": agenda_from_data(data) if data else None, **_lists(data)}


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
    cur = s.get("curriculum")
    if cur and cur.get("total"):
        out.append({"label": "Засварлах хөтөлбөр", "value": cur.get("needsRevision", 0), "total": cur["total"], "unit": ""})
    return out


# ======================= Тушаал гүйцэтгэх =======================
def _safe_name(s, limit=80):
    s = "".join("_" if ch in '\\/:*?"<>|' else ch for ch in str(s)).strip()
    return " ".join(s.split())[:limit] or "файл"


def _unique(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f"{base} ({i}){ext}"):
        i += 1
    return f"{base} ({i}){ext}"


def _to_pdf(docx_path):
    """Word файлыг Microsoft Word-оор PDF болгоно (Word суусан байх шаардлагатай). Word файл хэвээр үлдэнэ."""
    pdf = _unique(os.path.splitext(docx_path)[0] + ".pdf")
    ps = ("$ErrorActionPreference='Stop'; $w=New-Object -ComObject Word.Application; $w.Visible=$false; "
          "try { $d=$w.Documents.Open($env:TERRE_IN, $false, $true); $d.SaveAs([ref]$env:TERRE_OUT, [ref]17); $d.Close($false) } "
          "finally { $w.Quit() }")
    env = {**os.environ, "TERRE_IN": docx_path, "TERRE_OUT": pdf}
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env=env,
                       capture_output=True, text=True, timeout=180,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0 or not os.path.exists(pdf):
        raise RuntimeError("PDF болгож чадсангүй (Microsoft Word суусан эсэхийг шалгана уу). Word файл хадгалагдсан.")
    return pdf


def _export_path(cmd, params, files_root):
    fmt = params.get("format") or "Word"
    ext = {"Word": "docx", "PDF": "docx", "PowerPoint": "pptx"}.get(fmt, "docx")
    month = params.get("month") or now().strftime("%Y-%m")
    period = params.get("period") or "Сар"
    label = params.get("evaluation") or params.get("observation") or params.get("teacher") or ""
    name = cmd["file"].format(
        month=month if period in ("Сар", "7 хоног") else now().strftime("%Y-%m-%d"),
        month_or_all=params.get("month") or "бүгд",
        period_label={"Сар": "", "7 хоног": "7 хоног", "Улирал": "улирал", "Жил": "жил"}.get(period, ""),
        date=now().strftime("%Y-%m-%d"), time=now().strftime("%H%M"), label=_safe_name(label, 60), ext=ext)
    folder = os.path.join(files_root, cmd["folder"])
    os.makedirs(folder, exist_ok=True)
    return _unique(os.path.join(folder, _safe_name(" ".join(name.split()), 150)))


def _bridge_params(cmd, params):
    """Самбарын утгыг bridge-ийн параметр болгоно."""
    p = dict(params)
    act = cmd["action"]
    if act == "navigate":
        p["tab"] = TABS[p["tab"]]
    if "period" in p:
        p["period"] = PERIODS.get(p["period"], "month")
    if act == "curriculum_open_file" and p.get("type"):
        p["type"] = EVAL_TYPES[p["type"]]
    if act == "add_day_override":
        p["type"] = DAY_TYPES[p["type"]]
    if act == "export_report":
        p["format"] = "pptx" if params.get("format") == "PowerPoint" else "docx"
    if act == "consolidation_merge":
        p["files"] = [f.strip().strip('"') for f in str(params.get("files", "")).replace("\n", ";").split(";") if f.strip()]
    if act in ("export_curriculum_eval", "export_observation", "export_weakness_audit", "consolidation_merge"):
        p.pop("format", None)
    return p


def run_command(name, params, files_root):
    cmd = get_command(name)
    params = {k: str(v).strip() for k, v in (params or {}).items() if str(v).strip()}
    for p in cmd.get("params", []):
        if not p.get("optional") and p["name"] not in params:
            raise ValueError(f"'{p['label']}' хоосон байна")
        if p.get("choices") and p["name"] in params and params[p["name"]] not in p["choices"]:
            raise ValueError(f"'{p['label']}' нь {p['choices']}-ийн нэг байх ёстой")
    if not is_running():
        start()
    act = cmd["action"]
    bp = _bridge_params(cmd, params)
    if cmd.get("kind") == "export":
        path = _export_path(cmd, params, files_root)
        r = call(act, {**bp, "path": path}, timeout=240) or {}
        saved = r.get("path") or path
        log = [f"✓ Хадгалагдлаа: {saved}"]
        if params.get("format") == "PDF" and saved.lower().endswith(".docx"):
            saved = _to_pdf(saved)
            log.append(f"✓ PDF: {saved}")
        return {"log": log, "result": r, "file": saved}
    if act in ("navigate", "curriculum_open_file", "curriculum_import_file", "open_observation_form"):
        call("focus")
    r = call(act, bp, timeout=120) or {}
    undo = r.pop("undo", None) if isinstance(r, dict) else None
    shown = " · ".join(str(v) for k, v in r.items() if k not in ("id", "teacherId") and v not in (None, "", True)) \
        if isinstance(r, dict) else str(r)
    log = ["✓ " + (shown or name)]
    if act in ("curriculum_open_file", "curriculum_import_file"):
        log.append("School Manager дээр шалгаад «Шинжилгээ» / «Хадгалах» товчийг дарна уу")
    return {"log": log, "result": r,
            "undo": {"type": "sm", "action": undo["action"], "params": undo["params"]} if undo else None}
