# test_walk_forward_offline.py
# -*- coding: utf-8 -*-
"""
تست آفلاین walk_forward.py با جایگزین‌کردن دریافت دیتای شبکه‌ای با دیتای مصنوعی.
هدف: اطمینان از اینکه کل چرخهٔ main() بدون خطا اجرا می‌شود.
"""
import numpy as np
import pandas as pd

import config
import backtest as bt
import walk_forward as wf
import test_logic_offline as t

np.random.seed(7)


def fake_prepare_symbol_data(symbol: str) -> pd.DataFrame:
    """جایگزین بدون‌شبکهٔ prepare_symbol_data - یک دیتافریم 4H با همان ستون‌های موردنیاز می‌سازد."""
    n_bars = 3200  # حدود ۱.۵ سال کندل ۴ساعته - برای چند پنجره Walk-Forward کافی است
    h4_df = t.make_fake_ohlcv(n_bars, "4h", "2023-01-01", base_price=100)
    daily_bars = 550
    daily_df = t.make_fake_ohlcv(daily_bars, "1D", "2022-01-01", base_price=100)

    import indicators as ind
    ema200 = ind.ema(daily_df["close"], config.EMA_PERIOD)
    daily_ema_shifted = pd.DataFrame({"ema200_daily": ema200.shift(1)})

    h4_df["momentum_4h"] = ind.momentum(h4_df["close"], config.MOMENTUM_PERIOD)
    h4_df["cmf_4h"] = ind.cmf(h4_df["high"], h4_df["low"], h4_df["close"], h4_df["volume"], config.CMF_PERIOD)
    h4_df["atr_4h"] = ind.atr(h4_df["high"], h4_df["low"], h4_df["close"], config.ATR_PERIOD)

    merged = pd.merge_asof(
        h4_df.sort_index(), daily_ema_shifted.sort_index(),
        left_index=True, right_index=True, direction="backward"
    )
    merged["symbol"] = symbol
    return merged


def run():
    print("=== تست آفلاین walk_forward.py ===\n")

    # مانکی‌پچ کردن تابع دریافت دیتا تا شبکه لازم نباشد
    bt.prepare_symbol_data = fake_prepare_symbol_data

    # بازهٔ بک‌تست کوتاه‌تر برای تست سریع (چون دیتای مصنوعی فقط ~۱.۵ سال دارد)
    original_start = config.BACKTEST_START
    original_end = config.BACKTEST_END
    config.BACKTEST_START = "2023-01-01"
    config.BACKTEST_END = "2024-06-01"

    try:
        wf.main()
    finally:
        config.BACKTEST_START = original_start
        config.BACKTEST_END = original_end

    import os
    details_path = os.path.join(wf.RESULTS_DIR, "walk_forward_details.csv")
    summary_path = os.path.join(wf.RESULTS_DIR, "walk_forward_summary.csv")
    assert os.path.exists(details_path), "فایل details ساخته نشد"
    assert os.path.exists(summary_path), "فایل summary ساخته نشد"

    details_df = pd.read_csv(details_path)
    summary_df = pd.read_csv(summary_path)
    assert len(details_df) > 0, "هیچ پنجره‌ای تحلیل نشد"
    assert len(summary_df) > 0, "خلاصه‌ای تولید نشد"

    print("\n✅ فایل‌های خروجی ساخته شدند و خالی نیستند")
    print(f"✅ {len(details_df)} ردیف در walk_forward_details.csv")
    print(f"✅ {len(summary_df)} ردیف در walk_forward_summary.csv")
    print("\n=== نتیجه: walk_forward.py از نظر نحوی و منطقی روی دیتای نمونه به‌درستی اجرا شد ===")


if __name__ == "__main__":
    run()
