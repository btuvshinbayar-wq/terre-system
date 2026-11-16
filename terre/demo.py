"""Демо өгөгдөл — холболтгүйгээр самбар, дууг турших.

Хүний нэр зохиохгүй (зөвхөн албан тушаал, үүргээр). School Manager-ийн демо өгөгдөл байхгүй —
School Manager-ийн тоо зөвхөн жинхэнэ өгөгдлөөс харагдана.
"""
import datetime

from .config import now


def _t(minutes_ago):
    return (now() - datetime.timedelta(minutes=minutes_ago)).isoformat()


def messages():
    return [
        {"id": "demo:1", "source": "outlook", "sender": "Боловсролын газар",
         "subject": "ЯАРАЛТАЙ: 2-р улирлын ирцийн тайлан маргааш 12:00 цагаас өмнө",
         "body": "Сайн байна уу. 2-р улирлын сурагчдын ирцийн нэгдсэн тайланг маргааш 12:00 цагаас өмнө "
                 "хавсаргасан маягтын дагуу ирүүлнэ үү. Хоцорвол нэгдсэн тайланд орохгүй болохыг анхаарна уу.",
         "received": _t(40), "meta": {}},
        {"id": "demo:2", "source": "gmail", "sender": "Эцэг эх (10б анги)",
         "subject": "10б ангийн хүүхдийн SAT хичээлийн талаар",
         "body": "Сайн байна уу багшаа. Манай хүү 10б ангид сурдаг. SAT бэлтгэлийн хичээлд дундаас нь орж болох уу? "
                 "Хэдэн цагт, ямар өдрүүдэд хичээллэдэг вэ?",
         "received": _t(95), "meta": {}},
        {"id": "demo:3", "source": "gmail", "sender": "Canva", "subject": "Your weekly design digest",
         "body": "New templates this week... unsubscribe", "received": _t(130), "meta": {}},
        {"id": "demo:4", "source": "telegram", "sender": "Багш нарын групп", "subject": "Telegram (групп)",
         "body": "Гишүүн: Маргааш хурал хэдэн цагт билээ?\nГишүүн: 8:30 гэж сонссон", "received": _t(15), "meta": {}},
        {"id": "demo:5", "source": "gchat", "sender": "Сургалтын менежер", "subject": "Google Chat",
         "body": "Сайн уу, 11б ангийн mock test-ийн дүнг баасан гараг гэхэд нэгтгэж өгч чадах уу?",
         "received": _t(60), "meta": {}},
        {"id": "demo:6", "source": "gmail", "sender": "Google", "subject": "Security alert: new sign-in on Windows",
         "body": "We noticed a new sign-in to your Google Account on a Windows device. If this was you, no action needed.",
         "received": _t(300), "meta": {}},
        {"id": "demo:8", "source": "imap", "sender": "ЗАН ахлагч",
         "subject": "Математикийн ЗАН-ийн сарын төлөвлөгөө",
         "body": "Сайн байна уу. Математикийн заах аргын нэгдлийн 12-р сарын төлөвлөгөөг хавсаргав. "
                 "Санал байвал энэ долоо хоногт хэлээрэй.",
         "received": _t(75), "meta": {"account": "Сургуулийн мэйл"}},
        {"id": "demo:7", "source": "outlook", "sender": "Microsoft 365", "subject": "Newsletter: Teams-ийн шинэ боломжууд",
         "body": "Энэ сарын шинэчлэлүүд... no-reply", "received": _t(500), "meta": {}},
    ]


def calendar():
    return [
        {"time": "08:30", "title": "Шууд удирдлагын хурал", "location": "Захиралын өрөө", "source": "Outlook"},
        {"time": "11:00", "title": "SAT Math анги (11б)", "location": "304 тоот", "source": "Google"},
        {"time": "14:00", "title": "Эцэг эхийн уулзалт", "location": "Хурлын заал", "source": "Google"},
        {"time": "16:30", "title": "Боловсролын газрын онлайн хурал", "location": "Teams", "source": "Outlook"},
    ]


def purge():
    """Жинхэнэ горимд: демо горимын үед мэдээллийн санд үлдсэн зохиомол бичлэгүүдийг цэвэрлэнэ.

    Зөвхөн TED-ийн өөрийн демо бичлэгүүдийг (id нь "demo"-оор эхэлдэг) хасна. Компьютер дээрх файл, хавтсанд хүрэхгүй —
    демо хавтасны холболтыг л салгана.
    """
    from . import files, store
    n = 0
    with store._lock:
        n += store._db.execute("DELETE FROM items WHERE id LIKE 'demo:%'").rowcount
        store._db.commit()
    with files._lock:
        db = files._db
        n += db.execute("DELETE FROM files WHERE key GLOB 'demo[0-9]*'").rowcount
        try:
            n += db.execute("DELETE FROM tasks WHERE source_item LIKE 'demo:%'").rowcount
        except Exception:
            pass
        for r in db.execute("SELECT id FROM folders WHERE path LIKE '%TerreDemo%'").fetchall():
            try:
                job_ids = [j[0] for j in db.execute("SELECT id FROM jobs WHERE folder_id=?", (r[0],)).fetchall()]
                for jid in job_ids:
                    db.execute("DELETE FROM plan WHERE job_id=?", (jid,))
                db.execute("DELETE FROM jobs WHERE folder_id=?", (r[0],))
            except Exception:
                pass
            n += db.execute("DELETE FROM folders WHERE id=?", (r[0],)).rowcount
        db.commit()
    return n
