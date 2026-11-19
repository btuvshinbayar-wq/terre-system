"""TED-ийн 'тархи': Gemini ашиглан мессеж ангилах, хариу ноорог бичих, өглөөний мэдээ зохиох.
Gemini түлхүүргүй үед энгийн дүрмээр ажиллана (демо)."""
import json
import logging
from typing import Literal

from pydantic import BaseModel

from .config import CFG, EN, gemini_key, greeting

log = logging.getLogger("terre.brain")
_client = None


class Triage(BaseModel):
    category: Literal["auto", "approve", "urgent"]
    summary: str          # 1 өгүүлбэр (config: language — англи эсвэл монгол)
    action: Literal["archive", "mark_read", "none"]
    reason: str           # яагаад ингэж ангилсан
    draft: str            # хариу ноорог (хэрэггүй бол хоосон)
    task: str = ""            # эзний хийх ажил (байхгүй бол "")
    deadline: str = ""        # YYYY-MM-DD (байхгүй бол "")
    meeting_date: str = ""    # хурал/уулзалтын урилга бол YYYY-MM-DD
    meeting_time: str = ""    # HH:MM
    meeting_title: str = ""
    meeting_location: str = ""


def L(mn, en):
    """Хэрэглэгчид харагдах/сонсогдох текстийг тохируулсан хэлээр (config: language)."""
    return en if EN() else mn


def _lang_rule():
    return ("summary, reason, task: write in ENGLISH (the owner is practising English), short and clear."
            if EN() else "summary, reason, task: монголоор.")


def _gemini():
    global _client
    if _client is None:
        from google import genai
        from google.genai import types
        # 90 сек-ийн хязгаар: Google талд гацсан хүсэлт TED-ийг бүхэлд нь хүлээлгэхгүй
        _client = genai.Client(api_key=gemini_key(), http_options=types.HttpOptions(timeout=90_000))
    return _client


def _model():
    return CFG.get("gemini", {}).get("model", "gemini-2.5-flash")


def _fast():
    return CFG.get("gemini", {}).get("fast_model") or _model()


def _cfg(model=None, **kw):
    """Gemini тохиргоо. 2.5 загварт 'бодох' токеныг унтраана (зардлын ~80% хэмнэлт).
    Gemini 3.x загварууд thinking_budget-ийг хүлээж авдаггүй (400 INVALID_ARGUMENT) — тэдэнд анхдагч
    (Flash-Lite-д хамгийн бага) бодох түвшнийг үлдээнэ."""
    from google.genai import types
    if model and str(model).startswith("gemini-2"):
        return types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_budget=0), **kw)
    return types.GenerateContentConfig(**kw)


def _gen(model, prompt, **kw):
    from . import health
    try:
        r = _gemini().models.generate_content(model=model, contents=prompt, config=_cfg(model, **kw))
        health.ok("Gemini AI", model)
        return r
    except Exception as e:
        msg = str(e).lower()
        if "thinking" in msg or "invalid_argument" in msg:   # тохиргоог дэмжихгүй загвар — энгийн тохиргоогоор дахин
            from google.genai import types
            try:
                r = _gemini().models.generate_content(model=model, contents=prompt, config=types.GenerateContentConfig(**kw))
                health.ok("Gemini AI", model)
                return r
            except Exception as e2:
                health.err("Gemini AI", e2)
                raise
        health.err("Gemini AI", e)
        raise


