"""TED-ийн өөрийн тушаалууд (School Manager-ээс гадна): мэйл шалгах, Google Meet уулзалт, Google Drive.

Тушаалууд School Manager-ийн тушаалуудтай нэг жагсаалтад орж, самбар / дуу («Хэй Тэд») / Telegram-аас ажиллана.
"confirm": True гэсэн тушаал бусад хүнд мэдэгдэл (урилга, хуваалцсан тухай мэйл) илгээдэг тул дуут тушаалаар ч
шууд ажиллахгүй — самбар дээр таны ▶ Ажиллуулах товчийг хүлээнэ.
"""
import datetime
import io
import os

from .config import CFG, now, source_enabled

DRIVE_ROLES = {"Харах": "reader", "Сэтгэгдэл бичих": "commenter", "Засах": "writer"}
OPT = {"optional": True}

COMMANDS = [
    {"group": "TED: мэйл, календарь", "name": "Мэйл шалгах", "action": "check_mail",
     "description": "Бүх мэйл, чатыг одоо шалгаж, яаралтай болон хариу хүлээж буй мессежийн тоог хэлнэ", "params": []},
    {"group": "TED: мэйл, календарь", "name": "Уулзалт товлох (Google Meet)", "action": "meeting", "confirm": True,
     "description": "Google Calendar-т уулзалт нэмж Google Meet холбоос үүсгэнэ. Оролцогч бичвэл тэдэнд урилга очно",
     "params": [{"name": "title", "label": "Уулзалтын нэр"},
                {"name": "date", "label": "Огноо (YYYY-MM-DD)"},
                {"name": "time", "label": "Эхлэх цаг (HH:MM)"},
                {"name": "minutes", "label": "Үргэлжлэх хугацаа, минут (хоосон = 60)", **OPT},
                {"name": "attendees", "label": "Оролцогчдын мэйл (, тусгаарлана)", **OPT},
                {"name": "meet", "label": "Google Meet холбоос", "choices": ["Тийм", "Үгүй"], **OPT}]},
    {"group": "TED: Google Drive", "name": "Drive-д файл байршуулах", "action": "drive_upload",
     "description": "Компьютер дээрх файлыг Google Drive руу хуулна (эх файл хэвээр үлдэнэ)",
     "params": [{"name": "file", "label": "Файлын зам", "suggest": "docs"},
                {"name": "folder", "label": "Drive дахь хавтасны нэр (хоосон = My Drive)", **OPT}]},
    {"group": "TED: Google Drive", "name": "Drive-оос файл татах", "action": "drive_download",
     "description": "Drive-оос нэрээр нь хайж Documents\\Terre\\Drive хавтаст татна (Google Docs/Sheets-ийг Word/Excel болгоно)",
     "params": [{"name": "name", "label": "Файлын нэр (хэсэг нь ч болно)"}]},
    {"group": "TED: Google Drive", "name": "Drive файл хуваалцах", "action": "drive_share", "confirm": True,
     "description": "Drive дээрх файлыг тухайн хүнтэй хуваалцана (Google тэр хүнд мэдэгдэл илгээнэ)",
     "params": [{"name": "name", "label": "Файлын нэр"},
                {"name": "email", "label": "Хэнтэй (мэйл)"},
                {"name": "role", "label": "Эрх", "choices": list(DRIVE_ROLES), **OPT}]},
    {"group": "TED: Google Drive", "name": "Drive-оос файл хайх", "action": "drive_find",
     "description": "Drive дээрх файлуудыг нэрээр нь хайж жагсаана", "params": [{"name": "name", "label": "Хайх үг"}]},
]
NAMES = {c["name"] for c in COMMANDS}


def commands():
    out = []
    for c in COMMANDS:
        if c["action"] == "meeting" and not source_enabled("google_calendar"):
            continue
        if c["action"].startswith("drive_") and not source_enabled("google_drive"):
            continue
        out.append(c)
    return out


def get(name):
    return next(c for c in COMMANDS if c["name"] == name)


# ---------------- Google Drive ----------------
def _drive():
    from googleapiclient.discovery import build
    from .connectors.google_auth import creds
    return build("drive", "v3", credentials=creds(), cache_discovery=False)


