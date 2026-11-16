"""Telegram bot — Terre-ийг утаснаас удирдах.

- Зөвхөн таны (эзний) чатад хариулна, бусад хүнд юу ч хэлэхгүй.
- Яаралтай мэйл ирвэл мэдэгдэнэ: ноорог харах → "✅ Тийм, илгээ" гэсэн 2 алхмаар илгээнэ.
- Текст эсвэл дуут мессежээр тушаал өгнө: "Болд багшийг өвчтэй гэж тэмдэглэ", "А-145 тушаалд юу гэж байсан бэ?"
- Өдрийн тайлан, хугацаа дөхсөн ажлыг илгээж, товчоор зөвшөөрүүлнэ.
Bot token-ыг Windows Credential Manager-т хадгална.
"""
import asyncio
import itertools
import logging
import time

import requests

from .config import CFG, DEMO

log = logging.getLogger("terre.telegram_bot")
KEYRING_SERVICE = "TerreSystem-telegram-bot"
API = "https://api.telegram.org/bot{token}/{method}"
_counter = itertools.count(1)
_refs = {}            # богино код -> ("item"|"proposal"|...), payload  (callback_data 64 байтын хязгаартай)
_loop = None
_token_cache = None
STATUS = {"running": False, "last_error": "", "chat_id": None}
MENU = {"keyboard": [[{"text": "📋 Өнөөдөр"}, {"text": "✉ Хүлээгдэж буй"}],
                     [{"text": "✅ Даалгавар"}, {"text": "📝 Өдрийн тайлан"}]],
        "resize_keyboard": True, "is_persistent": True}


def cfg():
    return CFG.get("telegram_bot") or {}


def enabled():
    return bool(cfg().get("enabled")) and bool(token()) and bool(chat_id())


def token():
    global _token_cache
    if _token_cache is None:
        try:
            import keyring
            _token_cache = keyring.get_password(KEYRING_SERVICE, "token") or ""
        except Exception:
            _token_cache = ""
    return _token_cache or cfg().get("token", "")


def chat_id():
    from . import learn
    return learn.kv_get("tg_chat_id") or str(cfg().get("chat_id") or "")


def api(method, http_timeout=35, **params):
    params = {k: v for k, v in params.items() if v is not None}
    r = requests.post(API.format(token=token(), method=method), json=params, timeout=http_timeout)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Telegram алдаа"))
    return data["result"]


def _ref(kind, payload):
    k = str(next(_counter))
    _refs[k] = (kind, payload, time.time())
    if len(_refs) > 500:
        for old in sorted(_refs, key=lambda x: _refs[x][2])[:100]:
            _refs.pop(old, None)
    return k


def send(text, buttons=None, keyboard=False):
    params = {"chat_id": chat_id(), "text": text[:4000], "disable_web_page_preview": True}
    if buttons:
        params["reply_markup"] = {"inline_keyboard": buttons}
    elif keyboard:
        params["reply_markup"] = MENU
    try:
        return api("sendMessage", **params)
    except Exception as e:
        log.warning("Telegram илгээж чадсангүй: %s", e)
        STATUS["last_error"] = str(e)


def _from_thread(coro):
    """Engine-ийн loop дээр async функц ажиллуулах (bot өөрийн урсгалаас)."""
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=180)


# ---------------- Push мэдэгдлүүд ----------------
def _item_buttons(item_id):
    k = _ref("item", item_id)
    return [[{"text": "✎ Ноорог харах", "callback_data": f"draft:{k}"}, {"text": "Алгасах", "callback_data": f"skip:{k}"}]]


def push_urgent(item):
    send(f"🔴 Яаралтай — {item.get('sender', '')}\n{item.get('summary') or item.get('subject', '')}", _item_buttons(item["id"]))


def push_day_report(rep):
    lines = [f"• {it['title']} ({it['category']}, {it['hours']} цаг)" for it in rep["items"] if it["status"] == "pending"]
    if not lines:
        return
    send("📝 Өдрийн тайлан — School Manager-т оруулах тэмдэглэлүүд:\n" + "\n".join(lines),
         [[{"text": "✅ Бүгдийг оруулах", "callback_data": "rep:all"}, {"text": "Самбараас сонгоно", "callback_data": "noop"}]])


def push_tasks(items):
    for t in items[:6]:
        when = "өнөөдөр" if t.get("days_left") == 0 else "маргааш" if t.get("days_left") == 1 else \
            f"{-t['days_left']} хоног хэтэрсэн" if (t.get("days_left") or 0) < 0 else t.get("due", "")
        send(f"⏰ {t['title']}\nХугацаа: {when}", [[{"text": "✓ Хийсэн", "callback_data": f"tdone:{_ref('task', t['id'])}"}]])


