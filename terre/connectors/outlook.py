"""Outlook / Microsoft 365 — Microsoft Graph API (мэйл + календарь)."""
import datetime

import msal
import requests

from ..config import CFG, DATA, TZ, now

SCOPES = ["Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite"]
CACHE_FILE = DATA / "ms_token.json"
GRAPH = "https://graph.microsoft.com/v1.0"
_cache = msal.SerializableTokenCache()
_app = None


def _application():
    global _app
    if _app is None:
        if CACHE_FILE.exists():
            _cache.deserialize(CACHE_FILE.read_text(encoding="utf-8"))
        cid = CFG["sources"]["outlook"].get("client_id")
        if not cid:
            raise RuntimeError("config.yaml дээр outlook.client_id хоосон байна.")
        _app = msal.PublicClientApplication(
            cid, authority="https://login.microsoftonline.com/common", token_cache=_cache)
    return _app


def _save():
    if _cache.has_state_changed:
        CACHE_FILE.write_text(_cache.serialize(), encoding="utf-8")


def _token():
    app = _application()
    accts = app.get_accounts()
    r = app.acquire_token_silent(SCOPES, account=accts[0]) if accts else None
    if not r or "access_token" not in r:
        raise RuntimeError("Outlook-д нэвтрээгүй. `python -m terre.setup_auth` ажиллуулна уу.")
    _save()
    return r["access_token"]


def login():
    app = _application()
    flow = app.initiate_device_flow(scopes=SCOPES)
    print(flow["message"])  # "https://microsoft.com/devicelogin хаягаар орж XXXX кодыг оруул"
    r = app.acquire_token_by_device_flow(flow)
    if "access_token" not in r:
        raise SystemExit(f"Outlook нэвтрэлт амжилтгүй: {r.get('error_description')}")
    _save()
    print("Outlook: амжилттай нэвтэрлээ.")


def _get(path, **params):
    r = requests.get(GRAPH + path, headers={"Authorization": f"Bearer {_token()}"}, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _post(path, json=None, method="POST"):
    r = requests.request(method, GRAPH + path, headers={"Authorization": f"Bearer {_token()}"}, json=json, timeout=30)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        return {}


def fetch_unread(top=25):
    data = _get("/me/mailFolders/inbox/messages", **{
        "$filter": "isRead eq false", "$top": top, "$orderby": "receivedDateTime desc",
        "$select": "id,subject,from,receivedDateTime,bodyPreview,body,hasAttachments",
    })
    out = []
    for m in data.get("value", []):
        frm = (m.get("from") or {}).get("emailAddress", {})
        body = m.get("body", {}).get("content", "")
        if m.get("body", {}).get("contentType") == "html":
            import re
            body = re.sub(r"<[^>]+>", " ", body)
        out.append({
            "id": f"outlook:{m['id']}",
            "source": "outlook",
            "sender": frm.get("name") or frm.get("address", ""),
            "subject": m.get("subject") or "(гарчиггүй)",
            "snippet": m.get("bodyPreview", ""),
            "body": " ".join(body.split())[:8000],
            "received": _local(m.get("receivedDateTime")),
            "meta": {"msg_id": m["id"], "has_attachments": bool(m.get("hasAttachments"))},
        })
    return out


def _local(s):
    if not s:
        return ""
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(TZ).isoformat()


def apply_action(item, action):
    mid = item["meta"]["msg_id"]
    _post(f"/me/messages/{mid}", {"isRead": True}, method="PATCH")
    if action == "archive":
        moved = _post(f"/me/messages/{mid}/move", {"destinationId": "archive"})
        item["meta"]["archived_id"] = moved.get("id")   # Outlook зөөхөд ID өөрчлөгддөг
        return {"archived_id": moved.get("id")}


def unarchive(item):
    mid = item["meta"].get("archived_id") or item["meta"]["msg_id"]
    back = _post(f"/me/messages/{mid}/move", {"destinationId": "inbox"})
    _post(f"/me/messages/{back.get('id', mid)}", {"isRead": False}, method="PATCH")


def send_reply(item, body):
    mid = item["meta"]["msg_id"]
    conv = _get(f"/me/messages/{mid}", **{"$select": "conversationId"}).get("conversationId")
    _post(f"/me/messages/{mid}/reply", {"comment": body})
    _post(f"/me/messages/{mid}", {"isRead": True}, method="PATCH")
    return {"conversation_id": conv, "sent_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}


def thread_has_reply(track):
    data = _get("/me/messages", **{"$filter": f"conversationId eq '{track['conversation_id']}' and receivedDateTime gt {track['sent_at'][:19]}Z",
                                   "$select": "from,receivedDateTime", "$top": 10})
    me = (_get("/me", **{"$select": "mail,userPrincipalName"}) or {})
    mine = {(me.get("mail") or "").lower(), (me.get("userPrincipalName") or "").lower()}
    return any(((m.get("from") or {}).get("emailAddress", {}).get("address", "").lower() not in mine) for m in data.get("value", []))


def today_events():
    start = now().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + datetime.timedelta(days=1)
    data = _get("/me/calendarView", startDateTime=start.isoformat(), endDateTime=end.isoformat(),
                **{"$orderby": "start/dateTime", "$select": "subject,start,location,isAllDay"})
    out = []
    for e in data.get("value", []):
        if e.get("isAllDay"):
            t = "Өдөржин"
        else:
            # Graph анхдагчаар UTC буцаана
            st = datetime.datetime.fromisoformat(e["start"]["dateTime"][:19]).replace(tzinfo=datetime.timezone.utc)
            t = st.astimezone(TZ).strftime("%H:%M")
        out.append({"time": t, "title": e.get("subject", ""),
                    "location": (e.get("location") or {}).get("displayName", ""), "source": "Outlook"})
    return out


def download_attachments(item):
    import base64
    if not item["meta"].get("has_attachments"):
        return []
    data = _get(f"/me/messages/{item['meta']['msg_id']}/attachments")
    out = []
    for a in data.get("value", []):
        if a.get("@odata.type") != "#microsoft.graph.fileAttachment" or a.get("isInline"):
            continue
        out.append((a["name"], base64.b64decode(a["contentBytes"])))
    return out
