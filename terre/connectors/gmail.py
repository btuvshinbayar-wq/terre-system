import base64
from email.message import EmailMessage
from email.utils import parseaddr

from googleapiclient.discovery import build

from .google_auth import creds

_svc = None


def svc():
    global _svc
    if _svc is None:
        _svc = build("gmail", "v1", credentials=creds(), cache_discovery=False)
    return _svc


def _body(payload):
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"] + "==").decode("utf-8", "ignore")
    for p in payload.get("parts", []) or []:
        b = _body(p)
        if b:
            return b
    return ""


def _attachments(payload, out=None):
    out = [] if out is None else out
    for p in payload.get("parts", []) or []:
        b = p.get("body", {})
        if p.get("filename") and b.get("attachmentId"):
            out.append({"id": b["attachmentId"], "filename": p["filename"], "size": b.get("size", 0),
                        "mime": p.get("mimeType", "")})
        _attachments(p, out)
    return out


def fetch_unread(max_results=25):
    s = svc()
    res = s.users().messages().list(
        userId="me", q="is:unread in:inbox newer_than:3d", maxResults=max_results
    ).execute()
    out = []
    for m in res.get("messages", []):
        full = s.users().messages().get(userId="me", id=m["id"], format="full").execute()
        h = {x["name"].lower(): x["value"] for x in full["payload"].get("headers", [])}
        name, addr = parseaddr(h.get("from", ""))
        out.append({
            "id": f"gmail:{m['id']}",
            "source": "gmail",
            "sender": name or addr,
            "subject": h.get("subject", "(гарчиггүй)"),
            "snippet": full.get("snippet", ""),
            "body": _body(full["payload"])[:8000] or full.get("snippet", ""),
            "received": _iso(int(full.get("internalDate", 0))),
            "meta": {
                "msg_id": m["id"], "thread_id": full.get("threadId"),
                "rfc_id": h.get("message-id", ""), "references": h.get("references", ""),
                "reply_to": h.get("reply-to") or h.get("from", ""),
                "subject": h.get("subject", ""),
                "attachments": _attachments(full["payload"]),
            },
        })
    return out


def _iso(ms):
    import datetime
    from ..config import TZ
    return datetime.datetime.fromtimestamp(ms / 1000, TZ).isoformat()


def apply_action(item, action):
    mid = item["meta"]["msg_id"]
    remove = ["UNREAD"] + (["INBOX"] if action == "archive" else [])
    svc().users().messages().modify(userId="me", id=mid, body={"removeLabelIds": remove}).execute()


def unarchive(item):
    svc().users().messages().modify(userId="me", id=item["meta"]["msg_id"],
                                    body={"addLabelIds": ["INBOX", "UNREAD"]}).execute()


def send_reply(item, body):
    m = item["meta"]
    msg = EmailMessage()
    msg["To"] = m["reply_to"]
    subj = m.get("subject", "")
    msg["Subject"] = subj if subj.lower().startswith("re:") else f"Re: {subj}"
    if m.get("rfc_id"):
        msg["In-Reply-To"] = m["rfc_id"]
        msg["References"] = (m.get("references", "") + " " + m["rfc_id"]).strip()
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = svc().users().messages().send(userId="me", body={"raw": raw, "threadId": m["thread_id"]}).execute()
    apply_action(item, "mark_read")
    return {"thread_id": m["thread_id"], "sent_id": sent.get("id")}


def thread_has_reply(track):
    """Бидний илгээснээс хойш тэр thread-д өөр хүнээс мессеж ирсэн эсэх."""
    t = svc().users().threads().get(userId="me", id=track["thread_id"], format="metadata",
                                    metadataHeaders=["From"]).execute()
    msgs = t.get("messages", [])
    ids = [x["id"] for x in msgs]
    if track.get("sent_id") in ids:
        after = msgs[ids.index(track["sent_id"]) + 1:]
        return any("SENT" not in x.get("labelIds", []) for x in after)
    return False


def download_attachments(item):
    """[(filename, bytes)] — гарын үсгийн жижиг зургийг алгасна."""
    out = []
    for a in item["meta"].get("attachments", []):
        if a["mime"].startswith("image/") and a.get("size", 0) < 15000:
            continue
        r = svc().users().messages().attachments().get(
            userId="me", messageId=item["meta"]["msg_id"], id=a["id"]).execute()
        out.append((a["filename"], base64.urlsafe_b64decode(r["data"] + "==")))
    return out
