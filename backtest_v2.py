# نام فایل: backtest_v2.py
# مسیر: /mnt/user-data/outputs/backtest_v2.py
#
# بک‌تست استراتژی نسخهٔ ۲: اشباع فاندینگ + تأیید جریان (Open Interest بجای ETF/Whale) + انحراف از MA50
# روش: Out-of-Sample رولینگ، مشابه متدولوژی بک‌تست قبلی پروژه.
#
# این فایل خودش قابل اجراست: در انتها یک دیتای شبیه‌سازی‌شده (synthetic) می‌سازه
# و run_backtest رو روش تست می‌کنه تا مطمئن بشیم منطق بدون باگ اجرا می‌شه.
# برای بک‌تست واقعی، باید df رو با دیتای واقعی OHLCV/funding/OI (از ccxt) جایگزین کنید.

import pandas as pd
import numpy as np

WEIGHTS = {"funding": 0.40, "flow": 0.30, "ma50": 0.20, "volume": 0.10}
SCORE_THRESHOLD = 0.70


def funding_score(funding_rate: float, funding_hist: pd.Series) -> float:
    p05 = funding_hist.quantile(0.05)
    p95 = funding_hist.quantile(0.95)
    if funding_rate <= p05:
        return 1.0
    if funding_rate >= p95:
        return -1.0
    return 0.0


def flow_score(buy_sell_ratio: float) -> float:
    """
    بجای Open Interest (که fetchOpenInterestHistory برای CoinEx در ccxt پشتیبانی نمی‌شه)،
    از نسبت واقعی حجم خرید/فروش تیکر استفاده می‌کنیم -- مستقیماً از فیلدهای
    volume_buy و volume_sell که خودِ CoinEx در GET /futures/market-ticker برمی‌گردونه.
    buy_sell_ratio = volume_buy / volume_sell
    این معیار از OI هم به مفهوم "تأیید جریان واقعی سفارش" نزدیک‌تره، چون جهت‌دار هست.
    """
    if buy_sell_ratio > 1.15:   # فشار خرید واقعی محسوس
        return 1.0
    if buy_sell_ratio < 0.87:  # فشار فروش واقعی محسوس (معکوس ۱.۱۵)
        return -1.0
    return 0.0


def ma50_score(price: float, ma50: float) -> float:
    ratio = price / ma50
    if ratio < 0.85:
        return 1.0
    if ratio > 1.15:
        return -1.0
    return 0.0


def volume_score(volume_24h_usd: float, min_volume_usd: float = 50_000_000) -> float:
    return 1.0 if volume_24h_usd > min_volume_usd else 0.0


def compute_signal(row: pd.Series, funding_hist: pd.Series):
    fs = funding_score(row["funding_rate"], funding_hist)
    fl = flow_score(row["buy_sell_ratio"])
    ms = ma50_score(row["close"], row["ma50"])
    vs = volume_score(row["volume_24h_usd"])

    if vs == 0.0:
        return "HOLD", 0.0

    raw_score = (
        WEIGHTS["funding"] * fs + WEIGHTS["flow"] * fl + WEIGHTS["ma50"] * ms
    ) / (WEIGHTS["funding"] + WEIGHTS["flow"] + WEIGHTS["ma50"])

    if raw_score >= SCORE_THRESHOLD:
        return "BUY", raw_score
    if raw_score <= -SCORE_THRESHOLD:
        return "SELL", raw_score
    return "HOLD", raw_score


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def run_backtest(df: pd.DataFrame, symbol: str, window_days: int = 30, n_windows: int = 22):
    """
    df باید شامل ستون‌های زیر باشه (تایم‌فریم ۴ ساعته):
    timestamp, open, high, low, close, volume_24h_usd, funding_rate, buy_sell_ratio
    (buy_sell_ratio = volume_buy / volume_sell از GET /futures/market-ticker در CoinEx)
    """
    df = df.copy()
    df["ma50"] = df["close"].rolling(50).mean()
    df["atr14"] = atr(df)
    df = df.dropna().reset_index(drop=True)

    bars_per_window = window_days * 6  # هر ۴ ساعت یک کندل
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
            signal, score = compute_signal(row, funding_hist)

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


def _make_synthetic_data(n_bars: int = 5000, seed: int = 42) -> pd.DataFrame:
    """فقط برای تست سلامت کد -- این دیتای واقعی نیست و نتیجه‌اش معنای معاملاتی نداره."""
    rng = np.random.default_rng(seed)
    price = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n_bars)))
    high = price * (1 + np.abs(rng.normal(0, 0.005, n_bars)))
    low = price * (1 - np.abs(rng.normal(0, 0.005, n_bars)))
    open_ = price * (1 + rng.normal(0, 0.002, n_bars))
    funding_rate = rng.normal(0.0001, 0.0003, n_bars)
    buy_sell_ratio = np.exp(rng.normal(0, 0.15, n_bars))  # حول ۱.۰ نوسان می‌کنه، مثل نسبت واقعی
    volume_24h_usd = rng.uniform(40_000_000, 200_000_000, n_bars)
    timestamp = pd.date_range("2023-01-01", periods=n_bars, freq="4h")
    return pd.DataFrame({
        "timestamp": timestamp, "open": open_, "high": high, "low": low, "close": price,
        "volume_24h_usd": volume_24h_usd, "funding_rate": funding_rate, "buy_sell_ratio": buy_sell_ratio,
    })


if __name__ == "__main__":
    print("=== تست سلامت کد با دیتای synthetic (فقط بررسی باگ، نتیجه معاملاتی معتبر نیست) ===\n")
    df = _make_synthetic_data()
    result = run_backtest(df, "SYNTHETIC-TEST")
    print(f"نماد: {result['symbol']}")
    print(f"بازدهٔ ترکیبی OOS: {result['combined_oos_return_pct']:.2f}%")
    print(f"میانگین بازده هر پنجره: {result['mean_window_return_pct']:.2f}%")
    print(f"درصد پنجره‌های مثبت: {result['pct_positive_windows']:.1f}%")
    print(f"تعداد کل معاملات: {result['total_trades']}")
    print("\nاجرا بدون خطا کامل شد ✅")
