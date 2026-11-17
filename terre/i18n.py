"""Самбарт харуулах англи нэрс (config: language: en).

Дотоод нэр, утга (тушаалын нэр, School Manager-ийн төлөв, ангилал) МОНГОЛООР хэвээр — School Manager-т тэр
утгаараа бичигдэх ёстой, Gemini ч тэр нэрээр тааруулна. Энд зөвхөн хэрэглэгчид харагдах шошгыг орчуулна.
"""
from .config import EN

NAMES = {
    "Мэйл шалгах": "Check mail",
    "Уулзалт товлох (Google Meet)": "Schedule a meeting (Google Meet)",
    "Drive-д файл байршуулах": "Upload a file to Drive",
    "Drive-оос файл татах": "Download a file from Drive",
    "Drive файл хуваалцах": "Share a Drive file",
    "Drive-оос файл хайх": "Find a file on Drive",
    "Багшийн ирц тэмдэглэх": "Mark teacher attendance",
    "Бүгд ирсэн гэж бүртгэх": "Mark everyone present",
    "Сарын нэмэлт цаг оруулах": "Add extra hours for the month",
    "Цагийн тооцоо (Excel)": "Timesheet (Excel)",
    "Сарын цагийн тооцоо хаах": "Close the month's timesheet",
    "Сарын хаалт цуцлах": "Reopen a closed month",
    "Ажлын тэмдэглэл нэмэх": "Add a work note",
    "Төлөвлөгөө нэмэх": "Add a plan",
    "Төлөвлөгөөний төлөв солих": "Change plan status",
    "Төлөвлөгөө (Excel)": "Plans (Excel)",
    "Нэгдсэн ажлын тайлан": "Combined work report",
    "Төлөвлөгөөний файл шинжлэх": "Analyse a lesson plan file",
    "Хөтөлбөр импортлох": "Import a curriculum",
    "Хөтөлбөрийн шинжилгээ (Word)": "Curriculum analysis (Word)",
    "Ажиглалтын хуудас (Word)": "Lesson observation sheet (Word)",
    "Давтагдсан сул тал (Word)": "Recurring weaknesses (Word)",
    "Ажиглалтын хуудас нээх": "Open a new observation sheet",
    "Өөрийн тайлангийн багц (.json)": "My report package (.json)",
    "Менежерүүдийн тайлан нэгтгэх": "Merge managers' reports",
    "Амралтын өдөр нэмэх": "Add a holiday",
    "Бүрэн нөөцлөл хийх": "Full backup",
    "Багшийн хуваарь (JSON)": "Teacher timetable (JSON)",
    "Цонх нээх": "Open a School Manager screen",
}