TRIAGE_PROMPT = """Чи бол {owner}-ийн хувийн туслах TED. Доорх мессежийг ангил.

Эзний тухай:
{context}

Ангилал:
- "auto": хариу шаардлагагүй (сурталчилгаа, мэдээллийн захидал, автомат мэдэгдэл, баталгаажуулалт,
  групп чатын ерөнхий яриа). action-д "mark_read" (мэйл, чат — уншсан болгоно) эсвэл "none". Мэйлийг АРХИВЛАХГҮЙ.
- "approve": эзэн хариу өгөх эсвэл шийдвэр гаргах ёстой. Хариу ноорог бич.
- "urgent": өнөөдөр/маргааш хугацаатай, удирдлага эсвэл албан байгууллагын шаардлага,
  аюулгүй байдлын сэрэмжлүүлэг, хүүхдийн аюулгүй байдал. Хэрэгтэй бол ноорог бич.

Дүрэм:
- summary: 1 өгүүлбэр, хэн юу хүсч байгааг тодорхой.
- {lang_rule}
- draft: мессеж ирсэн хэлээр нь (монгол/англи), эзний өмнөөс, товч, эелдэг.
  Мэдэхгүй баримт (огноо, тоо, амлалт) зохиож болохгүй — оронд нь [ХААЛТАНД] үлдээ.
- "auto" бол draft хоосон.
- task: эзэнд ногдох тодорхой ажил байвал богино тушаал хэлбэрээр ("Submit the attendance report" / "Ирцийн тайлан ирүүлэх"), үгүй бол "".
- deadline: хугацаа заасан бол YYYY-MM-DD (өнөөдөр {today}, "баасан гаригт", "маргааш"-ийг огноо болго), үгүй бол "".
- meeting_*: хурал, уулзалт, сургалтад урьсан бол огноо, цаг, нэр, байршил; үгүй бол бүгд "".
{examples}
Эх сурвалж: {source}
Илгээгч: {sender}
Гарчиг: {subject}
Агуулга:
{body}
"""


def triage(item):
    if not gemini_key():
        return _heuristic(item)
    from . import learn
    prompt = TRIAGE_PROMPT.format(
        today=__import__("datetime").date.today().isoformat() + " (" + ["Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба", "Ням"][__import__("datetime").date.today().weekday()] + ")",
        examples=learn.triage_examples(),
        lang_rule=_lang_rule(),
        owner=CFG.get("owner_name", ""),
        context=CFG.get("owner_context", ""),
        source=item["source"],
        sender=item.get("sender", ""),
        subject=item.get("subject", ""),
        body=(item.get("body") or item.get("snippet") or "")[:6000],
    )
    try:
        resp = _gen(_fast(), prompt, response_mime_type="application/json",
                    response_schema=Triage, temperature=0.3)
        t = Triage(**json.loads(resp.text)).model_dump()
        # Хямд загвар ангилна, хариу ноорогийг илүү чадвартай загвар бичнэ
        if t["category"] != "auto" and _fast() != _model():
            try:
                t["draft"] = redraft({**item, "draft": t["draft"]},
                                     "Энэ мессежид сайн, бүрэн хариу ноорог бич (мессеж ирсэн хэлээр нь)")
            except Exception:
                pass
        return t
    except Exception as e:
        log.warning("Gemini triage алдаа: %s", e)
        t = _heuristic(item)
        t["reason"] = L(f"(Gemini алдаа, энгийн дүрмээр) {t['reason']}", f"(Gemini error, simple rules) {t['reason']}")
        return t


def redraft(item, instruction):
    if not gemini_key():
        return (item.get("draft") or "") + f"\n\n[{instruction}]"
    from . import learn
    prompt = f"""Чи {CFG.get('owner_name')}-ийн туслах. Доорх мессежид өгсөн хариу ноорогийг зааврын дагуу дахин бич.
Зөвхөн шинэ хариуны текстийг буцаа. Мэдэхгүй баримтыг зохиохгүй.
Хариуны хэл: заавар өөрөөр заагаагүй бол АНХНЫ МЕССЕЖИЙН хэлээр (заавар англиар бичигдсэн байж болно).

Эзний тухай: {CFG.get('owner_context','')}
{learn.style_block()}
Анхны мессеж ({item.get('sender')}): {item.get('subject')}
{(item.get('body') or '')[:4000]}

Одоогийн ноорог:
{item.get('draft')}

Заавар: {instruction}"""
    return _gen(_model(), prompt).text.strip()


