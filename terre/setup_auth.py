"""Нэг удаагийн нэвтрэлт: `python -m terre.setup_auth`
config.yaml дээр идэвхжүүлсэн эх сурвалж бүрт нэвтрүүлнэ. Нууц үг, кодыг ЗӨВХӨН энэ консолд өөрөө оруулна."""
import asyncio

import os
import sys

from .config import CFG, CONFIG_FILE, DEMO, gemini_key, save_config_value, source_enabled

if os.name == "nt":
    os.system("chcp 65001 >nul")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _basics():
    import getpass
    print(f"Тохиргооны файл: {CONFIG_FILE}\n")
    name = input(f"Таны нэр (Terre таныг ингэж дуудна) [{CFG.get('owner_name', '')}]: ").strip()
    if name:
        save_config_value(["owner_name"], name)
    if not gemini_key():
        print("\n[Gemini AI] https://aistudio.google.com/apikey хаягаар орж 'Create API key' дарж түлхүүр авна.")
        key = getpass.getpass("  Gemini API түлхүүр (бичихэд харагдахгүй, хоосон = алгасах): ").strip()
        if key:
            save_config_value(["gemini", "api_key"], key)
            print("  ✓ Хадгалагдлаа")
    print("\nДараах холболтуудыг тохируулахын тулд эхлээд config.yaml-д 'enabled: true' болгосон байх хэрэгтэй.")
    print("(Tray icon → «Тохиргоо засах» эсвэл самбарын «Систем» таб)\n")


def main():
    print("=== Terre System: холболтууд тохируулах ===\n")
    _basics()
    if any(source_enabled(s) for s in ("gmail", "google_calendar", "google_chat")):
        print("[Google] Браузер нээгдэнэ, данс сонгоод зөвшөөрнө үү...")
        from .connectors import google_auth
        google_auth.login()
    if source_enabled("outlook"):
        print("\n[Outlook]")
        from .connectors import outlook
        outlook.login()
    from .connectors import imap_mail
    for acc in imap_mail.accounts():
        import getpass
        print(f"\n[{acc['name']}] {acc['email']}  (IMAP {acc['imap_host']}:{acc['imap_port']}, SMTP {acc['smtp_host']}:{acc['smtp_port']})")
        if acc.get("provider") in ("yahoo", "icloud", "aol", "yandex", "mailru", "zoho", "gmx"):
            print("  Энэ үйлчилгээ ихэвчлэн энгийн нууц үг биш 'App password' шаарддаг (README 3.3).")
        while True:
            pw = getpass.getpass("  Нууц үг (бичихэд харагдахгүй, хоосон = алгасах): ")
            if not pw:
                break
            imap_mail.set_password(acc["email"], pw)
            try:
                imap_mail.test_account(acc)
                print("  ✓ IMAP, SMTP хоёуланд амжилттай нэвтэрлээ. Нууц үг Windows Credential Manager-т хадгалагдлаа.")
                break
            except Exception as e:
                print(f"  ✗ Нэвтэрч чадсангүй: {e}\n    Сервер, порт, нууц үгээ шалгаад дахин оролдоно уу.")
    if source_enabled("telegram"):
        print("\n[Telegram] Утасны дугаараа (+976...) оруулаад, Telegram-д ирсэн кодыг бичнэ үү.")
        from .connectors import telegram
        asyncio.run(telegram.login())
    if (CFG.get("telegram_bot") or {}).get("enabled") or input("\nУтаснаас удирдах Telegram bot тохируулах уу? (y/N): ").strip().lower() == "y":
        from . import telegram_bot
        try:
            telegram_bot.setup_interactive()
        except Exception as e:
            print(f"  ✗ Telegram bot: {e}")
    if CFG.get("school_manager", {}).get("enabled"):
        print("\n[School Manager] Terre Bridge-тэй хувилбар суулгасан байх хэрэгтэй (README 3.5).")
    if DEMO and input("\nДемо горимоос гарч жинхэнэ холболтуудаар ажиллах уу? (y/N): ").strip().lower() == "y":
        save_config_value(["demo_mode"], False)
        print("  ✓ demo_mode: false")
    print("\nБэлэн. Terre System-ийг дахин асаахад (tray → хаах → Эхлэх цэснээс нээх) шинэ холболтууд идэвхжинэ.")
    input("\nEnter дарж хаана уу...")


if __name__ == "__main__":
    main()
