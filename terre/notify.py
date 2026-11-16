"""Мэдэгдэл: Windows-ийн мэдэгдэл (toast) + Telegram bot. Алдаа гарсан ч үндсэн ажил зогсохгүй."""
import logging

log = logging.getLogger("terre.notify")


def _toast(title, body, path="/"):
    try:
        from . import desktop
        desktop.toast(title, body, path)
    except Exception as e:
        log.debug("toast: %s", e)


def _tg(fn, *a):
    try:
        from . import telegram_bot
        if telegram_bot.enabled():
            getattr(telegram_bot, fn)(*a)
    except Exception as e:
        log.info("telegram bot: %s", e)


def urgent(item):
    _toast(f"Яаралтай: {item.get('sender', '')}", item.get("summary") or item.get("subject", ""))
    _tg("push_urgent", item)


def day_report(rep):
    n = len(rep.get("items", []))
    _toast("Өдрийн тайлан бэлэн", f"School Manager-т оруулах {n} тэмдэглэлийн ноорог хүлээж байна", "/#work")
    _tg("push_day_report", rep)


def tasks_due(items):
    first = items[0]
    _toast(f"Хугацаа дөхсөн {len(items)} ажил", first["title"], "/#work")
    _tg("push_tasks", items)


def info(title, body):
    _toast(title, body)