def compose_briefing(calendar, counts, urgent, pending, metrics, errors):
    from .config import address
    owner = address()
    if not gemini_key():
        return _template_briefing(owner, calendar, counts, urgent, pending, metrics)
    data = {
        "greeting": f"{greeting()}, {owner}",
        "calendar_today": calendar,
        "counts": counts,
        "urgent": [{"from": i["sender"], "summary": i["summary"]} for i in urgent],
        "needs_approval": [{"from": i["sender"], "summary": i["summary"]} for i in pending],
        "metrics": metrics,
        "connection_errors": errors,
    }
    if EN():
        prompt = f"""You are TED, a calm, intelligent, slightly witty personal AI assistant (think J.A.R.V.I.S.).
Write the daily briefing that will be READ ALOUD to your owner. The owner is practising English, so use clear,
natural English at about B2 level: short sentences, common words, no idioms that are hard to follow.

Requirements:
- English only, 60-120 words, no markdown, lists or emoji (it is spoken).
- Order: the greeting (use "greeting" exactly as given, e.g. "Good morning, Sir.") -> today's schedule (with times)
  -> School Manager plans for today -> urgent items -> items waiting for the owner's approval
  -> how many items TED handled itself -> key numbers.
- Some data is in Mongolian (names of plans, mail summaries): translate the meaning into English.
  Keep people's names and place names as they are (transliterated to Latin letters).
- NO filler such as "TED is ready", "Have a great day", wishes or motivational endings. End with the last fact.
- Overdue tasks: never name them, only give the number ("You have N overdue tasks").
- If there are connection errors, mention them in one sentence.
- Do not invent anything that is not in the data.

Data:
{json.dumps(data, ensure_ascii=False, indent=1)}"""
    else:
        prompt = f"""Чи бол TED (монголоор «Тэд» гэж дуудна) — тайван, ухаалаг, бага зэрэг хошин хувийн AI туслах.
Доорх өгөгдлөөр эзэндээ ДУУГААР уншигдах өдрийн мэдээлэл зохио.

Шаардлага:
- Монгол хэлээр, 60-120 үг, markdown/жагсаалт/emoji БҮҮ ашигла (чангаар уншигдана).
- Дараалал: мэндчилгээ ("greeting"-ийг яг тэр чигээр нь) -> өнөөдрийн хуваарь (цагтай) -> School Manager-т өнөөдөр
  төлөвлөгдсөн ажлууд -> яаралтай зүйлс -> таны зөвшөөрөл хүлээж буй зүйлс -> TED өөрөө шийдсэн зүйлсийн тоо -> тоон үзүүлэлт.
- "TED ажилдаа бэлэн", "Амжилттай өдөр болтугай" зэрэг хоосон мэндчилгээ, урам өгөх төгсгөл, ерөөл БҮҮ нэм. Сүүлийн мэдээллээр л дуусга.
- Хугацаа хэтэрсэн ажлын НЭРИЙГ бүү дурд — зөвхөн тоог нь хэл ("хугацаа хэтэрсэн N ажил байна").
- Холболтын алдаа байвал нэг өгүүлбэрээр дурд.
- Өгөгдөлд байхгүй зүйл зохиохгүй.

Өгөгдөл:
{json.dumps(data, ensure_ascii=False, indent=1)}"""
    try:
        return _gen(_model(), prompt, temperature=0.7).text.strip()
    except Exception as e:
        log.warning("Gemini briefing алдаа: %s", e)
        return _template_briefing(owner, calendar, counts, urgent, pending, metrics)


# ---------- Gemini-гүй үеийн энгийн дүрэм ----------
AUTO_WORDS = ["unsubscribe", "newsletter", "no-reply", "noreply", "promo", "sale", "хямдрал",
              "урамшуулал", "webinar", "digest", "notification"]
URGENT_WORDS = ["яаралтай", "urgent", "asap", "өнөөдөр", "маргааш", "deadline", "хугацаа",
                "security alert", "аюулгүй"]


def _heuristic(item):
    text = " ".join([item.get("sender", ""), item.get("subject", ""), item.get("body", "")]).lower()
    owner = CFG.get("owner_name", "")
    draft = (f"Сайн байна уу,\n\nМессежийг тань хүлээн авлаа. [ХАРИУ] \n\nХүндэтгэсэн,\n{owner}")
    if item["source"] in ("telegram", "gchat") and "групп" in item.get("subject", ""):
        return dict(category="auto", action="mark_read", draft="",
                    summary=f"{item.get('sender')}: {(item.get('snippet') or item.get('body', '')).splitlines()[-1][:80] if (item.get('snippet') or item.get('body')) else ''}", reason=L("Групп чатын ерөнхий яриа", "General group chat"))
    if any(w in text for w in URGENT_WORDS):
        return dict(category="urgent", action="none", draft=draft,
                    summary=f"{item.get('sender')}: {item.get('subject')}", reason=L("Хугацаатай/яаралтай үг агуулсан", "Contains deadline/urgent words"))
    if any(w in text for w in AUTO_WORDS):
        return dict(category="auto", action="mark_read", draft="",
                    summary=f"{item.get('sender')}: {item.get('subject')}", reason=L("Мэдээллийн/автомат мессеж", "Newsletter or automatic message"))
    return dict(category="approve", action="none", draft=draft,
                summary=f"{item.get('sender')}: {item.get('subject')}", reason=L("Хариу шаардаж магадгүй", "May need a reply"))


