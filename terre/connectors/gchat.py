"""Google Chat — зөвхөн Google Workspace данс. API-д 'уншаагүй' төлөв байхгүй тул сүүлийн 24 цагийн мессежийг авна."""
import datetime

from googleapiclient.discovery import build

from .google_auth import creds


def fetch_recent(hours=24):
    s = build("chat", "v1", credentials=creds(), cache_discovery=False)
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours))
    since_s = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for sp in s.spaces().list(pageSize=50).execute().get("spaces", []):
        msgs = s.spaces().messages().list(
            parent=sp["name"], filter=f'createTime > "{since_s}"',
            orderBy="createTime desc", pageSize=10,
        ).execute().get("messages", [])
        if not msgs:
            continue
        title = sp.get("displayName") or "Хувийн чат"
        lines = [f"{m.get('sender', {}).get('displayName', '?')}: {m.get('text', '')}" for m in reversed(msgs)]
        out.append({
            "id": f"gchat:{msgs[0]['name']}",
            "source": "gchat",
            "sender": title,
            "subject": "Google Chat" + (" (групп)" if sp.get("spaceType") == "SPACE" else ""),
            "snippet": lines[-1][:200],
            "body": "\n".join(lines),
            "received": msgs[0].get("createTime", ""),
            "meta": {"space": sp["name"]},
        })
    return out
