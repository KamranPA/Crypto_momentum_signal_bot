# walk_forward.py
# -*- coding: utf-8 -*-
"""
Walk-Forward Optimization

به‌جای اینکه یک پارامتر را دستی روی کل بازه امتحان کنیم و ببینیم نتیجه چطور شد
(که ریسک Overfit شدن پارامتر روی همون بازهٔ خاص را دارد)، اینجا:

۱. دیتا را به پنجره‌های متوالی [Train][Test] تقسیم می‌کنیم
۲. روی هر Train، چند مقدار مختلف از پارامترهای ورود/خروج را امتحان می‌کنیم
   و بهترین را بر اساس Profit Factor انتخاب می‌کنیم
۳. همان پارامتر انتخاب‌شده (بدون هیچ تغییری) را روی Test - دیتایی که اصلاً
   در انتخاب پارامتر دخیل نبوده - اجرا می‌کنیم
۴. این چرخه را برای همهٔ پنجره‌ها تکرار می‌کنیم و نتیجهٔ Out-of-Sample را جمع می‌کنیم

اگر عملکرد Test به‌طور قابل‌توجه بدتر از Train باشد، یعنی پارامترها Overfit
شده‌اند و استراتژی به شکل فعلی قابل‌اعتماد نیست.

اجرا:
    python walk_forward.py

خروجی:
    - results/walk_forward_details.csv   جزئیات هر پنجره (پارامتر انتخابی + نتیجهٔ Train/Test)
    - results/walk_forward_summary.csv   خلاصهٔ Out-of-Sample هر ارز
"""
import os
import itertools
import warnings
import numpy as np
import pandas as pd

import config
import backtest as bt

warnings.filterwarnings("ignore")

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

# --- پارامترهایی که در دو دور قبلی دستی امتحان کردیم، حالا Walk-Forward
#     خودش برای هر پنجرهٔ زمانی بهترین مقدار را پیدا می‌کند ---
PARAM_GRID = {
    "ENTRY_CMF_THRESHOLD": [0.03, 0.05, 0.08],
    "EXIT_SIGNAL_FLIP_BUFFER": [0.0, 0.02, 0.05],
}

TRAIN_MONTHS = 6
TEST_MONTHS = 2
MIN_TRAIN_BARS = 100
MIN_TEST_BARS = 20


def generate_windows(start: str, end: str | None):
    """پنجره‌های متوالی [train_start,train_end) [test_start,test_end) تولید می‌کند."""
    windows = []
    train_start = pd.Timestamp(start, tz="utc")
    final_end = pd.Timestamp(end, tz="utc") if end else pd.Timestamp.now(tz="utc")

    while True:
        train_end = train_start + pd.DateOffset(months=TRAIN_MONTHS)
        test_end = train_end + pd.DateOffset(months=TEST_MONTHS)
        if test_end > final_end:
            break
        windows.append((train_start, train_end, train_end, test_end))
        train_start = train_start + pd.DateOffset(months=TEST_MONTHS)

    return windows


def set_params(params: dict):
    """پارامترها را روی ماژول config اعمال می‌کند (backtest.py همیشه از config.X تازه می‌خواند)."""
    for k, v in params.items():
        setattr(config, k, v)


def score_profit_factor(trades_df: pd.DataFrame) -> float:
    """
    معیار انتخاب پارامتر روی Train.
    اگر معاملات خیلی کم باشند (کمتر از ۵)، امتیاز خیلی پایین می‌گیرد تا انتخاب نشود
    (چون Profit Factor روی چند معاملهٔ کم قابل‌اعتماد نیست).
    """
    if trades_df.empty or len(trades_df) < 5:
        return -999.0
    wins = trades_df.loc[trades_df["pnl_pct_net"] > 0, "pnl_pct_net"].sum()
    losses = abs(trades_df.loc[trades_df["pnl_pct_net"] <= 0, "pnl_pct_net"].sum())
    if losses == 0:
        return wins if wins > 0 else 0.0
    return wins / losses


def run_symbol_walk_forward(symbol: str, full_df: pd.DataFrame, is_btc: bool) -> pd.DataFrame:
    windows = generate_windows(config.BACKTEST_START, config.BACKTEST_END)
    records = []

    for train_start, train_end, test_start, test_end in windows:
        train_df = full_df[(full_df.index >= train_start) & (full_df.index < train_end)]
        test_df = full_df[(full_df.index >= test_start) & (full_df.index < test_end)]

        if len(train_df) < MIN_TRAIN_BARS or len(test_df) < MIN_TEST_BARS:
            continue

        best_score = -np.inf
        best_params = None
        param_names = list(PARAM_GRID.keys())

        for combo in itertools.product(*PARAM_GRID.values()):
            params = dict(zip(param_names, combo))
            set_params(params)
            train_trades = bt.simulate_trades(train_df, symbol, is_btc)
            s = score_profit_factor(train_trades)
            if s > best_score:
                best_score = s
                best_params = params

        if best_params is None:
            continue

        # اعمال پارامتر انتخاب‌شده از Train، روی Test (دیتایی که در انتخاب پارامتر نقشی نداشت)
        set_params(best_params)
        test_trades = bt.simulate_trades(test_df, symbol, is_btc)
        test_summary = bt.summarize(test_trades, symbol)

        record = {
            "symbol": symbol,
            "train_start": train_start.date().isoformat(),
            "train_end": train_end.date().isoformat(),
            "test_start": test_start.date().isoformat(),
            "test_end": test_end.date().isoformat(),
            "train_profit_factor": round(best_score, 3) if best_score not in (-np.inf, -999.0) else None,
            "test_num_trades": test_summary["num_trades"],
            "test_win_rate_pct": test_summary["win_rate_pct"],
            "test_profit_factor": test_summary["profit_factor"],
            "test_total_return_pct": test_summary["total_return_pct_compounded"],
        }
        for k, v in best_params.items():
            record[f"param_{k}"] = v
        records.append(record)

    return pd.DataFrame(records)


