"""Terre System-ийн 'тархи': Gemini ашиглан мессеж ангилах, хариу ноорог бичих, өглөөний мэдээ зохиох.
Gemini түлхүүргүй үед энгийн дүрмээр ажиллана (демо)."""
import json
import logging
from typing import Literal

from pydantic import BaseModel

from .config import CFG, gemini_key, greeting

log = logging.getLogger("terre.brain")
_client = None


class Triage(BaseModel):
    category: Literal["auto", "approve", "urgent"]
    summary: str          # 1 өгүүлбэр, монголоор
    action: Literal["archive", "mark_read", "none"]
    reason: str           # яагаад ингэж ангилсан
    draft: str            # хариу ноорог (хэрэггүй бол хоосон)
    task: str = ""            # эзний хийх ажил (байхгүй бол "")
    deadline: str = ""        # YYYY-MM-DD (байхгүй бол "")
    meeting_date: str = ""    # хурал/уулзалтын урилга бол YYYY-MM-DD
    meeting_time: str = ""    # HH:MM
    meeting_title: str = ""
    meeting_location: str = ""


def _gemini():
    global _client
    if _client is None:
        from google import genai
        from google.genai import types
        # 90 сек-ийн хязгаар: Google талд гацсан хүсэлт Terre-ийг бүхэлд нь хүлээлгэхгүй
        _client = genai.Client(api_key=gemini_key(), http_options=types.HttpOptions(timeout=90_000))
    return _client


def _model():
    return CFG.get("gemini", {}).get("model", "gemini-2.5-flash")


def _fast():
    return CFG.get("gemini", {}).get("fast_model") or _model()


def _cfg(**kw):
    """Gemini тохиргоо. 2.5 Flash-ийн 'бодох' токеныг унтраана — зардлын ~80%-ийг хэмнэнэ."""
    from google.genai import types
    return types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_budget=0), **kw)


def _gen(model, prompt, **kw):
    try:
        return _gemini().models.generate_content(model=model, contents=prompt, config=_cfg(**kw))
    except Exception as e:
        if "thinking" in str(e).lower():   # зарим загвар thinking_budget=0-г дэмждэггүй
            from google.genai import types
            return _gemini().models.generate_content(model=model, contents=prompt,
                                                     config=types.GenerateContentConfig(**kw))
        raise


TRIAGE_PROMPT = """Чи бол {owner}-ийн хувийн туслах Terre. Доорх мессежийг ангил.

Эзний тухай:
{context}

Ангилал:
- "auto": хариу шаардлагагүй (сурталчилгаа, мэдээллийн захидал, автомат мэдэгдэл, баталгаажуулалт,
  групп чатын ерөнхий яриа). action-д "archive" (мэйл) эсвэл "mark_read" (чат) эсвэл "none".
- "approve": эзэн хариу өгөх эсвэл шийдвэр гаргах ёстой. Хариу ноорог бич.
- "urgent": өнөөдөр/маргааш хугацаатай, удирдлага эсвэл албан байгууллагын шаардлага,
  аюулгүй байдлын сэрэмжлүүлэг, хүүхдийн аюулгүй байдал. Хэрэгтэй бол ноорог бич.

Дүрэм:
- summary: монголоор 1 өгүүлбэр, хэн юу хүсч байгааг тодорхой.
- draft: мессеж ирсэн хэлээр нь (монгол/англи), эзний өмнөөс, товч, эелдэг.
  Мэдэхгүй баримт (огноо, тоо, амлалт) зохиож болохгүй — оронд нь [ХААЛТАНД] үлдээ.
- "auto" бол draft хоосон.
- task: эзэнд ногдох тодорхой ажил байвал богино тушаал хэлбэрээр ("Ирцийн тайлан ирүүлэх"), үгүй бол "".
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
                t["draft"] = redraft({**item, "draft": t["draft"]}, "Энэ мессежид сайн, бүрэн хариу ноорог бич")
            except Exception:
                pass
        return t
    except Exception as e:
        log.warning("Gemini triage алдаа: %s", e)
        t = _heuristic(item)
        t["reason"] = f"(Gemini алдаа, энгийн дүрмээр) {t['reason']}"
        return t


def redraft(item, instruction):
    if not gemini_key():
        return (item.get("draft") or "") + f"\n\n[{instruction}]"
    from . import learn
    prompt = f"""Чи {CFG.get('owner_name')}-ийн туслах. Доорх мессежид өгсөн хариу ноорогийг зааврын дагуу дахин бич.
