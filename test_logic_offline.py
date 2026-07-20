# test_logic_offline.py
# -*- coding: utf-8 -*-
"""
تست آفلاین منطق بک‌تست با دیتای مصنوعی تصادفی (Random Walk).
هدف: فقط اطمینان از صحت اجرای کد و نبود باگ نحوی/منطقی آشکار - نه اعتبارسنجی استراتژی.
این اسکریپت جایگزین اجرای واقعی روی دیتای CoinEx/Yahoo نیست.
"""
import numpy as np
import pandas as pd

import config
import indicators as ind
import backtest as bt

np.random.seed(42)


def make_fake_ohlcv(n_bars: int, freq: str, start: str, base_price: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range(start=start, periods=n_bars, freq=freq, tz="utc")
    returns = np.random.normal(loc=0.0002, scale=0.02, size=n_bars)
    close = base_price * (1 + returns).cumprod()
    high = close * (1 + np.abs(np.random.normal(0, 0.005, n_bars)))
    low = close * (1 - np.abs(np.random.normal(0, 0.005, n_bars)))
    open_ = close * (1 + np.random.normal(0, 0.002, n_bars))
    volume = np.random.uniform(1000, 5000, n_bars)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)
    return df


def run():
    print("=== تست آفلاین (دیتای مصنوعی) ===\n")

    daily_bars = 400
    h4_bars = 2400  # حدود 400 روز از کندل 4 ساعته

    daily_df = make_fake_ohlcv(daily_bars, "1D", "2023-01-01", base_price=100)
    h4_df = make_fake_ohlcv(h4_bars, "4h", "2023-01-01", base_price=100)

    # --- تست indicators.py ---
    ema200 = ind.ema(daily_df["close"], config.EMA_PERIOD)
    assert ema200.notna().sum() > 0, "EMA200 محاسبه نشد"

    momentum = ind.momentum(h4_df["close"], config.MOMENTUM_PERIOD)
    assert momentum.notna().sum() > 0, "Momentum محاسبه نشد"

    cmf = ind.cmf(h4_df["high"], h4_df["low"], h4_df["close"], h4_df["volume"], config.CMF_PERIOD)
    # نکته: NaNهای ابتدای سری (قبل از پر شدن پنجرهٔ rolling) طبیعی هستند؛ باید قبل از چک بازه dropna شوند
    # (چون Series.between روی NaN مقدار False می‌دهد، نه NaN - پس باید dropna قبل از between باشد)
    assert cmf.dropna().between(-1.001, 1.001).all(), "CMF خارج از محدودهٔ منطقی [-1,1]"

    atr = ind.atr(h4_df["high"], h4_df["low"], h4_df["close"], config.ATR_PERIOD)
    assert (atr.dropna() >= 0).all(), "ATR نمی‌تواند منفی باشد"

    regime = ind.btc_regime(1.5, 0.1, config.BTC_BULLISH_CMF, config.BTC_BEARISH_CMF)
    assert regime == "BULLISH", f"رژیم اشتباه: {regime}"
    regime2 = ind.btc_regime(-1.5, -0.1, config.BTC_BULLISH_CMF, config.BTC_BEARISH_CMF)
    assert regime2 == "BEARISH", f"رژیم اشتباه: {regime2}"
    regime3 = ind.btc_regime(0.5, 0.01, config.BTC_BULLISH_CMF, config.BTC_BEARISH_CMF)
    assert regime3 == "RANGING", f"رژیم اشتباه: {regime3}"
    print("✅ indicators.py: همهٔ محاسبات پایه صحیح هستند")

    # --- تست merge_asof بدون look-ahead ---
    daily_ema_shifted = pd.DataFrame({"ema200_daily": ema200.shift(1)})
    merged = pd.merge_asof(
        h4_df.sort_index(), daily_ema_shifted.sort_index(),
        left_index=True, right_index=True, direction="backward"
    )
    assert "ema200_daily" in merged.columns
    print("✅ ادغام EMA200 روزانه در جدول 4H بدون خطا انجام شد")

    # --- تست کامل simulate_trades با دیتای ساختگی مشابه خروجی prepare_symbol_data ---
    merged["momentum_4h"] = momentum
    merged["cmf_4h"] = cmf
    merged["atr_4h"] = atr
    merged["btc_regime"] = "RANGING"
    merged["symbol"] = "FAKE/USDT"

    trades_df = bt.simulate_trades(merged, "FAKE/USDT", is_btc=True)
    print(f"✅ simulate_trades اجرا شد بدون خطا -> {len(trades_df)} معامله شبیه‌سازی‌شده روی دیتای رندوم")

    if not trades_df.empty:
        summary = bt.summarize(trades_df, "FAKE/USDT")
        print(f"✅ summarize اجرا شد -> {summary}")
        # چک‌های Sanity
        assert trades_df["pnl_pct_net"].notna().all(), "PnL شامل NaN است"
        assert (trades_df["exit_time"] > trades_df["entry_time"]).all(), "زمان خروج باید بعد از ورود باشد"
        print("✅ چک‌های Sanity (بدون NaN، ترتیب زمانی درست) پاس شدند")
    else:
        print("⚠️ هیچ معامله‌ای روی دیتای مصنوعی رندوم رخ نداد (ممکن است طبیعی باشد - شرایط ورود سخت‌گیرانه است)")

    print("\n=== نتیجه: کد از نظر نحوی و منطقی روی دیتای نمونه به‌درستی اجرا شد ===")
    print("(این تست اعتبار استراتژی را نشان نمی‌دهد - فقط صحت اجرای کد)")


if __name__ == "__main__":
    run()
