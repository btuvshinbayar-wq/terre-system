import datetime

from googleapiclient.discovery import build

from ..config import TZ, now
from .google_auth import creds


def today_events():
    s = build("calendar", "v3", credentials=creds(), cache_discovery=False)
    start = now().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + datetime.timedelta(days=1)
    res = s.events().list(
        calendarId="primary", timeMin=start.isoformat(), timeMax=end.isoformat(),
        singleEvents=True, orderBy="startTime",
    ).execute()
    out = []
    for e in res.get("items", []):
        st = e["start"].get("dateTime")
        if st:
            t = datetime.datetime.fromisoformat(st.replace("Z", "+00:00")).astimezone(TZ).strftime("%H:%M")
        else:
            t = "Өдөржин"
        out.append({"time": t, "title": e.get("summary", "(нэргүй)"),
                    "location": e.get("location", ""), "source": "Google"})
    return out
