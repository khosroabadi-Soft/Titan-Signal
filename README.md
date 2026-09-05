# Titan Signal v4.0.0

<p align="center">
  <img src="https://img.shields.io/badge/Version-4.0.0-blueviolet" alt="Version">
  <img src="https://img.shields.io/badge/Python-3.11-blue" alt="Python">
  <img src="https://img.shields.io/badge/Exit-Trailing%20Stop-orange" alt="Trailing">
  <img src="https://img.shields.io/badge/Telegram-Reply%20Support-26A5E4" alt="Telegram">
  <img src="https://img.shields.io/badge/Schedule-30min%20Live-green" alt="Schedule">
</p>

سیستم خودکار تولید و مدیریت سیگنال فیوچرز کریپتو با **Trailing Stop**، ذخیره در ریپو، و پیام‌های فاخر تلگرام.

---

## نسخه ۴ چه چیزی دارد؟

| قابلیت | توضیح |
|--------|--------|
| **مدیریت لایو** | در هر اجرای بات، اول سیگنال‌های OPEN با دادهٔ زنده بسته می‌شوند، بعد سیگنال جدید ساخته می‌شود |
| **ریپلای تلگرام** | نتیجهٔ خروج روی **همان پیام سیگنال اصلی** ریپلای می‌شود (`telegram_message_id`) |
| **نام کامل سناریو** | مثلاً «کرونوس (Cronus)» نه فقط `S3` |
| **زمان‌بندی** | هر ۳۰ دقیقه ۷–۲۲ تهران + دو اجرای سخت‌گیرانه ۲۳ و ۰۰ |
| **ذخیره در ریپو** | `data/titan_signal.db` و CSV روزانه با commit در Actions |
| **نسخه‌گذاری** | `titansignal/version.py` + نمایش نسخه در workflow و لاگ |

---

## معماری

```
GitHub Actions
├── signal-bot.yml (v4.0.0)     هر ۳۰ دقیقه، ۷–۲۲ تهران
│     └─ bot.py
│           1) process_open_signals()  ← بستن با trail
│           2) fetch KuCoin + rules    ← سیگنال جدید
│           3) Telegram + DB + CSV
│
└── nightly-monitor.yml (v4.0.0)  ۲۳:۰۰ و ۰۰:۰۰ تهران
      └─ monitor.py  TITAN_MONITOR_MODE=final
            1) trail + EOD_FORCE_CLOSE
            2) گزارش روزانه + هشدار بازمانده‌ها
```

### خروج از معامله (Trailing)

1. استاپ اولیه ≈ ۴٪ از ورود (`sl_pct`)
2. اگر قیمت به اندازهٔ `trail_activate` به نفع برود → تریل روشن
3. استاپ متحرک ≈ قفل `trail_lock` (معمولاً ۹۰٪) از حداکثر حرکت مطلوب
4. در غیر این صورت: `MAX_HOLD` یا در شب `EOD_FORCE_CLOSE`

ثوابت مالی پیش‌فرض: مارجین **$۱۰**، اهرم **۱۰×**، پوزیشن **$۱۰۰**، کارمزد رفت‌وبرگشت حدود **$۰.۲۰**.

---

## سناریوها

| ID | نام | جهت تقریبی | نکته |
|----|-----|------------|------|
| S1 | پرومتئوس (Prometheus) | LONG | فیلتر RSI zone روی S1 |
| S2 | ایاپتوس (Iapetus) | SHORT | — |
| S3 | کرونوس (Cronus) | BOTH | فعال‌ترین در عمل |
| B1 | هایپریون (Hyperion) | LONG | — |
| B2 | اطلس (Atlas) | SHORT | `trail_activate` عریض‌تر |

پارامترهای دقیق (`sl_pct`, `trail_*`, `max_hold_candles`, آستانه وزن) در `titansignal/config.py`.

---

## ساختار پروژه

```
Titan-Signal-main/
├── bot.py                 # سیکل لایو: مدیریت باز + سیگنال جدید
├── monitor.py             # مدیریت / گزارش نهایی شب
├── requirements.txt
├── Dockerfile / docker-compose.yml
├── data/
│   ├── titan_signal.db    # SQLite (در ریپو با force-add)
│   └── signals/YYYY-MM-DD.csv
├── scripts/
│   ├── test_system.py
│   └── fetch_data.py
├── .github/workflows/
│   ├── signal-bot.yml           # v4.0.0
│   └── nightly-monitor.yml      # v4.0.0
└── titansignal/
    ├── version.py         # __version__ = 4.0.0
    ├── config.py
    ├── database.py        # Signal + telegram_message_id + migration
    ├── rules.py           # ۱۷ قانون + پیام سیگنال جدید
    ├── trailing.py        # موتور trail مشترک
    ├── telegram_util.py   # ارسال، ریپلای، fmt_price، نام سناریو
    ├── indicators.py
    ├── patterns.py
    └── signal_store.py
```

