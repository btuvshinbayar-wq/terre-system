# TED — Claude-д зориулсан заавар

Энэ project бол **TED**: Windows дээр ажилладаг хувийн AI туслах (өмнөх нэрс "Terre System", "Jarvis" — эдгээрийг ашиглахгүй).
Эзэн нь Tuvshuu — сургалтын менежер, програм хөгжүүлэлтийг AI-тай хамт зохион байгуулдаг (мэргэжлийн хөгжүүлэгч биш).
Харилцаа **монгол хэлээр**. Тайлбарыг товч, алхам алхмаар.

## Байнгын шаардлагууд
- **Нэр:** "TED" (монголоор «Тэд», дуудах үг «Хэй Тэд»). "Terre", "Jarvis" гэж хэзээ ч бүү нэрлэ. Харин дотоод техникийн
  нэрс (Python багц `terre`, repo `terre-system`, `%APPDATA%\Terre System`, `C:\Program Files\Terre System`,
  `Documents\Terre`, `%APPDATA%\TerreBridge`, keyring `TerreSystem-*`) хэвээр — солих нь тохиргоо, нэвтрэлт, холболтыг эвдэнэ.
- **Аюулгүй байдал:** мэйл, мессеж хэзээ ч автоматаар илгээхгүй — үргэлж хэрэглэгчийн товчоор. Файл хэзээ ч устгахгүй, зөвхөн зөөнө,
  бүх үйлдэл журналд буцаах боломжтой байна. Нууц үг, token-ыг config.yaml-д биш Windows Credential Manager (keyring)-д.
- **School Manager** = эзний өөрийн програм (repo `btuvshinbayar-wq/school-manager`). Эзэн зөвхөн **Lite (Neutralino)** хувилбар
  ашигладаг. Firebase / Smart Report-тэй ХОЛБОГДОХГҮЙ. Холболт нь `src/utils/terreBridge.ts` — файлын шуудангийн хайрцаг
  (`%APPDATA%\TerreBridge\school-manager.json` + `school-manager\inbox|outbox`; мэдэгдэл "🤖 TED: …"), салбар `terre-bridge-lite`
  (patch: `school-manager-terre-bridge.patch`). Өгөгдөл: `sm-data-mirror.json` (эзний хавтас `D:\work\2026-2027\SchoolManager-Data`).
  Лицензийн логикт хүрэхгүй, хуучин лицензийн кодтой нийцтэй байлгана.
- **Зохиомол нэр, өгөгдөл хэрэггүй:** School Manager-т хамаарах демо/жишээ өгөгдөл үүсгэхгүй, дутуу утгыг таамаглаж бөглөхгүй.
- **Зардал:** Gemini — ангилахад `gemini-2.5-flash-lite`, ноорогт `gemini-2.5-flash`, `thinking_budget=0`. Токен хэмнэх
  (багц ангилал, дүрмээр урьдчилан шүүх) нь чухал.
- **Хэрэглэгчийн туршлага:** хөдөлгөөнт, Iron Man маягийн HUD самбар. Шинэ UI нэмэхдээ одоогийн хэв маягийг (cyan, reactor,
  slideIn/rise анимаци, toast) дагана.
- **Түгээлт:** `installer/` дахь NSIS-ээр `TerreSystem-Setup-x.y.z.exe` (installer-ийн нэр, Эхлэх цэсийн нэрийг дараагийн хувилбарт TED болгоно). Python суулгах шаардлагагүй байх ёстой.

## Бүтэц (товч)
- `wake.py` дуудах үг «Хэй Тэд» (Vosk, offline) → тушаалыг Gemini-ээр ойлгож биелүүлнэ
- `terre/main.py` FastAPI (127.0.0.1:8765, токен cookie хамгаалалт), `engine.py` гол мөчлөг, `brain.py` Gemini
- `connectors/`: gmail, gcal, gchat, outlook, imap_mail, telegram (Telethon), school_manager (файлын хайрцаг + mirror унших)
- `files.py`, `organizer.py` файл/хавтас цэгцлэх; `search.py` FTS5 хайлт; `tasks.py`, `calendar_write.py`;
  `dayreport.py`; `journal.py` (буцаах); `health.py`; `learn.py`; `telegram_bot.py`; `desktop.py` (tray, товчлол, toast, Edge app цонх)
- `web/index.html` самбар (Нүүр/Ажил/Файл/Систем табууд), `web/quick.html` товчлолын жижиг цонх
- Суулгасан хувилбарт тохиргоо, өгөгдөл `%APPDATA%\Terre System\` (`installed.flag` байгаа үед)

## Хөгжүүлэх
- Демо: `config.yaml`-д `demo_mode: true` → `python -m terre` (холболтгүйгээр бүх зүйл ажиллана)
- Шалгалт: `python -m py_compile terre/*.py terre/connectors/*.py`, демо горимоор сервер асааж самбарыг браузераар шалгах
- Дэлгэрэнгүй: `docs/PROJECT.md`
