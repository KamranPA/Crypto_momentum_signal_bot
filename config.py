# -*- coding: utf-8 -*-
"""
تنظیمات مرکزی استراتژی.
همهٔ پارامترهایی که قرار است بعداً در Walk-Forward تغییر داده شوند، اینجا نگه‌داری می‌شوند
تا نیازی به دست‌زدن به منطق اصلی کد نباشد.
"""

# --- واچ‌لیست ---
# فرمت CoinEx (ccxt): 'BTC/USDT'
SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]
BTC_SYMBOL = "BTC/USDT"

# --- نگاشت به تیکر یاهو فایننس (برای فallback دیتای تاریخی) ---
YAHOO_MAP = {
    "BTC/USDT": "BTC-USD",
    "ETH/USDT": "ETH-USD",
    "SOL/USDT": "SOL-USD",
    "BNB/USDT": "BNB-USD",
    "XRP/USDT": "XRP-USD",
}

# --- پارامترهای اندیکاتور ---
MOMENTUM_PERIOD = 21          # روی تایم‌فریم 4H
CMF_PERIOD = 21                # روی تایم‌فریم 4H
EMA_PERIOD = 200                # روی تایم‌فریم Daily

# --- آستانه‌های رژیم بیت‌کوین ---
BTC_BULLISH_CMF = 0.05
BTC_BEARISH_CMF = -0.05

# --- آستانهٔ ورود لانگ آلت‌کوین در رژیم خرسی BTC (قدرت نسبی) ---
ALT_LONG_IN_BEARISH_CMF = 0.10

# --- مدیریت خروج (برای بک‌تست الگوریتمی - نسخهٔ ساده‌شدهٔ قابل‌کدنویسی) ---
# توجه: سند اصلی خروج را "دستی/بر اساس Swing" تعریف کرده بود.
# برای بک‌تست خودکار، دو روش جایگزین و قابل‌اندازه‌گیری تعریف می‌کنیم:
EXIT_MODE = "atr_and_signal_flip"   # یا "signal_flip_only"
ATR_PERIOD = 14
ATR_STOP_MULTIPLIER = 2.0            # حد ضرر = entry -/+ (ATR * این عدد)
ATR_TARGET_MULTIPLIER = 4.0          # حد سود = entry -/+ (ATR * این عدد)  -> R:R پیش‌فرض 1:2

# --- بازهٔ زمانی بک‌تست ---
BACKTEST_START = "2023-01-01"
BACKTEST_END = None   # None یعنی تا امروز

# --- تایم‌فریم‌ها ---
TF_DAILY = "1d"
TF_4H = "4h"

# --- حداقل تعداد کندل مورد نیاز از CoinEx قبل از رفتن سراغ Yahoo ---
MIN_DAILY_BARS_REQUIRED = EMA_PERIOD + 60   # کمی بافر اضافه
MIN_4H_BARS_REQUIRED = 500                   # برای اینکه بک‌تست معنادار باشد

# --- کارمزد و اسلیپیج فرضی برای بک‌تست (درصد هر طرف معامله) ---
FEE_PCT = 0.10      # 0.10% کارمزد هر طرف (ورود/خروج) - عدد واقعی CoinEx را چک کنید
SLIPPAGE_PCT = 0.05  # 0.05% اسلیپیج فرضی هر طرف