---

## راه‌اندازی روی GitHub Actions

### ۱) Secrets

| Secret | الزامی | توضیح |
|--------|--------|--------|
| `TELEGRAM_BOT_TOKEN` | بله | توکن ربات |
| `TELEGRAM_CHAT_ID` | بله | آیدی کانال/چت (برای کانال معمولاً `-100...`) |
| `TITAN_DATABASE_URL` | خیر | خالی = `sqlite:///data/titan_signal.db` |

### ۲) دسترسی workflow

**Settings → Actions → General → Workflow permissions**  
→ **Read and write permissions**

ربات تلگرام در کانال باید **ادمین** باشد تا ریپلای کار کند.

### ۳) زمان‌بندی (تهران UTC+۳:۳۰)

| workflow | زمان تهران | کار |
|----------|------------|-----|
| `Titan Signal Bot v4.0.0` | هر ۳۰ دقیقه ۷:۰۰–۲۲:۰۰ | لایو |
| `Titan Signal Night Final v4.0.0` | ۲۳:۰۰ و ۰۰:۰۰ | بستن اجباری + گزارش روز |

اجرای دستی: **Actions → workflow → Run workflow**.

### ۴) اولین اجرا

1. یک بار `signal-bot` را دستی Run کنید.  
2. یک بار `Night Final` را دستی Run کنید.  
3. پوشهٔ `data/` باید در ریپو commit شود.

---

## تلگرام

### سیگنال جدید
- سناریو با نام کامل فارسی/انگلیسی  
- ورود، استاپ اولیه، پارامتر تریل  
- لیست قوانین پاس/رد (محدود برای طول پیام)  
- `message_id` در DB ذخیره می‌شود  

### نتیجه خروج
- **ریپلای** روی پیام همان سیگنال (اگر `telegram_message_id` موجود باشد)  
- نام کامل سناریو + کد  
- نوع خروج: استاپ اولیه / تریل / سقف زمان / بستن اجباری  
- PnL و ROI مارجین  

### گزارش شبانه
- آمار بسته‌شده‌ها، نرخ برد روی بسته‌ها، PnL روز  
- لیست بازمانده‌ها + **هشدار مسئولیت با کاربر**  

محدودیت‌ها: تکه پیام ~۳۹۰۰ کاراکتر، فاصله ~۱ ثانیه بین پیام‌ها، retry روی rate limit.

---

## دیتابیس

- مسیر پیش‌فرض: `sqlite:///data/titan_signal.db`  
- migration خودکار ستون‌های جدید (از جمله `telegram_message_id`)  
- فیلدهای مهم سیگنال: ورود/استاپ، پارامتر تریل، `status`, `outcome`, PnL، `telegram_message_id`  

CSV روزانه در `data/signals/` **شامل message_id نیست**؛ فقط خلاصه است. برای ریپلای فقط DB معیار است.

---

## اجرای محلی

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
mkdir -p data/signals

python bot.py                          # لایو
TITAN_MONITOR_MODE=final python monitor.py   # گزارش نهایی
python scripts/test_system.py
```

---

## متغیرهای محیطی

| متغیر | پیش‌فرض | نقش |
|-------|---------|-----|
| `TELEGRAM_BOT_TOKEN` | خالی | ارسال پیام |
| `TELEGRAM_CHAT_ID` | خالی | مقصد |
| `TITAN_DATABASE_URL` | `sqlite:///data/titan_signal.db` | اتصال DB |
| `TITAN_MONITOR_MODE` | `manage` | `final` = force close + گزارش روز |

---

## تاریخچه نسخه

| نسخه | خلاصه |
|------|--------|
| **4.0.0** | ریپلای تلگرام، نام کامل سناریو، نسخه در workflow/لاگ، README کامل، مدیریت لایو نیم‌ساعته |
| 3.x | تریل، ذخیره در ریپو، ادغام بستن در بات، گزارش شبانه |
| 2.x | قوانین وزن‌دار و سناریوها |

کد نسخه: `titansignal/version.py` → `__version__ = "4.0.0"`.

---

## هشدار مهم

این نرم‌افزار **سیگنال و ثبت نتیجه** است، نه ربات اجرای سفارش روی صرافی.  
سیگنال‌های بازمانده بعد از اجرای شبانه در مسئولیت کاربر است.  
معاملات کریپتو ریسک بالا دارد؛ از این سیستم فقط به‌عنوان ابزار کمکی استفاده کنید.

---

## لایسنس

MIT (در صورت تمایل در ریپو حفظ یا تغییر دهید).
