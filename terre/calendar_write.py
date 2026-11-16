"""Календарьт үйл явдал нэмэх / устгах (Google эсвэл Outlook). Зөвхөн таны зөвшөөрлөөр дуудагдана."""
import datetime

from .config import CFG, DEMO, TZ, source_enabled


def target():
    t = (CFG.get("tasks") or {}).get("calendar_target", "auto")
    if t in ("google", "outlook"):
        return t
    if source_enabled("google_calendar"):
        return "google"
    if source_enabled("outlook"):
        return "outlook"
    return None


def _times(m):
    hhmm = m.get("time") or ""
    if hhmm:
        start = datetime.datetime.fromisoformat(f"{m['date']}T{hhmm}").replace(tzinfo=TZ)
        return start, start + datetime.timedelta(minutes=int(m.get("minutes") or 60)), False
    d = datetime.date.fromisoformat(m["date"])
    return d, d + datetime.timedelta(days=1), True


def create_event(m):
    """m: {date, time, title, location}. Буцаалтын мэдээлэл буцаана."""
    if DEMO:
        return {"type": "calendar", "provider": "demo", "id": "demo"}
    t = target()
    if not t:
        raise RuntimeError("Календарь холбогдоогүй байна (Google Calendar эсвэл Outlook)")
    start, end, allday = _times(m)
    if t == "google":
        from googleapiclient.discovery import build
        from .connectors.google_auth import creds
        body = {"summary": m["title"], "location": m.get("location", ""), "description": "TED нэмсэн",
                "start": {"date": start.isoformat()} if allday else {"dateTime": start.isoformat()},
                "end": {"date": end.isoformat()} if allday else {"dateTime": end.isoformat()}}
        ev = build("calendar", "v3", credentials=creds(), cache_discovery=False).events().insert(
            calendarId="primary", body=body).execute()
        return {"type": "calendar", "provider": "google", "id": ev["id"]}
    from .connectors import outlook
    if allday:
        body = {"subject": m["title"], "isAllDay": True,
                "start": {"dateTime": f"{start.isoformat()}T00:00:00", "timeZone": "UTC"},
                "end": {"dateTime": f"{end.isoformat()}T00:00:00", "timeZone": "UTC"}}
    else:
        u = datetime.timezone.utc
        body = {"subject": m["title"],
                "start": {"dateTime": start.astimezone(u).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
                "end": {"dateTime": end.astimezone(u).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"}}
    body["location"] = {"displayName": m.get("location", "")}
    ev = outlook._post("/me/events", body)
    return {"type": "calendar", "provider": "outlook", "id": ev.get("id")}


def delete_event(u):
    if u.get("provider") == "google":
        from googleapiclient.discovery import build
        from .connectors.google_auth import creds
        build("calendar", "v3", credentials=creds(), cache_discovery=False).events().delete(
            calendarId="primary", eventId=u["id"]).execute()
    elif u.get("provider") == "outlook":
        from .connectors import outlook
        outlook._post(f"/me/events/{u['id']}", None, method="DELETE")
