# backtest.py
# -*- coding: utf-8 -*-
"""
بک‌تست سادهٔ استراتژی (مرحلهٔ ۱).

هدف این مرحله فقط این است: آیا اصلاً این استراتژی روی دادهٔ گذشته سودآور بوده یا نه؟
این اسکریپت Walk-Forward نیست (آن مرحلهٔ بعدی است) - اینجا فقط یک بار روی کل بازه
با پارامترهای ثابت config.py تست می‌کنیم.

اجرا:
    python backtest.py

خروجی:
    - results/trades_<SYMBOL>.csv   جزئیات تک‌تک معاملات
    - results/summary.csv           خلاصهٔ عملکرد هر ارز
    - چاپ خلاصه در ترمینال

پیش‌نیاز نصب:
    pip install ccxt pandas yfinance numpy
"""
import os
import warnings
import pandas as pd
import numpy as np

import config
import indicators as ind
import data_fetcher as fetcher

warnings.filterwarnings("ignore")

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def prepare_symbol_data(symbol: str) -> pd.DataFrame:
    """
    برای یک نماد: دیتای روزانه + 4H را می‌گیرد، اندیکاتورها را حساب می‌کند،
    و یک دیتافریم واحد در تایم‌فریم 4H برمی‌گرداند که شامل ستون EMA200 روزانهٔ
    "به‌روز تا آن لحظه" هم هست (بدون look-ahead - یعنی فقط از کندل روزانهٔ بسته‌شدهٔ قبلی استفاده می‌شود).
    """
    yahoo_ticker = config.YAHOO_MAP[symbol]

    daily_df, daily_source = fetcher.get_daily_data(
        symbol, yahoo_ticker, config.BACKTEST_START, config.BACKTEST_END, config.MIN_DAILY_BARS_REQUIRED
    )
    h4_df, h4_source = fetcher.get_4h_data(
        symbol, yahoo_ticker, config.BACKTEST_START, config.MIN_4H_BARS_REQUIRED
    )

    print(f"  [{symbol}] دیتای روزانه: {len(daily_df)} کندل (منبع: {daily_source}) | "
          f"دیتای 4H: {len(h4_df)} کندل (منبع: {h4_source})")

    if daily_df.empty or h4_df.empty:
        return pd.DataFrame()

    # --- اندیکاتورهای روزانه ---
    daily_df = daily_df.copy()
    daily_df["ema200"] = ind.ema(daily_df["close"], config.EMA_PERIOD)
    # مهم: برای جلوگیری از look-ahead، EMA200 هر روز را با یک روز تأخیر منتقل می‌کنیم
    # یعنی کندل 4H در روز جاری فقط از EMA200 "روز قبل (بسته‌شده)" استفاده می‌کند.
    daily_ema_shifted = daily_df[["ema200"]].shift(1)
    daily_ema_shifted = daily_ema_shifted.rename(columns={"ema200": "ema200_daily"})

    # --- اندیکاتورهای 4H ---
    h4_df = h4_df.copy()
    h4_df["momentum_4h"] = ind.momentum(h4_df["close"], config.MOMENTUM_PERIOD)
    h4_df["cmf_4h"] = ind.cmf(h4_df["high"], h4_df["low"], h4_df["close"], h4_df["volume"], config.CMF_PERIOD)
    h4_df["atr_4h"] = ind.atr(h4_df["high"], h4_df["low"], h4_df["close"], config.ATR_PERIOD)

    # --- ادغام EMA200 روزانه در جدول 4H (merge_asof = فقط آخرین مقدار روزانهٔ *قبلاً بسته‌شده*) ---
    h4_df = h4_df.sort_index()
    daily_ema_shifted = daily_ema_shifted.sort_index()
    merged = pd.merge_asof(
        h4_df, daily_ema_shifted, left_index=True, right_index=True, direction="backward"
    )

    merged["symbol"] = symbol
    return merged


def compute_btc_regime_series(btc_df: pd.DataFrame) -> pd.Series:
    """رژیم BTC را برای هر کندل 4H محاسبه می‌کند (بدون look-ahead - همان کندل بسته‌شده)."""
    def _regime_row(row):
        return ind.btc_regime(row["momentum_4h"], row["cmf_4h"], config.BTC_BULLISH_CMF, config.BTC_BEARISH_CMF)

    return btc_df.apply(_regime_row, axis=1)


