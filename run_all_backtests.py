# نام فایل: run_all_backtests.py
# مسیر: run_all_backtests.py  (ریشهٔ ریپازیتوری)
#
# همهٔ فایل‌های result/history_*.csv رو می‌خونه، بک‌تست OOS رولینگ رو (از
# backtest_v2.py / strategy.py) روش اجرا می‌کنه، و یک جدول خلاصه می‌سازه --
# دقیقاً مشابه جدولی که برای استراتژی قبلی پروژه دیدیم (نماد / بازدهٔ ترکیبی
# OOS / میانگین بازده هر پنجره / درصد پنجره‌های مثبت).
#
# توجه: چون CoinEx تاریخچهٔ buy/sell ratio نداره، فقط ۲ جزء (funding + MA50)
# در این بک‌تست واقعاً تست شدن؛ flow_score فقط برای اجرای زنده استفاده می‌شه.

import glob
import os

import pandas as pd

import strategy
from backtest_v2 import run_backtest as _run_backtest_3factor

RESULT_DIR = "result"


def compute_signal_2factor(row, funding_hist):
    """
    نسخهٔ مخصوص بک‌تست: چون buy_sell_ratio تاریخی در دسترس نیست، امتیاز فقط از
    funding + MA50 محاسبه می‌شه -- با بازنرمال‌سازی درست وزن‌ها (نه با جای‌گذاری
    یک مقدار خنثی در فرمول ۳جزئی، که باعث می‌شد سقف امتیاز از آستانه کمتر بمونه).
    """
    vs = strategy.volume_score(row["volume_24h_usd"])
    if vs == 0.0:
        return "HOLD", 0.0

    fs = strategy.funding_score(row["funding_rate"], funding_hist)
    ms = strategy.ma50_score(row["close"], row["ma50"])

    w_funding, w_ma50 = strategy.WEIGHTS["funding"], strategy.WEIGHTS["ma50"]
    raw_score = (w_funding * fs + w_ma50 * ms) / (w_funding + w_ma50)

    if raw_score >= strategy.SCORE_THRESHOLD:
        return "BUY", raw_score
    if raw_score <= -strategy.SCORE_THRESHOLD:
        return "SELL", raw_score
    return "HOLD", raw_score


def run_backtest_2factor(df, symbol, window_days=30, n_windows=22):
    """نسخهٔ run_backtest که از compute_signal_2factor بجای strategy.compute_signal استفاده می‌کنه."""
    import numpy as np

    df = df.copy()
    df["ma50"] = df["close"].rolling(50).mean()
    df["atr14"] = strategy.atr(df)
    df = df.dropna().reset_index(drop=True)

    bars_per_window = window_days * 6
    results = []

    for w in range(n_windows):
        start = w * bars_per_window
        end = start + bars_per_window
        if end >= len(df):
            break
        window = df.iloc[start:end]
        funding_hist = df["funding_rate"].iloc[max(0, start - 500):start]
        if len(funding_hist) < 100:
            continue

        trades = []
        position = None
        for _, row in window.iterrows():
            signal, score = compute_signal_2factor(row, funding_hist)

            if position is None and signal in ("BUY", "SELL"):
                stop = row["close"] - row["atr14"] * 2 if signal == "BUY" else row["close"] + row["atr14"] * 2
                target = row["close"] + row["atr14"] * 4 if signal == "BUY" else row["close"] - row["atr14"] * 4
                position = {"side": signal, "entry": row["close"], "stop": stop, "target": target}
                continue

            if position is not None:
                hit_stop = (row["low"] <= position["stop"]) if position["side"] == "BUY" else (row["high"] >= position["stop"])
                hit_target = (row["high"] >= position["target"]) if position["side"] == "BUY" else (row["low"] <= position["target"])
                if hit_stop or hit_target:
                    exit_price = position["stop"] if hit_stop else position["target"]
                    pnl_pct = (exit_price / position["entry"] - 1) * (1 if position["side"] == "BUY" else -1)
                    trades.append(pnl_pct)
                    position = None

        window_return = float(np.prod([1 + t for t in trades]) - 1) if trades else 0.0
        results.append({"window": w, "n_trades": len(trades), "window_return_pct": window_return * 100})

    results_df = pd.DataFrame(results)
    if results_df.empty:
        return {"symbol": symbol, "combined_oos_return_pct": None, "windows": results_df}

    combined_return = float(np.prod([1 + r / 100 for r in results_df["window_return_pct"]]) - 1) * 100
    pct_positive = float((results_df["window_return_pct"] > 0).mean() * 100)

    return {
        "symbol": symbol,
        "combined_oos_return_pct": combined_return,
        "mean_window_return_pct": float(results_df["window_return_pct"].mean()),
        "pct_positive_windows": pct_positive,
        "total_trades": int(results_df["n_trades"].sum()),
        "windows": results_df,
    }


def main():
    csv_files = sorted(glob.glob(f"{RESULT_DIR}/history_*.csv"))
    if not csv_files:
        print(f"هیچ فایل history_*.csv در پوشهٔ {RESULT_DIR}/ پیدا نشد.")
        return

    summary_rows = []
    for path in csv_files:
        symbol = os.path.basename(path).replace("history_", "").replace(".csv", "")
        print(f"\n=== بک‌تست {symbol} (فقط funding + MA50 -- flow_score تاریخی در دسترس نیست) ===")

        df = pd.read_csv(path, parse_dates=["timestamp"])

        result = run_backtest_2factor(df, symbol)
        if result["combined_oos_return_pct"] is None:
            print(f"  دیتای کافی برای {symbol} نبود (کمتر از یک پنجرهٔ کامل).")
            continue

        print(f"  بازدهٔ ترکیبی OOS: {result['combined_oos_return_pct']:.2f}%")
        print(f"  میانگین بازده هر پنجره: {result['mean_window_return_pct']:.2f}%")
        print(f"  درصد پنجره‌های مثبت: {result['pct_positive_windows']:.1f}%")
        print(f"  تعداد کل معاملات: {result['total_trades']}")

        summary_rows.append({
            "symbol": symbol,
            "combined_oos_return_pct": round(result["combined_oos_return_pct"], 2),
            "mean_window_return_pct": round(result["mean_window_return_pct"], 2),
            "pct_positive_windows": round(result["pct_positive_windows"], 1),
            "total_trades": result["total_trades"],
        })

    summary_df = pd.DataFrame(summary_rows)
    summary_path = f"{RESULT_DIR}/backtest_summary.csv"
    summary_df.to_csv(summary_path, index=False)
    print(f"\nجدول خلاصه ذخیره شد: {summary_path}")
    print("\n" + summary_df.to_string(index=False))
    print("\n⚠️ توجه: flow_score (نسبت خرید/فروش) در این بک‌تست تست نشده چون CoinEx")
    print("تاریخچهٔ این داده رو نداره -- فقط برای اجرای زنده (main.py) استفاده می‌شه.")


if __name__ == "__main__":
    main()