def _template_briefing(owner, calendar, counts, urgent, pending, metrics):
    if EN():
        return _template_briefing_en(owner, calendar, counts, urgent, pending)
    parts = [f"{greeting()}, {owner}."]
    if calendar:
        ev = ", ".join(f"{e['time']}-д {e['title']}" for e in calendar[:5])
        parts.append(f"Өнөөдөр танд {len(calendar)} үйл явдал байна: {ev}.")
    else:
        parts.append("Өнөөдрийн календарь хоосон байна.")
    if urgent:
        parts.append(f"Яаралтай {len(urgent)} зүйл байна. Хамгийн түрүүнд: {urgent[0]['summary']}.")
    if pending:
        parts.append(f"Таны зөвшөөрлийг {len(pending)} хариу ноорог хүлээж байна.")
    done = counts.get("auto", 0) + counts.get("auto_done", 0)
    if done:
        parts.append(f"Чухал биш {done} мессежийг би ангилж өглөө.")
    sm = counts.get("school_manager")
    if isinstance(sm, dict):
        ab = sm.get("absent_teachers") or []
        if ab:
            parts.append(f"Өнөөдөр {len(ab)} багш ирээгүй: " + ", ".join(f"{a['name']} {a['status'].lower()}" for a in ab[:4]) + ".")
        if sm.get("today_plans"):
            parts.append(f"Өнөөдөр School Manager-т {len(sm['today_plans'])} ажил төлөвлөгдсөн: " + ", ".join(sm["today_plans"][:3]) + ".")
        if sm.get("overdue_plans_count"):
            parts.append(f"Хугацаа хэтэрсэн {sm['overdue_plans_count']} ажил байна.")
        if sm.get("upcoming_plans_7d"):
            parts.append(f"Энэ долоо хоногт: {sm['upcoming_plans_7d'][0]}.")
    elif sm:
        parts.append("School Manager хаалттай байна.")
    return " ".join(parts)


def _n(k, word):
    return f"{k} {word}" + ("" if k == 1 else "s")


def _template_briefing_en(owner, calendar, counts, urgent, pending):
    """Gemini-гүй англи мэдээ. Монгол өгөгдлийн нэрсийг англи хоолойгоор уншуулахгүйн тулд тоогоор хэлнэ."""
    parts = [f"{greeting()}, {owner}."]
    if calendar:
        times = ", ".join(e["time"] for e in calendar[:5] if e.get("time"))
        parts.append(f"You have {_n(len(calendar), 'event')} today" + (f", at {times}." if times else "."))
    else:
        parts.append("Your calendar is clear today.")
    if urgent:
        parts.append(f"There {'is' if len(urgent) == 1 else 'are'} {_n(len(urgent), 'urgent item')}.")
    if pending:
        parts.append(f"{_n(len(pending), 'reply draft')} {'is' if len(pending) == 1 else 'are'} waiting for your approval.")
    done = counts.get("auto", 0) + counts.get("auto_done", 0)
    if done:
        parts.append(f"I sorted {_n(done, 'unimportant message')} for you.")
    sm = counts.get("school_manager")
    if isinstance(sm, dict):
        ab = sm.get("absent_teachers") or []
        if ab:
            parts.append(f"{_n(len(ab), 'teacher')} {'is' if len(ab) == 1 else 'are'} absent today.")
        if sm.get("today_plans"):
            parts.append(f"School Manager has {_n(len(sm['today_plans']), 'plan')} for today.")
        if sm.get("overdue_plans_count"):
            parts.append(f"You have {_n(sm['overdue_plans_count'], 'overdue task')}.")
    elif sm:
        parts.append("School Manager is closed.")
    return " ".join(parts)


