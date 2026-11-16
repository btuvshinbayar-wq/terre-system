"""`python -m terre` — Terre System-ийг асаана."""
import asyncio
import logging
import os
import socket
import sys
import time

from .config import CFG, DATA

_handlers = [logging.FileHandler(DATA / "terre.log", encoding="utf-8")]
if sys.stdout is None or sys.stderr is None:
    sys.stdout = sys.stderr = open(DATA / "console.log", "a", encoding="utf-8", buffering=1)
else:
    _handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s", handlers=_handlers)

host, port = CFG["server"]["host"], int(CFG["server"]["port"])
base = f"http://{host}:{port}"


def _busy():
    with socket.socket() as s:
        return s.connect_ex((host, port)) == 0


if "--restart" in sys.argv:
    for _ in range(20):
        if not _busy():
            break
        time.sleep(0.5)

if _busy():                       # аль хэдийн ажиллаж байна → зөвхөн цонх нээнэ
    from . import desktop
    tok = (DATA / "dashboard_token").read_text(encoding="utf-8").strip() if (DATA / "dashboard_token").exists() else ""
    desktop.BASE_URL, desktop.TOKEN = base, tok
    desktop.open_quick(voice=True) if "--voice" in sys.argv else desktop.open_quick() if "--quick" in sys.argv \
        else desktop.open_window("/")
    sys.exit(0)

import uvicorn  # noqa: E402

from . import desktop, engine, main  # noqa: E402


def _refresh():
    if main.LOOP:
        asyncio.run_coroutine_threadsafe(engine.run_cycle(), main.LOOP)


def _quit():
    logging.getLogger("terre").info("Хэрэглэгч хаалаа")
    os._exit(0)


desktop.start(base, main.TOKEN, _refresh, _quit)
uvicorn.run(main.app, host=host, port=port, log_config=None)