DESCRIPTIONS = {
    "Мэйл шалгах": "Checks all mail and chats now and tells you how many are urgent or waiting for a reply",
    "Уулзалт товлох (Google Meet)": "Adds a meeting to Google Calendar with a Meet link. Attendees get an invitation",
    "Drive-д файл байршуулах": "Copies a file from your computer to Google Drive (the original stays)",
    "Drive-оос файл татах": "Finds a file on Drive by name and downloads it to Documents\\Terre\\Drive",
    "Drive файл хуваалцах": "Shares a Drive file with a person (Google sends them a notification)",
    "Drive-оос файл хайх": "Searches your Drive files by name",
    "Багшийн ирц тэмдэглэх": "Records a teacher's daily attendance (reason, minutes late, missed hours)",
    "Бүгд ирсэн гэж бүртгэх": "Marks every teacher without a record that day as present (existing records stay)",
    "Сарын нэмэлт цаг оруулах": "Adds substitute hours, overtime and last month's difference",
    "Цагийн тооцоо (Excel)": "Exports the monthly teacher timesheet to Excel, same numbers as the app",
    "Сарын цагийн тооцоо хаах": "Records the closing day of the timesheet",
    "Сарын хаалт цуцлах": "Reopens a closed month so it can be edited again",
    "Ажлын тэмдэглэл нэмэх": "Adds what you did to the daily work log",
    "Төлөвлөгөө нэмэх": "Adds a new item to the monthly or yearly plan",
    "Төлөвлөгөөний төлөв солих": "Marks a plan as done, postponed, etc.",
    "Төлөвлөгөө (Excel)": "Exports plans to Excel",
    "Нэгдсэн ажлын тайлан": "Exports the combined report (notes, plans, curriculum, attendance)",
    "Төлөвлөгөөний файл шинжлэх": "Loads a teacher's plan file into the analysis window. You press Analyse and Save in School Manager",
    "Хөтөлбөр импортлох": "Loads a Word/Excel/PDF curriculum into the import window (you decide to save)",
    "Хөтөлбөрийн шинжилгээ (Word)": "Turns a saved curriculum analysis into an official Word/PDF",
    "Ажиглалтын хуудас (Word)": "Turns a lesson observation into the official sheet (11 criteria)",
    "Давтагдсан сул тал (Word)": "Report of weaknesses that repeat across a teacher's curriculum and observations",
    "Ажиглалтын хуудас нээх": "Opens a new lesson observation sheet in School Manager",
    "Өөрийн тайлангийн багц (.json)": "Exports your own report file for the head manager",
    "Менежерүүдийн тайлан нэгтгэх": "Merges other managers' .json files with yours, without duplicates",
    "Амралтын өдөр нэмэх": "Adds a public holiday, student holiday or make-up day to the settings",
    "Бүрэн нөөцлөл хийх": "Saves a backup copy of all data (without licence data)",
    "Багшийн хуваарь (JSON)": "Exports the teachers' weekly timetable as JSON",
    "Цонх нээх": "Opens a School Manager screen",
}

GROUPS = {
    "TED: мэйл, календарь": "TED: mail & calendar",
    "TED: Google Drive": "TED: Google Drive",
    "Ирц & цаг": "Attendance & hours",
    "Тэмдэглэл & төлөвлөгөө": "Notes & plans",
    "Тайлан": "Reports",
    "Хөтөлбөр & ажиглалт": "Curriculum & observation",
    "Нэгтгэл": "Consolidation",
    "Тохиргоо & нөөц": "Settings & backup",
}

LABELS = {
    "Уулзалтын нэр": "Meeting title", "Огноо (YYYY-MM-DD)": "Date (YYYY-MM-DD)",
    "Эхлэх цаг (HH:MM)": "Start time (HH:MM)", "Үргэлжлэх хугацаа, минут (хоосон = 60)": "Length in minutes (empty = 60)",
    "Оролцогчдын мэйл (, тусгаарлана)": "Attendee emails (separate with ,)", "Google Meet холбоос": "Google Meet link",
    "Файлын зам": "File path", "Drive дахь хавтасны нэр (хоосон = My Drive)": "Drive folder name (empty = My Drive)",
    "Файлын нэр (хэсэг нь ч болно)": "File name (part is fine)", "Файлын нэр": "File name", "Хэнтэй (мэйл)": "Share with (email)",
    "Эрх": "Access", "Хайх үг": "Search words", "Багш": "Teacher", "Төлөв": "Status",
    "Огноо (YYYY-MM-DD, хоосон = өнөөдөр)": "Date (YYYY-MM-DD, empty = today)", "Тайлбар": "Note",
    "Хоцорсон минут": "Minutes late", "Зайлшгүй шалтгаанаар ороогүй цаг": "Missed hours, excused",
    "Зайлшгүй шалтгаан (олимпиад, сургалт…)": "Excuse (olympiad, training…)", "Шалтгаангүй ороогүй цаг": "Missed hours, unexcused",
    "Сар (YYYY-MM, хоосон = энэ сар)": "Month (YYYY-MM, empty = this month)", "Орлон заасан цаг": "Substitute hours",
    "Нэмэлт заасан (илүү) цаг": "Overtime hours", "Өмнөх сарын зөрүү цаг (+/-)": "Last month's difference (+/-)",
    "Хаах өдөр (хоосон = тухайн сарын 25)": "Closing day (empty = the 25th)", "Юу хийсэн": "What you did",
    "Ангилал": "Category", "Зарцуулсан цаг": "Hours spent", "Оролцогчийн тоо": "Participants",
    "Үр дүн, дүгнэлт": "Result, conclusion", "Анхаарах зүйл": "Points of concern", "Сайжруулах санал": "Suggestions",
    "Холбогдох төлөвлөгөө": "Related plan", "Эхэлсэн цаг (HH:MM)": "Start time (HH:MM)", "Үйл ажиллагаа": "Activity",
    "Төрөл": "Type", "Эхлэх огноо (YYYY-MM-DD)": "Start date (YYYY-MM-DD)", "Дуусах огноо": "End date",
    "Зорилго": "Goal", "Хариуцах нэгж": "Responsible unit", "Хүрэх үр дүн": "Expected result", "Төлөвлөгөө": "Plan",
    "Сар (YYYY-MM, хоосон = бүгд)": "Month (YYYY-MM, empty = all)", "Хугацаа": "Period", "Хэлбэр": "Format",
    "Файлын зам (.docx / .pdf)": "File path (.docx / .pdf)", "Файлын зам (.docx / .xlsx / .pdf)": "File path (.docx / .xlsx / .pdf)",
    "Хөтөлбөр": "Curriculum", "Ажиглалт": "Observation", "Файлуудын зам (; тусгаарлана)": "File paths (separate with ;)",
    "Тайлбар (баярын нэр г.м.)": "Note (holiday name etc.)", "Цэс": "Screen",
}