# ---------------- Ирсэн мессеж ----------------
def _today_text():
    from . import engine, store, tasks
    st = engine.STATE
    lines = [st.get("briefing") or "Өнөөдрийн мэдээлэл бэлдэж байна."]
    if st.get("calendar"):
        lines.append("\n📅 " + "\n📅 ".join(f"{e['time']} {e['title']}" for e in st["calendar"][:8]))
    c = store.today_counts()
    lines.append(f"\n🔴 Яаралтай: {c.get('open_urgent', 0)} · 🟡 Хүлээгдэж буй: {c.get('open_pending', 0)} · ✅ Даалгавар: {len(tasks.open_tasks())}")
    return "\n".join(lines)


def _handle_text(text):
    from . import brain, engine, search, store, tasks
    t = text.strip()
    if t in ("/start", "/help", "/menu"):
        return send("Сайн байна уу! Би Terre. Тушаалаа бичих эсвэл дуут мессеж илгээнэ үү.\n"
                    "Жишээ: «Болд багшийг өвчтэй гэж тэмдэглэ», «А-145 тушаалд юу гэж байсан бэ?», «Энэ сарын тайланг гарга»",
                    keyboard=True)
    if t.startswith("📋") or t == "/today":
        return send(_today_text(), keyboard=True)
    if t.startswith("✉") or t == "/pending":
        items = store.by_status(["urgent", "pending"], 8)
        if not items:
            return send("Хүлээгдэж буй мессеж алга. 👌")
        for it in items:
            send(f"{'🔴' if it['status'] == 'urgent' else '🟡'} {it['sender']}\n{it.get('summary') or it['subject']}", _item_buttons(it["id"]))
        return
    if t.startswith("✅") or t == "/tasks":
        ts = [x for x in tasks.open_tasks() if x["kind"] != "meeting"][:10]
        if not ts:
            return send("Нээлттэй даалгавар алга.")
        for x in ts:
            send(f"• {x['title']}" + (f"\n  Хугацаа: {x['due']}" if x.get("due") else ""),
                 [[{"text": "✓ Хийсэн", "callback_data": f"tdone:{_ref('task', x['id'])}"}]])
        return
    if t.startswith("📝") or t == "/report":
        from . import dayreport
        rep = dayreport.get() or _from_thread(engine.day_report(force=True))
        return push_day_report(rep) or (None if any(i["status"] == "pending" for i in rep["items"]) else send("Өнөөдрийн тайланд оруулах зүйл алга."))
    if t.lower().startswith(("/find ", "🔎")):
        q = t.split(" ", 1)[1] if " " in t else ""
        return _send_search(q)
    # Чөлөөт тушаал
    st = engine.STATE.get("sm_state") or {}
    ctx = {"teachers": st.get("teachers", []), "plans": st.get("plans", [])[:80], "today": time.strftime("%Y-%m-%d"),
           "tasks": [x["title"] + (f" ({x['due']})" if x.get("due") else "") for x in tasks.open_tasks()][:20],
           "calendar": engine.STATE.get("calendar", [])}
    plan = brain.plan_command(t, engine.commands(), engine.STATE.get("metrics", []), ctx)
    if plan.get("type") == "macro":
        k = _ref("proposal", {"name": plan["macro"], "params": plan.get("params", {})})
        shown = "\n".join(f"  {a}: {b}" for a, b in (plan.get("params") or {}).items() if b) or "  (параметргүй)"
        return send(f"⚙ {plan['macro']}\n{shown}\n\n{plan.get('say', '')}",
                    [[{"text": "▶ Ажиллуулах", "callback_data": f"run:{k}"}, {"text": "Болих", "callback_data": "cancel"}]])
    if plan.get("type") == "files":
        return _send_search(plan.get("query") or t, ask=True)
    return send(plan.get("say") or "Ойлгосонгүй.")


def _send_search(q, ask=True):
    from . import search
    if not q:
        return send("Юу хайх вэ? Жишээ: /find А-145 тушаал")
    r = search.ask(q) if ask else {"answer": "", "sources": search.search(q, 8)}
    src = "\n".join(f"[{i + 1}] {s['name']} ({s['folder']})" for i, s in enumerate(r["sources"][:6]))
    send(f"🔎 {r['answer']}\n\n{src}".strip())


def _handle_voice(file_id, mime="audio/ogg"):
    from . import brain
    f = api("getFile", file_id=file_id)
    data = requests.get(f"https://api.telegram.org/file/bot{token()}/{f['file_path']}", timeout=60).content
    text = brain.transcribe(data, mime)
    if not text:
        return send("Дууг таньж чадсангүй. Дахин оролдоно уу.")
    send(f"🎙 «{text}»")
    _handle_text(text)