def check_entry(row, is_btc: bool, btc_regime_val: str) -> str | None:
    """
    بررسی شرایط ورود برای یک ردیف (کندل 4H) بر اساس بخش ۴ سند استراتژی.
    خروجی: 'LONG', 'SHORT' یا None
    """
    if pd.isna(row["ema200_daily"]) or pd.isna(row["momentum_4h"]) or pd.isna(row["cmf_4h"]):
        return None

    price = row["close"]
    momentum_ok_long = row["momentum_4h"] > 0
    momentum_ok_short = row["momentum_4h"] < 0
    cmf_ok_long = row["cmf_4h"] > 0
    cmf_ok_short = row["cmf_4h"] < 0
    trend_ok_long = price > row["ema200_daily"]
    trend_ok_short = price < row["ema200_daily"]

    long_base = trend_ok_long and momentum_ok_long and cmf_ok_long
    short_base = trend_ok_short and momentum_ok_short and cmf_ok_short

    if is_btc:
        if long_base:
            return "LONG"
        if short_base:
            return "SHORT"
        return None

    # منطق آلت‌کوین‌ها - وابسته به رژیم BTC
    if long_base:
        if btc_regime_val in ("BULLISH", "RANGING"):
            return "LONG"
        if btc_regime_val == "BEARISH" and row["cmf_4h"] > config.ALT_LONG_IN_BEARISH_CMF:
            return "LONG"
        return None

    if short_base:
        if btc_regime_val in ("BEARISH", "RANGING"):
            return "SHORT"
        # هرگز شورت آلت‌کوین در بازار گاوی BTC
        return None

    return None


def simulate_trades(df: pd.DataFrame, symbol: str, is_btc: bool) -> pd.DataFrame:
    """
    شبیه‌سازی معاملات روی یک نماد.
    منطق خروج (چون سند اصلی خروج را دستی/Swing تعریف کرده بود و برای بک‌تست خودکار
    قابل‌کدنویسی نیست، اینجا از دو روش قابل‌اندازه‌گیری استفاده می‌کنیم):
      1) Stop-loss و Take-profit بر اساس ATR در لحظهٔ ورود
      2) اگر سیگنال معکوس شود (momentum/cmf برگردد) قبل از رسیدن به SL/TP، با آن قیمت خارج می‌شویم
    هر لحظه حداکثر یک پوزیشن باز برای هر نماد (بدون هم‌پوشانی).
    """
    trades = []
    position = None  # dict: {'side','entry_price','entry_time','stop','target'}

    for ts, row in df.iterrows():
        if pd.isna(row.get("atr_4h")):
            continue

        # --- اگر پوزیشن باز داریم، اول بررسی خروج ---
        if position is not None:
            exit_price = None
            exit_reason = None

            if position["side"] == "LONG":
                if row["low"] <= position["stop"]:
                    exit_price, exit_reason = position["stop"], "STOP_LOSS"
                elif row["high"] >= position["target"]:
                    exit_price, exit_reason = position["target"], "TAKE_PROFIT"
                elif row["cmf_4h"] < 0:
                    exit_price, exit_reason = row["close"], "SIGNAL_FLIP"
            else:  # SHORT
                if row["high"] >= position["stop"]:
                    exit_price, exit_reason = position["stop"], "STOP_LOSS"
                elif row["low"] <= position["target"]:
                    exit_price, exit_reason = position["target"], "TAKE_PROFIT"
                elif row["cmf_4h"] > 0:
                    exit_price, exit_reason = row["close"], "SIGNAL_FLIP"

            if exit_price is not None:
                fee_slip = (config.FEE_PCT + config.SLIPPAGE_PCT) / 100.0
                gross_pct = (exit_price - position["entry_price"]) / position["entry_price"] * 100
                if position["side"] == "SHORT":
                    gross_pct = -gross_pct
                net_pct = gross_pct - (fee_slip * 100 * 2)  # کارمزد ورود+خروج

                trades.append({
                    "symbol": symbol,
                    "side": position["side"],
                    "entry_time": position["entry_time"],
                    "entry_price": position["entry_price"],
                    "exit_time": ts,
                    "exit_price": exit_price,
                    "exit_reason": exit_reason,
                    "pnl_pct_gross": round(gross_pct, 3),
                    "pnl_pct_net": round(net_pct, 3),
                })
                position = None

        # --- اگر پوزیشنی باز نیست، بررسی ورود جدید ---
        if position is None:
            btc_regime_val = row.get("btc_regime", "RANGING")
            signal = check_entry(row, is_btc, btc_regime_val)
            if signal is not None:
                atr_val = row["atr_4h"]
                entry_price = row["close"]
                if signal == "LONG":
                    stop = entry_price - atr_val * config.ATR_STOP_MULTIPLIER
                    target = entry_price + atr_val * config.ATR_TARGET_MULTIPLIER
                else:
                    stop = entry_price + atr_val * config.ATR_STOP_MULTIPLIER
                    target = entry_price - atr_val * config.ATR_TARGET_MULTIPLIER

                position = {
                    "side": signal,
                    "entry_price": entry_price,
                    "entry_time": ts,
                    "stop": stop,
                    "target": target,
                }

    return pd.DataFrame(trades)