Зөвхөн шинэ хариуны текстийг буцаа. Мэдэхгүй баримтыг зохиохгүй.

Эзний тухай: {CFG.get('owner_context','')}
{learn.style_block()}
Анхны мессеж ({item.get('sender')}): {item.get('subject')}
{(item.get('body') or '')[:4000]}

Одоогийн ноорог:
{item.get('draft')}

Заавар: {instruction}"""
    return _gen(_model(), prompt).text.strip()


def compose_briefing(calendar, counts, urgent, pending, metrics, errors):
    owner = CFG.get("owner_name", "")
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
    prompt = f"""Чи бол Terre System — тайван, ухаалаг, бага зэрэг хошин хувийн AI туслах.
Доорх өгөгдлөөр эзэндээ ДУУГААР уншигдах өдрийн мэдээлэл зохио.

Шаардлага:
- Монгол хэлээр, 90-140 үг, markdown/жагсаалт/emoji БҮҮ ашигла (чангаар уншигдана).
- Дараалал: мэндчилгээ -> өнөөдрийн хуваарь (цагтай) -> яаралтай зүйлс -> таны зөвшөөрөл хүлээж буй
  зүйлс -> Terre өөрөө шийдсэн зүйлсийн тоо -> тоон үзүүлэлт -> богино урам өгөх төгсгөл.
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
                    summary=f"{item.get('sender')}: {(item.get('snippet') or item.get('body', '')).splitlines()[-1][:80] if (item.get('snippet') or item.get('body')) else ''}", reason="Групп чатын ерөнхий яриа")
    if any(w in text for w in URGENT_WORDS):
        return dict(category="urgent", action="none", draft=draft,
                    summary=f"{item.get('sender')}: {item.get('subject')}", reason="Хугацаатай/яаралтай үг агуулсан")
    if any(w in text for w in AUTO_WORDS):
        act = "archive" if item["source"] in ("gmail", "outlook") else "mark_read"
        return dict(category="auto", action=act, draft="",
                    summary=f"{item.get('sender')}: {item.get('subject')}", reason="Мэдээллийн/автомат мессеж")
    return dict(category="approve", action="none", draft=draft,
                summary=f"{item.get('sender')}: {item.get('subject')}", reason="Хариу шаардаж магадгүй")