def _esc(s):
    return str(s).replace("\\", "\\\\").replace("'", "\\'")


def _find(svc, name, limit=10):
    q = f"name contains '{_esc(name)}' and trashed = false and mimeType != 'application/vnd.google-apps.folder'"
    return svc.files().list(q=q, pageSize=limit, orderBy="modifiedTime desc",
                            fields="files(id,name,mimeType,modifiedTime,webViewLink,size)").execute().get("files", [])


def _one(svc, name):
    hits = _find(svc, name)
    exact = [f for f in hits if f["name"].lower() == name.lower()]
    if len(exact) == 1:
        return exact[0]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise RuntimeError(f"Drive дээр «{name}» нэртэй файл олдсонгүй")
    raise RuntimeError("Олон файл таарлаа, нэрийг тодруулна уу: " + "; ".join(f["name"] for f in hits[:6]))


def _folder_id(svc, name):
    q = f"name = '{_esc(name)}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    got = svc.files().list(q=q, pageSize=2, fields="files(id,name)").execute().get("files", [])
    if got:
        return got[0]["id"], False
    f = svc.files().create(body={"name": name, "mimeType": "application/vnd.google-apps.folder"}, fields="id").execute()
    return f["id"], True


EXPORT = {"application/vnd.google-apps.document": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
          "application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
          "application/vnd.google-apps.presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx")}


def drive_upload(p):
    from googleapiclient.http import MediaFileUpload
    path = os.path.expandvars(os.path.expanduser(p["file"].strip().strip('"')))
    if not os.path.isfile(path):
        raise RuntimeError(f"Файл олдсонгүй: {path}")
    svc = _drive()
    body = {"name": os.path.basename(path)}
    if p.get("folder"):
        fid, _ = _folder_id(svc, p["folder"])
        body["parents"] = [fid]
    f = svc.files().create(body=body, media_body=MediaFileUpload(path, resumable=True),
                           fields="id,name,webViewLink").execute()
    return {"log": [f"✓ Drive-д байршууллаа: {f['name']}", f"🔗 {f.get('webViewLink', '')}"],
            "undo": {"type": "drive", "op": "trash", "id": f["id"]}, "say": f"{f['name']} файлыг Drive-д байршууллаа"}


def drive_download(p, files_root):
    from googleapiclient.http import MediaIoBaseDownload
    svc = _drive()
    f = _one(svc, p["name"].strip())
    name = f["name"]
    if f["mimeType"] in EXPORT:
        mime, ext = EXPORT[f["mimeType"]]
        req = svc.files().export_media(fileId=f["id"], mimeType=mime)
        if not name.lower().endswith(ext):
            name += ext
    elif f["mimeType"].startswith("application/vnd.google-apps"):
        raise RuntimeError("Энэ төрлийн Google файлыг (форм, зураг төсөл г.м.) татах боломжгүй")
    else:
        req = svc.files().get_media(fileId=f["id"])
    folder = os.path.join(files_root, "Drive")
    os.makedirs(folder, exist_ok=True)
    safe = "".join("_" if ch in '\\/:*?"<>|' else ch for ch in name)
    dest, i = os.path.join(folder, safe), 2
    while os.path.exists(dest):
        b, e = os.path.splitext(os.path.join(folder, safe))
        dest, i = f"{b} ({i}){e}", i + 1
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    with open(dest, "wb") as out:
        out.write(buf.getvalue())
    return {"log": [f"✓ Татлаа: {dest}"], "file": dest, "say": f"{name} файлыг татаж Drive хавтаст хадгаллаа"}


def drive_share(p):
    svc = _drive()
    f = _one(svc, p["name"].strip())
    email = p["email"].strip()
    if "@" not in email:
        raise RuntimeError("Мэйл хаяг буруу байна")
    role = DRIVE_ROLES.get(p.get("role") or "Харах", "reader")
    perm = svc.permissions().create(fileId=f["id"], body={"type": "user", "role": role, "emailAddress": email},
                                    sendNotificationEmail=True, fields="id").execute()
    return {"log": [f"✓ «{f['name']}» файлыг {email}-тэй хуваалцлаа ({p.get('role') or 'Харах'})", f"🔗 {f.get('webViewLink', '')}"],
            "undo": {"type": "drive", "op": "unshare", "id": f["id"], "perm": perm["id"]},
            "say": f"{f['name']} файлыг хуваалцлаа"}