# ---------- Файл ангилах ----------
FILE_RULES = [
    (("тайлан", "report"), "Тайлан"),
    (("тушаал", "шийдвэр", "журам"), "Тушаал, шийдвэр"),
    (("албан бичиг", "албан_бичиг", "letter"), "Албан бичиг"),
    (("шалгалт", "дүн", "mock", "test", "exam", "score"), "Шалгалт, дүн"),
    (("хичээл", "lesson", "worksheet", "даалгавар"), "Хичээлийн материал"),
    (("сурагч", "бүртгэл", "student", "анги"), "Сурагчийн бүртгэл"),
    (("хурал", "төлөвлөгөө", "plan", "meeting"), "Хурал, төлөвлөгөө"),
    (("төсөв", "санхүү", "invoice", "нэхэмжлэх", "цалин"), "Санхүү"),
]
EXT_RULES = {
    "Зураг": {".jpg", ".jpeg", ".png", ".gif", ".heic", ".webp", ".bmp"},
    "Програм, архив": {".exe", ".msi", ".zip", ".rar", ".7z", ".iso"},
}


def classify_file(name, ext, text, categories):
    for cat, exts in EXT_RULES.items():
        if ext in exts and cat in categories:
            return {"category": cat, "reason": "Файлын төрлөөр"}
    if gemini_key() and (text or name):
        from . import learn
        prompt = f"""Сургуулийн удирдлагын ажилтны компьютер дээрх файлыг АГУУЛГААР нь ангил.
Зөвхөн эдгээрээс нэгийг сонго: {json.dumps(categories, ensure_ascii=False)}
{learn.file_examples()}
JSON буцаа: {{"category": "...", "reason": "монголоор 1 богино өгүүлбэр", "name": "..."}}
"name": агуулгыг тодорхой илэрхийлэх цэвэр файлын нэр (баримтын хэлээр, өргөтгөлгүй, 60 тэмдэгтээс богино, / \\ : * ? " < > | тэмдэггүй, огноо агуулгад байвал оруул). Одоогийн нэр аль хэдийн тодорхой бол яг хэвээр нь буцаа.

Файлын нэр: {name}
Агуулгын эхлэл:
{(text or "(агуулга уншигдсангүй)")[:3000]}"""
        try:
            r = json.loads(_gen(_fast(), prompt, response_mime_type="application/json", temperature=0.1).text)
            if r.get("category") in categories:
                return {"category": r["category"], "reason": r.get("reason", ""), "name": r.get("name") or None}
        except Exception as e:
            log.warning("Файл ангилах Gemini алдаа: %s", e)
    low = (name + " " + (text or "")[:500]).lower()
    for words, cat in FILE_RULES:
        if cat in categories and any(w in low for w in words):
            return {"category": cat, "reason": "Түлхүүр үгээр"}
    return {"category": "Бусад" if "Бусад" in categories else categories[-1], "reason": "Тодорхойгүй"}


