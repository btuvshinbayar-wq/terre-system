"""Бусад мэйл хаяг (IMAP + SMTP): сургуулийн домэйн мэйл, Yahoo, iCloud, Mail.ru, Yandex, Zoho, hosting мэйл...

Нууц үгийг config.yaml-д БИЧИХГҮЙ — Windows Credential Manager (keyring)-д хадгална.
Унших үед мэйлийг 'уншсан' болгохгүй (BODY.PEEK).
"""
import email
import imaplib
import re
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.policy import default as default_policy
from email.utils import make_msgid, parseaddr, parsedate_to_datetime

from ..config import CFG, TZ

KEYRING_SERVICE = "TerreSystem-mail"

PRESETS = {
    # Хоёр дахь Gmail данс: App password хэрэгтэй (2-Step Verification асаалттай). Gmail илгээсэн мэйлээ өөрөө
    # хадгалдаг тул sent_folder хоосон (давхардуулахгүй); архив = "Бүх мэйл"
    "gmail":   {"imap_host": "imap.gmail.com", "smtp_host": "smtp.gmail.com", "smtp_port": 465,
                "archive_folder": "[Gmail]/All Mail", "sent_folder": ""},
    "yahoo":   {"imap_host": "imap.mail.yahoo.com", "smtp_host": "smtp.mail.yahoo.com", "smtp_port": 465},
    "icloud":  {"imap_host": "imap.mail.me.com", "smtp_host": "smtp.mail.me.com", "smtp_port": 587},
    "mailru":  {"imap_host": "imap.mail.ru", "smtp_host": "smtp.mail.ru", "smtp_port": 465},
    "yandex":  {"imap_host": "imap.yandex.com", "smtp_host": "smtp.yandex.com", "smtp_port": 465},
    "zoho":    {"imap_host": "imap.zoho.com", "smtp_host": "smtp.zoho.com", "smtp_port": 465},
    "aol":     {"imap_host": "imap.aol.com", "smtp_host": "smtp.aol.com", "smtp_port": 465},
    "gmx":     {"imap_host": "imap.gmx.com", "smtp_host": "mail.gmx.com", "smtp_port": 587},
}


# ---------------- Тохиргоо ----------------
def accounts():
    out = []
    for a in CFG.get("sources", {}).get("other_mail", []) or []:
        if not a.get("enabled") or not a.get("email"):
            continue
        acc = {"imap_port": 993, "smtp_port": 465, "archive_folder": "Archive", "sent_folder": "Sent", "inbox": "INBOX",
               **PRESETS.get((a.get("provider") or "").lower(), {}), **{k: v for k, v in a.items() if v not in (None, "")}}
        acc.setdefault("name", acc["email"])
        acc.setdefault("username", acc["email"])
        if not acc.get("imap_host"):
            dom = acc["email"].split("@")[-1]
            acc["imap_host"], acc["smtp_host"] = f"mail.{dom}", acc.get("smtp_host") or f"mail.{dom}"
        acc.setdefault("smtp_host", acc["imap_host"].replace("imap", "smtp", 1))
        out.append(acc)
    return out


def _account(name):
    for a in accounts():
        if a["name"] == name:
            return a
    raise RuntimeError(f"Мэйл данс олдсонгүй эсвэл идэвхгүй: {name}")


def get_password(acc):
    import keyring
    pw = keyring.get_password(KEYRING_SERVICE, acc["email"])
    if not pw:
        raise RuntimeError(f"{acc['email']}: нууц үг хадгалагдаагүй. `setup_connections.bat` ажиллуулна уу.")
    return pw


def set_password(email_addr, password):
    import keyring
    keyring.set_password(KEYRING_SERVICE, email_addr, password)


# ---------------- IMAP ----------------
def _imap(acc):
    ctx = ssl.create_default_context()
    if int(acc["imap_port"]) == 143:
        m = imaplib.IMAP4(acc["imap_host"], 143, timeout=30)
        m.starttls(ssl_context=ctx)
    else:
        m = imaplib.IMAP4_SSL(acc["imap_host"], int(acc["imap_port"]), ssl_context=ctx, timeout=30)
    m.login(acc["username"], get_password(acc))
    return m


def _decode_body(msg):
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        text = part.get_content()
    except Exception:
        text = (part.get_payload(decode=True) or b"").decode("utf-8", "ignore")
    if part.get_content_type() == "text/html":
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
        text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def _attachments(msg):
    return [p.get_filename() for p in msg.iter_attachments() if p.get_filename()]


