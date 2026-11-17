import datetime
import os
import pathlib
import shutil
import sys
from zoneinfo import ZoneInfo

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent      # програмын код (Program Files дотор байж болно)


def _user_dir():
    """Тохиргоо, өгөгдөл хадгалах газар. Суулгасан хувилбарт %APPDATA%\\TED."""
    if os.environ.get("TERRE_HOME"):
        return pathlib.Path(os.environ["TERRE_HOME"])
    if (ROOT / "installed.flag").exists() or not os.access(ROOT, os.W_OK):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return pathlib.Path(base) / "Terre System"
    return ROOT                                               # хөгжүүлэлтийн горим: кодын хавтас


HOME = _user_dir()
DATA = HOME / "data"
SECRETS = HOME / "secrets"
CONFIG_FILE = HOME / "config.yaml"
for _d in (HOME, DATA, SECRETS):
    _d.mkdir(parents=True, exist_ok=True)
if not CONFIG_FILE.exists() and (ROOT / "config.example.yaml").exists() and HOME != ROOT:
    shutil.copy(ROOT / "config.example.yaml", CONFIG_FILE)


def _load():
    path = CONFIG_FILE if CONFIG_FILE.exists() else ROOT / "config.example.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


CFG = _load()
TZ = ZoneInfo(CFG.get("timezone", "Asia/Ulaanbaatar"))
DEMO = bool(CFG.get("demo_mode"))
FROZEN = (ROOT / "installed.flag").exists()


def address():
    """TED таныг ингэж дуудна (config: address). Гарын үсэгт owner_name хэвээр."""
    return str(CFG.get("address") or CFG.get("owner_name") or "").strip()


def save_config_value(path_keys, value):
    """Самбараас тохиргоо өөрчлөх (жишээ нь demo_mode). Тайлбаруудыг хадгалахын тулд мөрөөр нь засна."""
    text = CONFIG_FILE.read_text(encoding="utf-8") if CONFIG_FILE.exists() else ""
    key = path_keys[-1]
    import re
    pat = re.compile(rf"^(\s*{re.escape(key)}\s*:\s*)([^#\n]*)(.*)$", re.M)
    rendered = yaml.safe_dump(value, allow_unicode=True, default_flow_style=True).strip().removesuffix("...").strip()
    if pat.search(text):
        text = pat.sub(lambda m: f"{m.group(1)}{rendered}  {m.group(3).strip()}".rstrip(), text, count=1)
        CONFIG_FILE.write_text(text, encoding="utf-8")
    d = CFG
    for k in path_keys[:-1]:
        d = d.setdefault(k, {})
    d[key] = value


def now():
    return datetime.datetime.now(TZ)


def source_enabled(name):
    return bool(CFG.get("sources", {}).get(name, {}).get("enabled"))


def gemini_key():
    return (CFG.get("gemini", {}) or {}).get("api_key") or os.environ.get("GEMINI_API_KEY", "")


def greeting():
    h = now().hour
    if h < 11:
        return "Өглөөний мэнд"
    if h < 17:
        return "Өдрийн мэнд"
    return "Оройн мэнд"


def python_exe(windowless=True):
    exe = pathlib.Path(sys.executable)
    if windowless and exe.name.lower() == "python.exe" and (exe.parent / "pythonw.exe").exists():
        return str(exe.parent / "pythonw.exe")
    return str(exe)