def _template_briefing(owner, calendar, counts, urgent, pending, metrics):
    parts = [f"{greeting()}, {owner}. Terre ажилдаа бэлэн."]
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
        if sm.get("overdue_plans"):
            parts.append(f"Хугацаа хэтэрсэн {len(sm['overdue_plans'])} төлөвлөгөө байна: {sm['overdue_plans'][0]}.")
        if sm.get("upcoming_plans_7d"):
            parts.append(f"Энэ долоо хоногт: {sm['upcoming_plans_7d'][0]}.")
    elif sm:
        parts.append("School Manager хаалттай байна.")
    parts.append("Амжилттай өдөр болтугай.")
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
        rules = [("ирц", "Багшийн ирц тэмдэглэх"), ("өвчтэй", "Багшийн ирц тэмдэглэх"), ("чөлөө", "Багшийн ирц тэмдэглэх"),
                 ("тасалсан", "Багшийн ирц тэмдэглэх"), ("хоцорсон", "Багшийн ирц тэмдэглэх"), ("тэмдэглэл", "Ажлын тэмдэглэл нэмэх"),
                 ("биелсэн", "Төлөвлөгөөний төлөв солих"), ("цагийн тооцоо", "Цагийн тооцоо (Excel)"),
                 ("нэгтгэ", "Менежерүүдийн тайлан нэгтгэх"), ("ажиглалт", "Ажиглалтын хуудас (Word)"),
                 ("сул тал", "Давтагдсан сул тал (Word)"), ("хөтөлбөр", "Төлөвлөгөөний файл шинжлэх"),
                 ("амралт", "Амралтын өдөр нэмэх"), ("тайлан", "Нэгдсэн ажлын тайлан"),
                 ("нөөц", "Бүрэн нөөцлөл хийх"), ("төлөвлөгөө нэм", "Төлөвлөгөө нэмэх")]
        for w, name in rules:
            if w in low and any(c["name"] == name for c in commands):
                params = {}
                for st in ["Өвчтэй", "Чөлөөтэй", "Тасалсан", "Хоцорсон", "Ирсэн"]:
                    if st.lower()[:4] in low:
                        params["status"] = st
                for t in context.get("teachers", []):
                    if any(len(part) > 2 and part.lower() in low for part in t.split()[-1:]):
                        params["teacher"] = t
                return {"type": "macro", "macro": name, "params": params, "say": f"«{name}» — дутуу талбарыг бөглөөд ажиллуулна уу."}
        if any(w in low for w in ("файл", "хаана", "тушаал", "баримт", "юу гэж", "албан бичиг")):
            return {"type": "files", "query": text}
        return {"type": "answer", "say": "Gemini түлхүүргүй үед би энгийн түлхүүр үгээр л таньдаг. Доорх товчнуудаас сонгоно уу."}
    prompt = f"""Чи бол Terre System — сургалтын менежерийн туслах. Тэр өөрийн School Manager програмыг
чамаар дамжуулан удирддаг. Тушаалыг уншаад ЗӨВХӨН JSON буцаа.

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
  * choices байгаа бол тэдгээрийн нэгийг яг бич. "маргааш", "өчигдөр" гэвэл огноог YYYY-MM-DD болго.
  * Олдоогүй талбарыг "" үлдээ. Зохиож бүү бич.
- Асуулт бол (хэдэн багш өвчтэй гэх мэт) тоонуудаас товч хариул: {{"type":"answer","say":"..."}}
- Таарах тушаал байхгүй бол: {{"type":"answer","say":"чадахгүйгээ хэлээд ойролцоо тушаал санал болго"}}

Тушаал: {text}"""
    r = json.loads(_gen(_model(), prompt, response_mime_type="application/json", temperature=0.1).text)
    if r.get("type") == "macro" and r.get("macro") not in [c["name"] for c in commands]:
        return {"type": "answer", "say": "Тохирох тушаал олдсонгүй."}
    return r


def transcribe(audio_bytes, mime="audio/wav"):
    """Монгол яриаг текст болгоно (Gemini аудио). Түлхүүргүй бол хоосон."""
    if not gemini_key() or not audio_bytes:
        return ""
    from google.genai import types
    part = types.Part.from_bytes(data=audio_bytes, mime_type=mime.split(";")[0])
    prompt = ("Энэ бичлэгт хүн Terre гэдэг туслахдаа тушаал өгч эсвэл асуулт асууж байна. Яриаг ҮГЧЛЭН бичгээр буулга "
              "(ихэвчлэн монгол хэл, заримдаа англи). Зөвхөн буулгасан текстийг буцаа. Яриа сонсогдохгүй бол хоосон буцаа.")
    try:
        resp = _gemini().models.generate_content(model=_fast(), contents=[prompt, part], config=_cfg(temperature=0))
        return (resp.text or "").strip().strip('"«»')
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