def parse(raw, acc, uid, uidvalidity):
    msg = email.message_from_bytes(raw, policy=default_policy)
    name, addr = parseaddr(str(msg.get("From", "")))
    body = _decode_body(msg)
    try:
        received = parsedate_to_datetime(msg.get("Date")).astimezone(TZ).isoformat()
    except Exception:
        received = ""
    return {
        "id": f"imap:{acc['name']}:{uidvalidity}:{uid}",
        "source": "imap",
        "sender": name or addr,
        "subject": str(msg.get("Subject", "")) or "(гарчиггүй)",
        "snippet": body[:200],
        "body": body[:8000],
        "received": received,
        "meta": {
            "account": acc["name"], "uid": uid, "uidvalidity": uidvalidity, "from_addr": (addr or "").lower(),
            "rfc_id": str(msg.get("Message-ID", "")), "references": str(msg.get("References", "")),
            "reply_to": str(msg.get("Reply-To") or msg.get("From", "")), "subject": str(msg.get("Subject", "")),
            "attachments": _attachments(msg),
            # Google Chat-ийн «уншаагүй мессеж» мэдэгдлийн мэйл — самбарт Google Chat гэж харуулна
            "chat": (addr or "").lower() in ("chat-noreply@google.com", "chat-noreply@chat.google.com"),
        },
    }


def _fetch_account(acc, limit=25, days=3):
    m = _imap(acc)
    try:
        typ, data = m.select(acc["inbox"], readonly=True)
        if typ != "OK":
            raise RuntimeError(f"{acc['inbox']} хавтас нээгдсэнгүй")
        uidvalidity = (m.response("UIDVALIDITY")[1] or [b"0"])[0]
        uidvalidity = uidvalidity.decode() if isinstance(uidvalidity, bytes) else str(uidvalidity)
        since = time.strftime("%d-%b-%Y", time.gmtime(time.time() - days * 86400))
        typ, data = m.uid("SEARCH", None, "UNSEEN", "SINCE", since)
        uids = (data[0] or b"").split()[-limit:]
        out = []
        for uid in reversed(uids):
            typ, msgdata = m.uid("FETCH", uid, "(BODY.PEEK[])")
            raw = next((x[1] for x in msgdata if isinstance(x, tuple)), None)
            if raw:
                out.append(parse(raw, acc, uid.decode(), uidvalidity))
        return out
    finally:
        try:
            m.logout()
        except Exception:
            pass


def _explain(acc, e):
    """Түгээмэл алдааг ойлгомжтой болгох."""
    m = str(e)
    low = m.lower()
    if "keyring" in low or "нууц үг" in low or "password" in low and "not" in low:
        return f"{m} → Эхлэх цэс → «Terre — холболт тохируулах»-аар App password оруулна уу"
    if "authenticationfailed" in low or "invalid credentials" in low or "application-specific password" in low:
        hint = (" Gmail бол энгийн нууц үг биш App password (16 тэмдэгт) хэрэгтэй; байгууллагын данс бол IT админ хаасан байж магадгүй."
                if "gmail" in (acc.get("imap_host") or "") else "")
        return "Нэвтэрч чадсангүй (нууц үг буруу)." + hint
    return m


def fetch_unread():
    from .. import health
    items, errors = [], []
    for acc in accounts():
        try:
            got = _fetch_account(acc)
            items += got
            health.ok(acc["name"], f"{len(got)} уншаагүй мэйл")
        except Exception as e:
            errors.append(f"{acc['name']}: {e}")
            health.err(acc["name"], _explain(acc, e))
    if errors and not items:
        raise RuntimeError("; ".join(errors))
    return items


def _with_message(item, fn):
    acc = _account(item["meta"]["account"])
    m = _imap(acc)
    try:
        m.select(acc["inbox"])
        return fn(m, acc, item["meta"]["uid"])
    finally:
        try:
            m.logout()
        except Exception:
            pass


def apply_action(item, action):
    def do(m, acc, uid):
        m.uid("STORE", uid, "+FLAGS", r"(\Seen)")
        if action == "archive" and acc.get("archive_folder"):
            typ, _ = m.uid("MOVE", uid, acc["archive_folder"])
            if typ != "OK":   # MOVE дэмжихгүй сервер
                if m.uid("COPY", uid, acc["archive_folder"])[0] == "OK":
                    m.uid("STORE", uid, "+FLAGS", r"(\Deleted)")
                    try:   # зөвхөн энэ мэйлийг (UIDPLUS). Дэмжихгүй бол бусад мэйлд хүрэхгүйн тулд expunge хийхгүй
                        m.uid("EXPUNGE", uid)
                    except Exception:
                        pass
    _with_message(item, do)


def mark_read(item):
    _with_message(item, lambda m, acc, uid: m.uid("STORE", uid, "+FLAGS", r"(\Seen)"))


def mark_unread(item):
    _with_message(item, lambda m, acc, uid: m.uid("STORE", uid, "-FLAGS", r"(\Seen)"))


