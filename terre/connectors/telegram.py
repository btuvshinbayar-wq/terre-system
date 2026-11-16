"""Telegram — таны хувийн данс (Telethon). Уншаагүй чатуудыг уншина, зөвшөөрсөн хариуг илгээнэ."""
from telethon import TelegramClient

from ..config import CFG, DATA

_client = None


def _make():
    t = CFG["sources"]["telegram"]
    return TelegramClient(str(DATA / "telegram"), int(t["api_id"]), t["api_hash"])


async def client():
    global _client
    if _client is None:
        _client = _make()
    if not _client.is_connected():
        await _client.connect()
    if not await _client.is_user_authorized():
        raise RuntimeError("Telegram-д нэвтрээгүй. `python -m terre.setup_auth` ажиллуулна уу.")
    return _client


async def fetch_unread():
    c = await client()
    limit = int(CFG["sources"]["telegram"].get("max_chats", 40))
    out = []
    async for d in c.iter_dialogs(limit=limit):
        if not d.unread_count or d.archived:
            continue
        msgs = await c.get_messages(d.entity, limit=min(d.unread_count, 8))
        lines = []
        for m in reversed(msgs):
            if not m.message:
                continue
            who = getattr(m.sender, "first_name", None) or d.name
            lines.append(f"{who}: {m.message}")
        if not lines:
            continue
        out.append({
            "id": f"telegram:{d.id}:{msgs[0].id}",
            "source": "telegram",
            "sender": d.name,
            "subject": "Telegram" + (" (групп)" if (d.is_group or d.is_channel) else ""),
            "snippet": lines[-1][:200],
            "body": "\n".join(lines),
            "received": msgs[0].date.isoformat(),
            "meta": {"chat_id": d.id, "unread": d.unread_count},
        })
    return out


async def apply_action(item, action):
    c = await client()
    await c.send_read_acknowledge(item["meta"]["chat_id"])


async def send_reply(item, body):
    c = await client()
    await c.send_message(item["meta"]["chat_id"], body)
    await c.send_read_acknowledge(item["meta"]["chat_id"])


async def login():
    c = _make()
    await c.start()  # утасны дугаар, Telegram-аас ирсэн кодыг консолд асууна
    me = await c.get_me()
    print(f"Telegram: {me.first_name} нэрээр нэвтэрлээ.")
    await c.disconnect()
