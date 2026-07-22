# نام فایل: main.py
# مسیر: main.py  (ریشهٔ ریپازیتوری)
#
# نقطهٔ ورود اجرای زنده. توسط .github/workflows/signal.yml هر ۴ ساعت اجرا می‌شه:
#   ۱) برای هر نماد، دیتای زنده از CoinEx می‌گیره (data_fetcher.py)
#   ۲) سیگنال رو با همون منطق بک‌تست‌شده محاسبه می‌کنه (strategy.py)
#   ۳) اگه BUY/SELL بود و قبلاً برای همون نماد در ۴ ساعت اخیر سیگنال نفرستاده،
#      به تلگرام می‌فرسته (telegram_notifier.py)
#
# state.json وضعیت آخرین سیگنال هر نماد رو نگه می‌داره تا از اسپم جلوگیری بشه.
# این فایل توسط خودِ GitHub Action کامیت می‌شه (نیازی به Supabase در فاز اول نیست؛
# اگه بعداً Supabase وصل شد، فقط کافیه توابع load_state/save_state عوض بشن).

import json
import os
import sys
from pathlib import Path

import strategy
import data_fetcher
import telegram_notifier

SYMBOLS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "BNB/USDT:USDT"]
STATE_FILE = Path("state.json")


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def main() -> None:
    exchange = data_fetcher.get_exchange()
    state = load_state()
    sent_count = 0
    MAX_SIGNALS_PER_RUN = 2  # مطابق محدودیت طرح اولیه: حداکثر ۲ سیگنال در هر اجرا

    for symbol in SYMBOLS:
        if sent_count >= MAX_SIGNALS_PER_RUN:
            print(f"سقف {MAX_SIGNALS_PER_RUN} سیگنال در این اجرا پر شد، بقیهٔ نمادها رد شدن.")
            break
        try:
            row, funding_hist = data_fetcher.build_signal_row(exchange, symbol)
        except Exception as exc:
            print(f"[خطا] دریافت دیتای {symbol} شکست خورد: {exc}", file=sys.stderr)
            continue

        signal, score = strategy.compute_signal(row, funding_hist)
        print(f"{symbol}: {signal} (score={score:.2f})")

        if signal == "HOLD":
            continue

        # جلوگیری از سیگنال تکراری برای همون جهت در ۴ ساعت اخیر
        last = state.get(symbol)
        if last and last.get("signal") == signal:
            print(f"سیگنال {signal} برای {symbol} قبلاً ارسال شده، رد شد.")
            continue

        try:
            telegram_notifier.send_signal_message(symbol, signal, score, row)
            sent_count += 1
            state[symbol] = {"signal": signal, "score": score}
        except Exception as exc:
            print(f"[خطا] ارسال تلگرام برای {symbol} شکست خورد: {exc}", file=sys.stderr)

    save_state(state)


if __name__ == "__main__":
    main()
