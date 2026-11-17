"""Google OAuth (Gmail, Calendar, Chat). Анх удаа setup_auth.py нэвтрүүлнэ, дараа нь token-оор ажиллана."""
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from ..config import DATA, SECRETS, source_enabled

CLIENT_FILE = SECRETS / "google_credentials.json"
TOKEN_FILE = DATA / "google_token.json"


def scopes():
    s = []
    if source_enabled("gmail"):
        s.append("https://www.googleapis.com/auth/gmail.modify")  # унших, шошголох, илгээх
    if source_enabled("google_calendar"):
        s.append("https://www.googleapis.com/auth/calendar.events")   # унших + үйл явдал нэмэх
    if source_enabled("google_drive"):
        s.append("https://www.googleapis.com/auth/drive")             # Drive: байршуулах, татах, хуваалцах
    if source_enabled("google_chat"):
        s += ["https://www.googleapis.com/auth/chat.spaces.readonly",
              "https://www.googleapis.com/auth/chat.messages.readonly"]
    return s


def creds():
    if not TOKEN_FILE.exists():
        raise RuntimeError("Google-д нэвтрээгүй байна. `python -m terre.setup_auth` ажиллуулна уу.")
    c = Credentials.from_authorized_user_file(str(TOKEN_FILE))
    missing = set(scopes()) - set(c.scopes or [])
    if missing:
        raise RuntimeError("Google эрх нэмэгдсэн. `python -m terre.setup_auth`-ийг дахин ажиллуулна уу.")
    if not c.valid and c.refresh_token:
        c.refresh(Request())
        TOKEN_FILE.write_text(c.to_json(), encoding="utf-8")
    return c


def login():
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not CLIENT_FILE.exists():
        raise SystemExit(f"{CLIENT_FILE} файл алга. README-ийн 'Google холболт' хэсгийг харна уу.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), scopes())
    c = flow.run_local_server(port=0)
    TOKEN_FILE.write_text(c.to_json(), encoding="utf-8")
    (DATA / "google_login.txt").write_text(str(__import__("time").time()), encoding="utf-8")
    print("Google: амжилттай нэвтэрлээ.")