def build_summary(details_df: pd.DataFrame) -> pd.DataFrame:
    summaries = []
    for symbol, g in details_df.groupby("symbol"):
        combined_trades = int(g["test_num_trades"].sum())

        if combined_trades > 0:
            weighted_wr = (g["test_win_rate_pct"].fillna(0) * g["test_num_trades"]).sum() / combined_trades
        else:
            weighted_wr = None

        # profit_factor گاهی رشتهٔ "inf" است (وقتی هیچ ضرری رخ نداده) - برای میانگین‌گیری عددی می‌کنیم
        test_pf_numeric = pd.to_numeric(g["test_profit_factor"], errors="coerce")
        avg_test_pf = test_pf_numeric.mean()
        avg_train_pf = g["train_profit_factor"].mean()

        # ترکیب بازده‌های Out-of-Sample به‌صورت متوالی (compounding سادهٔ فرضی)
        equity = 1.0
        for r in g["test_total_return_pct"]:
            if pd.notna(r):
                equity *= (1 + r / 100.0)
        combined_return_pct = (equity - 1) * 100

        overfit_gap = None
        if pd.notna(avg_train_pf) and pd.notna(avg_test_pf):
            overfit_gap = round(avg_train_pf - avg_test_pf, 3)

        summaries.append({
            "symbol": symbol,
            "num_windows": len(g),
            "combined_test_trades": combined_trades,
            "weighted_test_win_rate_pct": round(weighted_wr, 2) if weighted_wr is not None else None,
            "avg_train_profit_factor": round(avg_train_pf, 3) if pd.notna(avg_train_pf) else None,
            "avg_test_profit_factor": round(avg_test_pf, 3) if pd.notna(avg_test_pf) else None,
            "overfit_gap_train_minus_test": overfit_gap,
            "combined_out_of_sample_return_pct": round(combined_return_pct, 2),
        })

    return pd.DataFrame(summaries)


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    print("=== Walk-Forward Optimization ===\n")
    print(f"پارامترهای تحت جستجو: {PARAM_GRID}")
    print(f"Train: {TRAIN_MONTHS} ماه | Test: {TEST_MONTHS} ماه\n")

    # ذخیرهٔ مقادیر اصلی config تا در پایان بازگردانده شوند (پاک بودن state برای اجراهای بعدی)
    original_params = {k: getattr(config, k) for k in PARAM_GRID.keys()}

    print("در حال دریافت و آماده‌سازی دیتای BTC (برای تعیین رژیم بازار)...")
    btc_data = bt.prepare_symbol_data(config.BTC_SYMBOL)
    if btc_data.empty:
        print("❌ دیتای BTC دریافت نشد. اجرا متوقف شد.")
        return
    btc_data["btc_regime"] = bt.compute_btc_regime_series(btc_data)

    all_details = []

    for symbol in config.SYMBOLS:
        is_btc = symbol == config.BTC_SYMBOL
        print(f"\nWalk-Forward برای {symbol} ...")

        if is_btc:
            df = btc_data.copy()
        else:
            df = bt.prepare_symbol_data(symbol)
            if df.empty:
                print(f"  ⚠️ دیتا برای {symbol} در دسترس نبود، رد شد.")
                continue
            df = pd.merge_asof(
                df.sort_index(),
                btc_data[["btc_regime"]].sort_index(),
                left_index=True, right_index=True, direction="backward",
            )

        details = run_symbol_walk_forward(symbol, df, is_btc)
        if details.empty:
            print(f"  ⚠️ دیتای کافی برای هیچ پنجره‌ای در {symbol} وجود نداشت.")
            continue

        all_details.append(details)
        print(f"  ✅ {len(details)} پنجره تحلیل شد.")

    # بازگرداندن config به مقادیر اصلی
    set_params(original_params)

    if not all_details:
        print("\n❌ هیچ نتیجه‌ای تولید نشد (دیتای کافی برای هیچ نمادی وجود نداشت).")
        return

    details_df = pd.concat(all_details, ignore_index=True)
    details_path = os.path.join(RESULTS_DIR, "walk_forward_details.csv")
    details_df.to_csv(details_path, index=False, encoding="utf-8-sig")

    summary_df = build_summary(details_df)
    summary_path = os.path.join(RESULTS_DIR, "walk_forward_summary.csv")
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")

    print("\n=== خلاصهٔ Out-of-Sample (Walk-Forward) ===")
    print(summary_df.to_string(index=False))
    print(f"\nجزئیات کامل هر پنجره در: {details_path}")
    print(
        "\nنکته: اگر avg_train_profit_factor به‌طور قابل‌توجه بالاتر از avg_test_profit_factor باشد "
        "(overfit_gap_train_minus_test بزرگ و مثبت)، یعنی پارامترها روی Train بیش‌برازش (Overfit) شده‌اند "
        "و عملکرد Train گمراه‌کننده است - فقط به avg_test_profit_factor و combined_out_of_sample_return_pct اعتماد کنید."
    )


if __name__ == "__main__":
    main()