def summarize(trades_df: pd.DataFrame, symbol: str) -> dict:
    if trades_df.empty:
        return {
            "symbol": symbol, "num_trades": 0, "win_rate_pct": None,
            "avg_pnl_pct_net": None, "profit_factor": None,
            "max_drawdown_pct": None, "total_return_pct_compounded": None,
        }

    wins = trades_df[trades_df["pnl_pct_net"] > 0]
    losses = trades_df[trades_df["pnl_pct_net"] <= 0]

    win_rate = len(wins) / len(trades_df) * 100
    gross_profit = wins["pnl_pct_net"].sum()
    gross_loss = abs(losses["pnl_pct_net"].sum())
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else np.inf

    # equity curve فرضی (compounding سادهٔ فرضی، بدون در نظر گرفتن هم‌پوشانی چند پوزیشن)
    equity = (1 + trades_df["pnl_pct_net"] / 100).cumprod()
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max * 100
    max_dd = drawdown.min()
    total_return = (equity.iloc[-1] - 1) * 100

    return {
        "symbol": symbol,
        "num_trades": len(trades_df),
        "win_rate_pct": round(win_rate, 2),
        "avg_pnl_pct_net": round(trades_df["pnl_pct_net"].mean(), 3),
        "profit_factor": round(profit_factor, 2) if profit_factor != np.inf else "inf",
        "max_drawdown_pct": round(max_dd, 2),
        "total_return_pct_compounded": round(total_return, 2),
    }


def diagnose_exit_reasons(trades_df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """
    شکست معاملات بر اساس دلیل خروج (STOP_LOSS / TAKE_PROFIT / SIGNAL_FLIP)
    تا مشخص شود مشکل اصلی کجاست: حد ضرر خیلی تنگ؟ خروج زودهنگام با برگشت CMF؟
    """
    if trades_df.empty:
        return pd.DataFrame()

    grouped = trades_df.groupby("exit_reason").agg(
        count=("pnl_pct_net", "count"),
        avg_pnl_pct_net=("pnl_pct_net", "mean"),
        win_rate_pct=("pnl_pct_net", lambda s: round((s > 0).mean() * 100, 2)),
    ).reset_index()
    grouped["symbol"] = symbol
    grouped["pct_of_trades"] = round(grouped["count"] / len(trades_df) * 100, 1)
    return grouped[["symbol", "exit_reason", "count", "pct_of_trades", "win_rate_pct", "avg_pnl_pct_net"]]


def main():

    os.makedirs(RESULTS_DIR, exist_ok=True)
    print("=== مرحلهٔ ۱: بک‌تست ساده ===\n")

    print("در حال دریافت و آماده‌سازی دیتای BTC (برای تعیین رژیم بازار)...")
    btc_data = prepare_symbol_data(config.BTC_SYMBOL)
    if btc_data.empty:
        print("❌ دیتای BTC دریافت نشد. اجرا متوقف شد.")
        return
    btc_data["btc_regime"] = compute_btc_regime_series(btc_data)

    all_summaries = []
    all_diagnostics = []

    for symbol in config.SYMBOLS:
        print(f"\nدر حال پردازش {symbol} ...")
        is_btc = symbol == config.BTC_SYMBOL

        if is_btc:
            df = btc_data.copy()
        else:
            df = prepare_symbol_data(symbol)
            if df.empty:
                print(f"  ⚠️ دیتا برای {symbol} در دسترس نبود، رد شد.")
                continue
            # ادغام رژیم BTC بر اساس نزدیک‌ترین کندل زمانی (بدون look-ahead)
            df = pd.merge_asof(
                df.sort_index(),
                btc_data[["btc_regime"]].sort_index(),
                left_index=True, right_index=True, direction="backward",
            )

        trades_df = simulate_trades(df, symbol, is_btc)
        trades_path = os.path.join(RESULTS_DIR, f"trades_{symbol.replace('/', '_')}.csv")
        trades_df.to_csv(trades_path, index=False, encoding="utf-8-sig")

        summary = summarize(trades_df, symbol)
        all_summaries.append(summary)
        print(f"  ✅ {summary['num_trades']} معامله | Win Rate: {summary['win_rate_pct']}% | "
              f"Profit Factor: {summary['profit_factor']} | Max DD: {summary['max_drawdown_pct']}%")

        diag = diagnose_exit_reasons(trades_df, symbol)
        if not diag.empty:
            all_diagnostics.append(diag)

    summary_df = pd.DataFrame(all_summaries)
    summary_path = os.path.join(RESULTS_DIR, "summary.csv")
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")

    if all_diagnostics:
        diagnostics_df = pd.concat(all_diagnostics, ignore_index=True)
        diagnostics_path = os.path.join(RESULTS_DIR, "diagnostics.csv")
        diagnostics_df.to_csv(diagnostics_path, index=False, encoding="utf-8-sig")
        print("\n=== تشخیص دلیل خروج معاملات (برای فهمیدن نقطهٔ ضعف) ===")
        print(diagnostics_df.to_string(index=False))

    print("\n=== خلاصهٔ نهایی ===")
    print(summary_df.to_string(index=False))
    print(f"\nنتایج کامل در پوشهٔ: {RESULTS_DIR}")


if __name__ == "__main__":
    main()