def _handle_callback(cb):
    from . import dayreport, engine, store, tasks
    data = cb.get("data", "")
    api("answerCallbackQuery", http_timeout=10, callback_query_id=cb["id"])
    kind, _, k = data.partition(":")
    ref = _refs.get(k)
    if kind in ("draft", "skip", "send", "run", "tdone") and not ref:
        return send("Энэ товч хуучирсан байна. «✉ Хүлээгдэж буй» дарж дахин нээнэ үү.")
    if kind == "draft":
        it = store.get(ref[1])
        if not it or it["status"] not in ("urgent", "pending"):
            return send("Энэ мессеж аль хэдийн шийдэгдсэн.")
        k2 = _ref("item", it["id"])
        return send(f"✉ {it['sender']} — {it['subject']}\n\n{it.get('draft') or '(ноорог алга)'}",
                    [[{"text": "✅ Тийм, илгээ", "callback_data": f"send:{k2}"}, {"text": "Болих", "callback_data": "cancel"}]])
    if kind == "send":
        it = store.get(ref[1])
        if not it or it["status"] not in ("urgent", "pending"):
            return send("Энэ мессеж аль хэдийн шийдэгдсэн.")
        _from_thread(engine.send(it["id"], it.get("draft") or "", who="Та (Telegram)"))
        return send(f"✓ Илгээгдлээ: {it['sender']}")
    if kind == "skip":
        engine.dismiss(ref[1], who="Та (Telegram)")
        return send("Алгаслаа.")
    if kind == "run":
        p = ref[1]
        miss = [x["label"] for c in engine.commands() if c["name"] == p["name"] for x in c.get("params", [])
                if not x.get("optional") and not p["params"].get(x["name"])]
        if miss:
            return send(f"Дутуу: {', '.join(miss)}. Тушаалаа илүү дэлгэрэнгүй бичнэ үү.")
        r = _from_thread(engine.run_command(p["name"], p["params"], who="Та (Telegram)"))
        return send(("✓ " if r["ok"] else "✗ ") + p["name"] + "\n" + "\n".join(r.get("log", [])))
    if kind == "tdone":
        tasks.set_status(ref[1], "done")
        return send("✓ Хийсэн гэж тэмдэглэлээ.")
    if kind == "rep" and k == "all":
        rep = dayreport.get()
        ids = [i["id"] for i in rep["items"] if i["status"] == "pending"] if rep else []
        added = dayreport.add_items(ids)
        return send(f"✓ School Manager-т {len(added)} тэмдэглэл орлоо.")
    if kind in ("cancel", "noop"):
        return


def _poll_forever():
    offset = None
    STATUS["running"] = True
    while True:
        try:
            ups = api("getUpdates", http_timeout=40, timeout=30, offset=offset)
            STATUS["last_error"] = ""
            for u in ups:
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                cb = u.get("callback_query")
                cid = str((msg.get("chat") or {}).get("id") or ((cb or {}).get("message") or {}).get("chat", {}).get("id", ""))
                if cid != chat_id():
                    continue                       # зөвхөн эзэн
                try:
                    if cb:
                        _handle_callback(cb)
                    elif msg.get("voice") or msg.get("audio"):
                        v = msg.get("voice") or msg.get("audio")
                        _handle_voice(v["file_id"], v.get("mime_type", "audio/ogg"))
                    elif msg.get("text"):
                        _handle_text(msg["text"])
                except Exception as e:
                    log.exception("Telegram bot боловсруулах алдаа")
                    send(f"Алдаа: {e}")
        except Exception as e:
            STATUS["last_error"] = str(e)
            log.info("Telegram polling: %s", e)
            time.sleep(10)


def start(loop):
    global _loop
    _loop = loop
    if not enabled() or DEMO:
        return False
    import threading
    threading.Thread(target=_poll_forever, daemon=True, name="telegram-bot").start()
    return True


# ---------------- Тохируулах (setup_auth-аас) ----------------
def setup_interactive():
    import getpass
    import keyring
    print("\n[Telegram bot] Telegram дээр @BotFather → /newbot → нэр өгөөд token авна.")
    tok = getpass.getpass("  Bot token (харагдахгүй, хоосон = алгасах): ").strip()
    if not tok:
        return
    keyring.set_password(KEYRING_SERVICE, "token", tok)
    global _token_cache
    _token_cache = tok
    me = api("getMe")
    print(f"  ✓ Bot: @{me['username']}. Одоо Telegram дээр тэр bot-д /start гэж бичнэ үү (60 секунд хүлээнэ)...")
    deadline, offset = time.time() + 60, None
    while time.time() < deadline:
        ups = api("getUpdates", http_timeout=30, timeout=20, offset=offset)
        for u in ups:
            offset = u["update_id"] + 1
            m = u.get("message") or {}
            if m.get("text", "").startswith("/start"):
                from . import learn
                learn.kv_set("tg_chat_id", str(m["chat"]["id"]))
                api("sendMessage", chat_id=m["chat"]["id"], text="✓ Terre System холбогдлоо! Зөвхөн танд хариулна.",
                    reply_markup=MENU)
                print(f"  ✓ Таны чат холбогдлоо ({m['from'].get('first_name', '')}). config.yaml → telegram_bot.enabled: true")
                return
    print("  ✗ /start ирсэнгүй. Дахин оролдоно уу.")