def drive_find(p):
    hits = _find(_drive(), p["name"].strip(), limit=10)
    if not hits:
        return {"log": ["Олдсонгүй"], "say": "Drive дээр тийм файл олдсонгүй"}
    lines = [f"• {f['name']} ({f.get('modifiedTime', '')[:10]})" for f in hits]
    return {"log": [f"Drive-аас {len(hits)} файл олдлоо:"] + lines,
            "say": f"{len(hits)} файл олдлоо. Хамгийн сүүлийнх нь {hits[0]['name']}"}


def drive_undo(u):
    svc = _drive()
    if u["op"] == "trash":
        svc.files().update(fileId=u["id"], body={"trashed": True}).execute()   # Drive-ийн хогийн сав (30 хоног)
    elif u["op"] == "unshare":
        svc.permissions().delete(fileId=u["id"], permissionId=u["perm"]).execute()


# ---------------- Уулзалт ----------------
def meeting(p):
    from googleapiclient.discovery import build
    from .connectors.google_auth import creds
    tz = CFG.get("timezone") or "Asia/Ulaanbaatar"
    try:
        start = datetime.datetime.strptime(f"{p['date'].strip()} {p['time'].strip()}", "%Y-%m-%d %H:%M")
    except ValueError:
        raise RuntimeError("Огноо YYYY-MM-DD, цаг HH:MM хэлбэрээр байх ёстой")
    mins = int(float(p.get("minutes") or 60))
    end = start + datetime.timedelta(minutes=mins)
    body = {"summary": p["title"].strip(), "description": "TED товлосон",
            "start": {"dateTime": start.isoformat(), "timeZone": tz},
            "end": {"dateTime": end.isoformat(), "timeZone": tz}}
    attendees = [a.strip() for a in str(p.get("attendees") or "").replace(";", ",").split(",") if "@" in a]
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]
    want_meet = (p.get("meet") or "Тийм") == "Тийм"
    if want_meet:
        body["conferenceData"] = {"createRequest": {"requestId": f"ted-{int(now().timestamp())}",
                                                    "conferenceSolutionKey": {"type": "hangoutsMeet"}}}
    ev = build("calendar", "v3", credentials=creds(), cache_discovery=False).events().insert(
        calendarId="primary", body=body, conferenceDataVersion=1 if want_meet else 0,
        sendUpdates="all" if attendees else "none").execute()
    link = ev.get("hangoutLink") or ""
    log = [f"✓ Календарьт нэмлээ: {body['summary']} — {start:%m/%d %H:%M}–{end:%H:%M}"]
    if link:
        log.append(f"🔗 Meet: {link}")
    if attendees:
        log.append(f"✉ Урилга очлоо: {', '.join(attendees)}")
    return {"log": log, "undo": {"type": "calendar", "provider": "google", "id": ev["id"]},
            "say": f"{body['summary']} уулзалтыг {start.month}-р сарын {start.day}-нд {start:%H:%M}-д товлолоо"
                   + (", Meet холбоос үүслээ" if link else "")}


def run(name, params, files_root):
    """Синхрон гүйцэтгэл (thread-д дуудагдана). check_mail-ийг engine async-аар хийнэ."""
    c = get(name)
    params = {k: str(v).strip() for k, v in (params or {}).items() if str(v).strip()}
    for p in c.get("params", []):
        if not p.get("optional") and p["name"] not in params:
            raise ValueError(f"'{p['label']}' хоосон байна")
    a = c["action"]
    if a == "meeting":
        return meeting(params)
    if a == "drive_upload":
        return drive_upload(params)
    if a == "drive_download":
        return drive_download(params, files_root)
    if a == "drive_share":
        return drive_share(params)
    if a == "drive_find":
        return drive_find(params)
    raise KeyError(name)
