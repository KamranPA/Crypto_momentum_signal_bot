# نام فایل: telegram_notifier.py
# مسیر: telegram_notifier.py  (ریشهٔ ریپازیتوری)
#
# ارسال سیگنال به تلگرام. توکن و chat_id از GitHub Secrets میان (متغیر محیطی).

import os
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def send_signal_message(symbol: str, signal: str, score: float, row: dict) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN یا TELEGRAM_CHAT_ID تنظیم نشده (باید در GitHub Secrets باشه).")

    entry = row["close"]
    atr14 = row["atr14"]
    if signal == "BUY":
        stop = entry - atr14 * 2
        target = entry + atr14 * 4
        emoji = "🟢"
    else:
        stop = entry + atr14 * 2
        target = entry - atr14 * 4
        emoji = "🔴"

    text = (
        f"{emoji} سیگنال {signal} — {symbol}\n\n"
        f"قیمت ورود: {entry:.4f}\n"
        f"حد ضرر: {stop:.4f}\n"
        f"هدف: {target:.4f}\n"
        f"امتیاز سیگنال: {score:.2f}\n\n"
        f"funding_rate: {row['funding_rate']:.5f}\n"
        f"buy/sell ratio: {row['buy_sell_ratio']:.2f}\n"
        f"قیمت/MA50: {row['close'] / row['ma50']:.2f}\n\n"
        f"⚠️ این پیام فقط سیگنال است. معامله باید دستی یا با فاز بعدی ربات انجام شود."
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=15)
    resp.raise_for_status()