# Сонголтын утга School Manager-т МОНГОЛООР бичигдэнэ — зөвхөн харагдах шошго
CHOICES = {
    "Тийм": "Yes", "Үгүй": "No", "Харах": "View", "Сэтгэгдэл бичих": "Comment", "Засах": "Edit",
    "Ирсэн": "Present", "Өвчтэй": "Sick", "Чөлөөтэй": "On leave", "Тасалсан": "Absent", "Хоцорсон": "Late",
    "бүртгэл": "registration", "хурал цуглаан": "meeting", "уулзалт": "appointment", "зөвлөн туслах": "advising",
    "цахим систем": "e-systems", "сургалт": "training", "хөтөлбөр хэрэгжүүлэх": "curriculum delivery",
    "өөрийн хөгжил": "self-development", "тодорхойлолт": "reference letter", "шилжилт хөдөлгөөн": "transfers",
    "амжилт": "achievement", "бусад": "other", "сарын": "monthly", "жилийн": "yearly",
    "төлөвлөсөн": "planned", "хийгдэж байгаа": "in progress", "биелсэн": "done", "хойшилсон": "postponed",
    "Сар": "Month", "7 хоног": "Week", "Улирал": "Term", "Жил": "Year",
    "Жилийн төлөвлөгөө": "Yearly plan", "Нэгж хичээл": "Unit plan", "Ээлжит хичээл": "Lesson plan",
    "Бүх нийтийн амралт": "Public holiday", "Сурагчдын амралт (багш ажиллана)": "Student holiday (teachers work)",
    "Нөхөж хичээллэх өдөр": "Make-up school day", "Хяналтын самбар": "Dashboard", "Календар": "Calendar",
    "Тэмдэглэл": "Notes", "Хөтөлбөрийн шинжилгээ": "Curriculum analysis", "Ирц & Цагийн хуваарь": "Attendance & timetable",
    "Нэгтгэл": "Consolidation", "Тохиргоо": "Settings", "Тайлан": "Reports", "Төлөвлөгөө": "Plans",
}


def t(table, s):
    return table.get(s, s) if EN() else s


def command_for_ui(c):
    """Тушаалыг самбарт: name (дотоод, монгол) + title/description/group/label англиар."""
    params = []
    for p in c.get("params", []):
        q = dict(p)
        q["label"] = t(LABELS, p.get("label", p["name"]))
        if p.get("choices"):
            q["choice_labels"] = {x: t(CHOICES, x) for x in p["choices"]}
        params.append(q)
    return {"name": c["name"], "title": t(NAMES, c["name"]),
            "description": t(DESCRIPTIONS, c["name"]) if EN() and c["name"] in DESCRIPTIONS else c.get("description", ""),
            "group": t(GROUPS, c.get("group", "")), "params": params}