def trash(item):
    """Хогийн сав руу зөөнө (config: trash_folder, анхдагч "Trash")."""
    def do(m, acc, uid):
        folder = acc.get("trash_folder") or "Trash"
        m.uid("STORE", uid, "+FLAGS", r"(\Seen)")
        if m.uid("MOVE", uid, folder)[0] == "OK":
            return
        if m.uid("COPY", uid, folder)[0] != "OK":
            raise RuntimeError(f"'{folder}' хавтас олдсонгүй. config.yaml → trash_folder-д хогийн савны нэрийг бичнэ үү")
        m.uid("STORE", uid, "+FLAGS", r"(\Deleted)")
        try:
            m.uid("EXPUNGE", uid)
        except Exception:
            pass
    _with_message(item, do)


def unarchive(item):
    acc = _account(item["meta"]["account"])
    m = _imap(acc)
    try:
        rid = item["meta"].get("rfc_id")
        if acc.get("archive_folder") and rid and m.select(acc["archive_folder"])[0] == "OK":
            typ, data = m.uid("SEARCH", None, "HEADER", "Message-ID", rid)
            for uid in (data[0] or b"").split():
                m.uid("STORE", uid, "-FLAGS", r"(\Seen)")
                if m.uid("MOVE", uid, acc["inbox"])[0] != "OK":
                    m.uid("COPY", uid, acc["inbox"])
                return
        m.select(acc["inbox"])
        m.uid("STORE", item["meta"]["uid"], "-FLAGS", r"(\Seen)")
    finally:
        try:
            m.logout()
        except Exception:
            pass


def download_attachments(item):
    if not item["meta"].get("attachments"):
        return []

    def do(m, acc, uid):
        typ, msgdata = m.uid("FETCH", uid, "(BODY.PEEK[])")
        raw = next((x[1] for x in msgdata if isinstance(x, tuple)), None)
        msg = email.message_from_bytes(raw, policy=default_policy)
        out = []
        for p in msg.iter_attachments():
            fn = p.get_filename()
            data = p.get_payload(decode=True)
            if not fn or not data:
                continue
            if p.get_content_maintype() == "image" and len(data) < 15000:
                continue
            out.append((fn, data))
        return out
    return _with_message(item, do)


# ---------------- SMTP ----------------
def build_reply(acc, item, body):
    meta = item["meta"]
    msg = EmailMessage()
    msg["From"] = f"{acc.get('display_name') or CFG.get('owner_name', '')} <{acc['email']}>"
    msg["To"] = meta["reply_to"]
    subj = meta.get("subject", "")
    msg["Subject"] = subj if subj.lower().startswith(("re:", "ре:")) else f"Re: {subj}"
    msg["Message-ID"] = make_msgid(domain=acc["email"].split("@")[-1])
    if meta.get("rfc_id"):
        msg["In-Reply-To"] = meta["rfc_id"]
        msg["References"] = (meta.get("references", "") + " " + meta["rfc_id"]).strip()
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg.set_content(body)
    return msg


def _smtp_send(acc, msg):
    ctx = ssl.create_default_context()
    port = int(acc["smtp_port"])
    if port == 465:
        with smtplib.SMTP_SSL(acc["smtp_host"], port, context=ctx, timeout=30) as s:
            s.login(acc["username"], get_password(acc))
            s.send_message(msg)
    else:
        with smtplib.SMTP(acc["smtp_host"], port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(acc["username"], get_password(acc))
            s.send_message(msg)


def send_reply(item, body):
    acc = _account(item["meta"]["account"])
    msg = build_reply(acc, item, body)
    _smtp_send(acc, msg)

    def after(m, acc, uid):
        m.uid("STORE", uid, "+FLAGS", r"(\Seen \Answered)")
        if acc.get("sent_folder"):   # зарим сервер илгээсэн мэйлийг өөрөө хадгалдаггүй
            try:
                m.append(acc["sent_folder"], r"(\Seen)", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
            except Exception:
                pass
    try:
        _with_message(item, after)
    except Exception:
        pass   # мэйл аль хэдийн явсан — тэмдэглэгээ амжилтгүй байсан ч алдаа биш
    return {"account": acc["name"], "sent_msgid": msg["Message-ID"]}


def thread_has_reply(track):
    acc = _account(track["account"])
    m = _imap(acc)
    try:
        m.select(acc["inbox"], readonly=True)
        typ, data = m.uid("SEARCH", None, "HEADER", "In-Reply-To", track["sent_msgid"])
        if (data[0] or b"").split():
            return True
        typ, data = m.uid("SEARCH", None, "HEADER", "References", track["sent_msgid"])
        return bool((data[0] or b"").split())
    finally:
        try:
            m.logout()
        except Exception:
            pass


def test_account(acc):
    """setup_auth-д: IMAP, SMTP хоёуланд нэвтэрч үзнэ."""
    m = _imap(acc)
    m.logout()
    ctx = ssl.create_default_context()
    port = int(acc["smtp_port"])
    s = smtplib.SMTP_SSL(acc["smtp_host"], port, context=ctx, timeout=30) if port == 465 else smtplib.SMTP(acc["smtp_host"], port, timeout=30)
    if port != 465:
        s.starttls(context=ctx)
    s.login(acc["username"], get_password(acc))
    s.quit()