# ---------- Тушаал -> School Manager ----------
def plan_command(text, commands, metrics, context):
    """Хэрэглэгчийн тушаалыг School Manager-ийн тушаал + параметр болгох, эсвэл шууд хариулах."""
    catalog = [{"name": c["name"], "description": c.get("description", ""),
                "params": [{k: p[k] for k in ("name", "label", "choices", "optional") if k in p} for p in c.get("params", [])]}
               for c in commands]
    if not gemini_key():
        low = text.lower()
        if any(low.startswith(w) for w in ("where is", "where's", "where are", "what did", "find the", "find my", "show me the")) \
                and "drive" not in low:
            return {"type": "files", "query": text}
        rules = [("ирц", "Багшийн ирц тэмдэглэх"), ("өвчтэй", "Багшийн ирц тэмдэглэх"), ("чөлөө", "Багшийн ирц тэмдэглэх"),
                 ("тасалсан", "Багшийн ирц тэмдэглэх"), ("хоцорсон", "Багшийн ирц тэмдэглэх"), ("тэмдэглэл", "Ажлын тэмдэглэл нэмэх"),
                 ("биелсэн", "Төлөвлөгөөний төлөв солих"), ("цагийн тооцоо", "Цагийн тооцоо (Excel)"),
                 ("нэгтгэ", "Менежерүүдийн тайлан нэгтгэх"), ("ажиглалт", "Ажиглалтын хуудас (Word)"),
                 ("сул тал", "Давтагдсан сул тал (Word)"), ("хөтөлбөр", "Төлөвлөгөөний файл шинжлэх"),
                 ("амралт", "Амралтын өдөр нэмэх"), ("тайлан", "Нэгдсэн ажлын тайлан"),
                 ("нөөц", "Бүрэн нөөцлөл хийх"), ("төлөвлөгөө нэм", "Төлөвлөгөө нэмэх"),
                 ("мэйл", "Мэйл шалгах"), ("уулзалт", "Уулзалт товлох (Google Meet)"), ("drive", "Drive-оос файл хайх"),
                 # Англи тушаал (Gemini-гүй үед ч таньна)
                 ("attendance", "Багшийн ирц тэмдэглэх"), ("sick", "Багшийн ирц тэмдэглэх"), ("absent", "Багшийн ирц тэмдэглэх"),
                 ("late", "Багшийн ирц тэмдэглэх"), ("check mail", "Мэйл шалгах"), ("check my mail", "Мэйл шалгах"),
                 ("email", "Мэйл шалгах"), ("mail", "Мэйл шалгах"), ("meeting", "Уулзалт товлох (Google Meet)"),
                 ("timesheet", "Цагийн тооцоо (Excel)"), ("backup", "Бүрэн нөөцлөл хийх"), ("add a note", "Ажлын тэмдэглэл нэмэх"),
                 ("note", "Ажлын тэмдэглэл нэмэх"), ("work report", "Нэгдсэн ажлын тайлан")]
        for w, name in rules:
            if w in low and any(c["name"] == name for c in commands):
                params = {}
                for st in ["Өвчтэй", "Чөлөөтэй", "Тасалсан", "Хоцорсон", "Ирсэн"]:
                    if st.lower()[:4] in low:
                        params["status"] = st
                for w2, st in [("sick", "Өвчтэй"), ("leave", "Чөлөөтэй"), ("absent", "Тасалсан"), ("late", "Хоцорсон"), ("present", "Ирсэн")]:
                    if w2 in low:
                        params["status"] = st
                for t in context.get("teachers", []):
                    if any(len(part) > 2 and part.lower() in low for part in t.split()[-1:]):
                        params["teacher"] = t
                cmd = next(c for c in commands if c["name"] == name)
                missing = [p for p in cmd.get("params", []) if not p.get("optional") and p["name"] not in params]
                say = (L(f"«{name}» — дутуу талбарыг бөглөөд ажиллуулна уу.", "Please fill in the missing fields and run it.") if missing
                       else L(f"«{name}» бэлэн. ▶ Ажиллуулах дарна уу.", "Ready. Press Run."))
                return {"type": "macro", "macro": name, "params": params, "say": say}
        if any(w in low for w in ("файл", "хаана", "тушаал", "баримт", "юу гэж", "албан бичиг", "file", "where is", "document", "find")):
            return {"type": "files", "query": text}
        return {"type": "answer", "say": L("Gemini түлхүүргүй үед би энгийн түлхүүр үгээр л таньдаг. Доорх товчнуудаас сонгоно уу.",
                                           "Without a Gemini key I only understand simple keywords. Please choose a command below.")}
    say_rule = ("Хариултын \"say\" текстийг ЗААВАЛ АНГЛИАР бич — энгийн, тодорхой, B2 түвшний англи (эзэн англи хэлээ сайжруулж байгаа). "
                "Монгол өгөгдлийн нэрсийг (төлөвлөгөө, ажил) утгаар нь орчуулж, хүний нэрийг латинаар бич. \"query\" болон params-ийг орчуулахгүй."
                if EN() else "\"say\"-г монголоор бич.")
    prompt = f"""Чи бол TED — сургалтын менежерийн туслах. Тэр чамаар дамжуулан School Manager програмаа удирдаж,
мэйл шалгаж, Google Calendar-т (Meet) уулзалт товлож, Google Drive-тай ажилладаг. Тушаалыг уншаад ЗӨВХӨН JSON буцаа.
Тушаал англи эсвэл монгол хэлээр ирж болно (эзэн англи хэлээ сайжруулж байгаа). Англи тушаалыг ч мөн адил ойлгож,
доорх МОНГОЛ нэртэй тушаалуудтай тааруул. Параметрийн утгыг (багшийн нэр, choices) жагсаалтад байгаа яг хэлбэрээр нь бич.
{say_rule}

Өнөөдөр: {context.get("today")}
Боломжит тушаалууд: {json.dumps(catalog, ensure_ascii=False)}
Багш нарын бүтэн нэрс: {json.dumps(context.get("teachers", []), ensure_ascii=False)}
Төлөвлөгөөнүүд: {json.dumps(context.get("plans", []), ensure_ascii=False)}
Хөтөлбөрийн бичлэгүүд (evaluation): {json.dumps(context.get("evaluations", []), ensure_ascii=False)}
Хичээлийн ажиглалтууд (observation): {json.dumps(context.get("observations", []), ensure_ascii=False)}
Хөтөлбөр/ажиглалттай багш нар: {json.dumps(context.get("curriculum_teachers", []), ensure_ascii=False)}
School Manager-ийн товч мэдээ: {json.dumps(context.get("sm_summary") or {}, ensure_ascii=False)}
School Manager-ийн одоогийн тоонууд: {json.dumps(metrics, ensure_ascii=False)}
Нээлттэй даалгаврууд: {json.dumps(context.get("tasks", []), ensure_ascii=False)}
Өнөөдрийн календарь: {json.dumps(context.get("calendar", []), ensure_ascii=False)}

Дүрэм:
- Компьютер дээрх файл, баримт бичиг хайх эсвэл түүний агуулгын талаар асуувал (тушаал, тайлан, албан бичигт юу гэж байсан,
  файл хаана байна): {{"type":"files","query":"хайх гол үгс эсвэл асуулт"}}
- Даалгавар, хугацаа, өнөөдрийн хуваарийн талаар асуувал дээрх жагсаалтаас товч хариул: {{"type":"answer","say":"..."}}
- Тушаалтай таарвал: {{"type":"macro","macro":"<нэр яг>","params":{{...}},"say":"юу хийх гэж байгаагаа 1 өгүүлбэрээр"}}
  * teacher: жагсаалтаас ЯГ бүтэн нэрийг бич (хэрэглэгч нэрийн зөвхөн нэг хэсгийг хэлсэн бол жагсаалтаас бүрэн нэрийг ол; жагсаалтад байхгүй нэр зохиож болохгүй). Олон таарвал хоосон үлдээж say-д асуу.
  * plan: жагсаалтаас яг нэрийг бич.
  * evaluation, observation: дээрх жагсаалтаас яг мөрийг бич. Олон таарвал хоосон үлдээж асуу.
  * file, files: хэрэглэгч хэлсэн бол л бөглө (замыг зохиохгүй).
  * "мэйл шалга", "шинэ мэйл байна уу" → "Мэйл шалгах". "уулзалт/хурал/meet товло" → "Уулзалт товлох (Google Meet)"
    (date YYYY-MM-DD, time HH:MM 24 цагаар; "3 цагт" гэвэл ажлын цаг тул 15:00). Drive-тай холбоотойг Drive-ийн тушаалаар.
  * choices байгаа бол тэдгээрийн нэгийг яг бич. "маргааш", "өчигдөр" гэвэл огноог YYYY-MM-DD болго.
  * Олдоогүй талбарыг "" үлдээ. Зохиож бүү бич.
- Асуулт бол (хэдэн багш өвчтэй гэх мэт) тоонуудаас товч хариул: {{"type":"answer","say":"..."}}
- Таарах тушаал байхгүй бол: {{"type":"answer","say":"чадахгүйгээ хэлээд ойролцоо тушаал санал болго"}}

Тушаал: {text}"""
    r = json.loads(_gen(_model(), prompt, response_mime_type="application/json", temperature=0.1).text)
    if r.get("type") == "macro" and r.get("macro") not in [c["name"] for c in commands]:
        return {"type": "answer", "say": L("Тохирох тушаал олдсонгүй.", "I couldn't find a matching command.")}
    return r


