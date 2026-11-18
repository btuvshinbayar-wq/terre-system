"""Windows desktop: tray icon, глобал товчлол, Windows мэдэгдэл, програм шиг цонх (Edge app mode).
Windows биш орчинд (хөгжүүлэлт) бүгд чимээгүй алгасагдана."""
import ctypes
import logging
import os
import shutil
import subprocess
import sys
import threading
import webbrowser

from .config import CFG, DATA, ROOT

log = logging.getLogger("terre.desktop")
IS_WIN = sys.platform == "win32"
BASE_URL = ""          # http://127.0.0.1:8765
TOKEN = ""
STATUS = {"tray": False, "hotkeys": [], "hotkey_errors": []}
_icon_path = DATA / "terre.ico"


def cfg():
    return {"hotkeys": True, "hotkey_command": "win+shift+t", "hotkey_voice": "win+shift+v", "app_window": True,
            "toasts": True, "tray": True, **(CFG.get("desktop") or {})}


def url(path="/"):
    sep = "&" if "?" in path else "?"
    return f"{BASE_URL}{path}{sep}k={TOKEN}"


# ---------------- Икон ----------------
def _make_icon():
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), outline=(56, 214, 245, 255), width=6)
    d.ellipse((22, 22, 42, 42), fill=(191, 244, 255, 255))
    try:
        if not _icon_path.exists():
            img.save(_icon_path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    except Exception:
        pass
    return img


# ---------------- Цонх ----------------
def _edge():
    for c in (shutil.which("msedge"),
              os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
              os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe")):
        if c and os.path.exists(c):
            return c
    return None


def open_window(path="/", size=(1400, 920), small=False):
    """Хаягийн мөргүй, програм шиг цонх (Edge --app). Edge олдохгүй бол энгийн браузер."""
    target = url(path)
    edge = _edge() if (IS_WIN and cfg()["app_window"]) else None
    if edge:
        w, h = (540, 640) if small else size
        # Үндсэн самбар дэлгэц дүүрэн (maximize) нээгдэнэ; жижиг тушаалын цонх хэмжээгээрээ
        geom = [f"--window-size={w},{h}"] if small else ["--start-maximized"]
        args = [edge, f"--app={target}", *geom, f"--user-data-dir={DATA / 'window'}",
                "--no-first-run", "--disable-features=Translate", "--autoplay-policy=no-user-gesture-required"]
        try:
            subprocess.Popen(args, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if not small:
                threading.Thread(target=_maximize_later, daemon=True).start()
            return
        except Exception as e:
            log.warning("Edge цонх нээгдсэнгүй: %s", e)
    webbrowser.open(target)


def _maximize_later(title="TED", timeout=12):
    """Edge өмнөх цонхны хэмжээгээ санаж --start-maximized-ийг үл тоох тохиолдол бий — тэгвэл гарч ирмэгц нь
    Windows-оор дэлгэц дүүргэнэ (гарчиг яг "TED" — жижиг цонхных "TED · Quick")."""
    import time
    if not IS_WIN:
        return
    u32 = ctypes.windll.user32
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    end = time.time() + timeout
    while time.time() < end:
        found = []

        def cb(hwnd, _):
            if u32.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(256)
                u32.GetWindowTextW(hwnd, buf, 256)
                if buf.value == title:
                    found.append(hwnd)
            return True
        u32.EnumWindows(proto(cb), 0)
        if found:
            for hwnd in found:
                if not u32.IsZoomed(hwnd):
                    u32.ShowWindow(hwnd, 3)        # SW_MAXIMIZE
            return
        time.sleep(0.4)


def open_quick(voice=False):
    open_window("/quick" + ("?voice=1" if voice else ""), small=True)


# ---------------- Мэдэгдэл ----------------
def toast(title, body, path="/"):
    if not (IS_WIN and cfg()["toasts"]):
        return
    try:
        from winotify import Notification, audio
        n = Notification(app_id="TED", title=title[:80], msg=body[:200],
                         icon=str(_icon_path) if _icon_path.exists() else "", launch=url(path))
        n.set_audio(audio.Default, loop=False)
        n.show()
    except Exception as e:
        log.info("toast алдаа: %s", e)


# ---------------- Глобал товчлол (RegisterHotKey) ----------------
MODS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT = 0x4000


def _parse(combo):
    mods, vk = 0, None
    for part in combo.lower().replace(" ", "").split("+"):
        if part in MODS:
            mods |= MODS[part]
        elif len(part) == 1:
            vk = ord(part.upper())
        elif part == "space":
            vk = 0x20
        elif part.startswith("f") and part[1:].isdigit():
            vk = 0x6F + int(part[1:])
    return mods, vk


def _hotkey_thread(bindings):
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    for i, (combo, fn) in enumerate(bindings, 1):
        mods, vk = _parse(combo)
        if vk and user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
            STATUS["hotkeys"].append(combo)
        else:
            STATUS["hotkey_errors"].append(f"{combo} (өөр програм ашиглаж байж магадгүй)")
    from . import health
    if STATUS["hotkey_errors"]:
        health.warn("Товчлол", "Бүртгэгдээгүй: " + ", ".join(STATUS["hotkey_errors"]))
    else:
        health.ok("Товчлол", ", ".join(STATUS["hotkeys"]))
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        if msg.message == 0x0312:       # WM_HOTKEY
            idx = msg.wParam - 1
            if 0 <= idx < len(bindings):
                try:
                    bindings[idx][1]()
                except Exception:
                    log.exception("hotkey")


# ---------------- Tray ----------------
def _tray(on_refresh, on_quit):
    import pystray
    img = _make_icon()
    c = cfg()
    menu = pystray.Menu(
        pystray.MenuItem("Самбар нээх", lambda: open_window("/"), default=True),
        pystray.MenuItem(f"Тушаал өгөх   ({c['hotkey_command']})", lambda: open_quick()),
        pystray.MenuItem(f"Дуугаар ярих   ({c['hotkey_voice']})", lambda: open_quick(voice=True)),
        pystray.MenuItem("Одоо шалгах", lambda: on_refresh()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Тохиргоо засах (config.yaml)", lambda: os.startfile(str(DATA.parent / "config.yaml"))),
        pystray.MenuItem("Холболт тохируулах", lambda: run_setup()),
        pystray.MenuItem("Өгөгдлийн хавтас", lambda: os.startfile(str(DATA.parent))),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("TED-ийг хаах", lambda icon, item: (icon.stop(), on_quit())),
    )
    icon = pystray.Icon("terre", img, "TED", menu)
    STATUS["tray"] = True
    icon.run()


def run_setup():
    """Холболт тохируулах консолыг шинэ цонхонд нээнэ."""
    from .config import python_exe
    exe = python_exe(windowless=False)
    subprocess.Popen([exe, "-m", "terre.setup_auth"], cwd=str(ROOT),
                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))


def pick_folder():
    """Windows-ийн хавтас сонгох цонх (PowerShell, нэмэлт сангүй)."""
    if not IS_WIN:
        raise RuntimeError("Зөвхөн Windows дээр")
    ps = ("Add-Type -AssemblyName System.Windows.Forms;"
          "$f=New-Object System.Windows.Forms.FolderBrowserDialog;$f.Description='TED-д холбох хавтас сонгох';"
          "$f.ShowNewFolderButton=$false;"
          "$o=New-Object System.Windows.Forms.Form;$o.TopMost=$true;"
          "if($f.ShowDialog($o) -eq 'OK'){[Console]::OutputEncoding=[Text.Encoding]::UTF8;Write-Output $f.SelectedPath}")
    r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], capture_output=True, timeout=600,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.stdout.decode("utf-8", "ignore").strip()


def start(base_url, token, on_refresh, on_quit):
    global BASE_URL, TOKEN
    BASE_URL, TOKEN = base_url, token
    _make_icon()
    if not IS_WIN:
        return
    c = cfg()
    if c["hotkeys"]:
        threading.Thread(target=_hotkey_thread, daemon=True, name="hotkeys",
                         args=([(c["hotkey_command"], open_quick), (c["hotkey_voice"], lambda: open_quick(voice=True))],)).start()
    if c["tray"]:
        threading.Thread(target=_tray, args=(on_refresh, on_quit), daemon=True, name="tray").start()
