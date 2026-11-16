# Terre System — Claude-д зориулсан заавар

Энэ project бол **Terre System**: Windows дээр ажилладаг хувийн AI туслах (өмнөх нэр "Jarvis" — энэ нэрийг ашиглахгүй).
Эзэн нь Tuvshuu — сургалтын менежер, програм хөгжүүлэлтийг AI-тай хамт зохион байгуулдаг (мэргэжлийн хөгжүүлэгч биш).
Харилцаа **монгол хэлээр**. Тайлбарыг товч, алхам алхмаар.

## Байнгын шаардлагууд
- **Нэр:** "Terre System" / "Terre". "Jarvis" гэж хэзээ ч бүү нэрлэ.
- **Аюулгүй байдал:** мэйл, мессеж хэзээ ч автоматаар илгээхгүй — үргэлж хэрэглэгчийн товчоор. Файл хэзээ ч устгахгүй, зөвхөн зөөнө,
  бүх үйлдэл журналд буцаах боломжтой байна. Нууц үг, token-ыг config.yaml-д биш Windows Credential Manager (keyring)-д.
- **School Manager** = эзний өөрийн Electron програм (repo `btuvshinbayar-wq/school-manager`). Firebase / Smart Report-тэй
  ХОЛБОГДОХГҮЙ. Холболт нь `terre-bridge.cjs` + `src/utils/terreBridge.ts` (patch: `school-manager-terre-bridge.patch`).
  Лицензийн логикт хүрэхгүй, хуучин лицензийн кодтой нийцтэй байлгана.
- **Зардал:** Gemini — ангилахад `gemini-2.5-flash-lite`, ноорогт `gemini-2.5-flash`, `thinking_budget=0`. Токен хэмнэх
  (багц ангилал, дүрмээр урьдчилан шүүх) нь чухал.
- **Хэрэглэгчийн туршлага:** хөдөлгөөнт, Iron Man маягийн HUD самбар. Шинэ UI нэмэхдээ одоогийн хэв маягийг (cyan, reactor,
  slideIn/rise анимаци, toast) дагана.
- **Түгээлт:** `installer/` дахь NSIS-ээр `TerreSystem-Setup-x.y.z.exe`. Python суулгах шаардлагагүй байх ёстой.

## Бүтэц (товч)
- `terre/main.py` FastAPI (127.0.0.1:8765, токен cookie хамгаалалт), `engine.py` гол мөчлөг, `brain.py` Gemini
- `connectors/`: gmail, gcal, gchat, outlook, imap_mail, telegram (Telethon), school_manager (bridge)
- `files.py`, `organizer.py` файл/хавтас цэгцлэх; `search.py` FTS5 хайлт; `tasks.py`, `calendar_write.py`;
  `dayreport.py`; `journal.py` (буцаах); `health.py`; `learn.py`; `telegram_bot.py`; `desktop.py` (tray, товчлол, toast, Edge app цонх)
- `web/index.html` самбар (Нүүр/Ажил/Файл/Систем табууд), `web/quick.html` товчлолын жижиг цонх
- Суулгасан хувилбарт тохиргоо, өгөгдөл `%APPDATA%\Terre System\` (`installed.flag` байгаа үед)

## Хөгжүүлэх
- Демо: `config.yaml`-д `demo_mode: true` → `python -m terre` (холболтгүйгээр бүх зүйл ажиллана)
- Шалгалт: `python -m py_compile terre/*.py terre/connectors/*.py`, демо горимоор сервер асааж самбарыг браузераар шалгах
- Дэлгэрэнгүй: `docs/PROJECT.md`