def transcribe(audio_bytes, mime="audio/wav"):
    """Яриаг (англи/монгол) текст болгоно (Gemini аудио). Түлхүүргүй бол хоосон."""
    if not gemini_key() or not audio_bytes:
        return ""
    from google.genai import types
    part = types.Part.from_bytes(data=audio_bytes, mime_type=mime.split(";")[0])
    prompt = ("Энэ бичлэгт хүн TED («Тэд») гэдэг компьютерийн туслахдаа тушаал өгч эсвэл асуулт асууж байх ёстой. "
              "Хэрэв энэ нь туслахад хандсан тушаал/асуулт БИШ бол (утсаар эсвэл өөр хүнтэй ярьж буй яриа, хагас өгүүлбэр, "
              "чимээ, ТВ/радио) ЗӨВХӨН «-» гэж буцаа, юу ч бүү буулга. Тушаал бол ҮГЧЛЭН бичгээр буулга "
              "(англи эсвэл монгол хэлээр, ярьсан хэлээр нь — бүү орчуул). Зөвхөн буулгасан текстийг буцаа.")
    try:
        resp = _gemini().models.generate_content(model=_fast(), contents=[prompt, part], config=_cfg(_fast(), temperature=0))
        t = (resp.text or "").strip().strip('"«»').strip()
        return "" if t in ("-", "—", "–") else t
    except Exception as e:
        log.warning("Дуу таних алдаа: %s", e)
        return ""


def classify_files_batch(entries, categories):
    """entries: [{"i": int, "name": str, "ext": str, "text": str}] → {i: {"category", "reason"}}.
    Нэг Gemini дуудлагаар 20 хүртэл файл ангилна (хямд, хурдан)."""
    out = {}
    rest = []
    for e in entries:
        hit = None
        for cat, exts in EXT_RULES.items():
            if e["ext"] in exts and cat in categories:
                hit = {"category": cat, "reason": "Файлын төрлөөр"}
        if hit:
            out[e["i"]] = hit
        else:
            rest.append(e)
    if rest and gemini_key():
        for k in range(0, len(rest), 20):
            chunk = rest[k:k + 20]
            listing = "\n".join(f'[{e["i"]}] {e["name"]} :: {(e["text"] or "")[:400].replace(chr(10), " ")}' for e in chunk)
            from . import learn
            prompt = f"""Сургуулийн удирдлагын ажилтны компьютер дээрх файлуудыг АГУУЛГААР нь ангил.
Ангиллууд (зөвхөн эдгээрээс): {json.dumps(categories, ensure_ascii=False)}
{learn.file_examples()}
Мөр бүр: [дугаар] файлын нэр :: агуулгын эхлэл.
JSON массив буцаа: [{{"i": дугаар, "category": "...", "reason": "3-6 үгтэй шалтгаан", "name": "..."}}]
"name": агуулгыг тодорхой илэрхийлэх цэвэр файлын нэр (баримтын хэлээр, өргөтгөлгүй, 60 тэмдэгтээс богино, / \\ : * ? " < > | тэмдэггүй, огноо агуулгад байвал оруул). Одоогийн нэр аль хэдийн тодорхой бол яг хэвээр нь буцаа.

{listing}"""
            try:
                arr = json.loads(_gen(_fast(), prompt, response_mime_type="application/json", temperature=0.1).text)
                for r in arr:
                    if r.get("category") in categories:
                        out[int(r["i"])] = {"category": r["category"], "reason": r.get("reason", ""), "name": r.get("name") or None}
            except Exception as ex:
                log.warning("Багц ангилал алдаа: %s", ex)
    for e in rest:
        if e["i"] not in out:
            out[e["i"]] = classify_file(e["name"], e["ext"], e["text"], categories) if not gemini_key() else \
                _rule_only(e["name"], e["text"], categories)
    return out


def _rule_only(name, text, categories):
    low = (name + " " + (text or "")[:500]).lower()
    for words, cat in FILE_RULES:
        if cat in categories and any(w in low for w in words):
            return {"category": cat, "reason": "Түлхүүр үгээр"}
    return {"category": "Бусад" if "Бусад" in categories else categories[-1], "reason": "Тодорхойгүй"}
