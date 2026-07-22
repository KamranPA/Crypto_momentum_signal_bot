# نام فایل: strategy.py
# مسیر: strategy.py  (ریشهٔ ریپازیتوری)
#
# منطق سیگنال مشترک -- هم backtest_v2.py و هم main.py (اجرای زنده) این فایل رو
# import می‌کنن. این کار عمداً انجام شده تا هیچ‌وقت منطق بک‌تست و لایو از هم
# جدا نشن (یکی از رایج‌ترین دلایل شکست ربات‌های معاملاتی، اختلاف بین کدی که
# بک‌تست شده و کدی که واقعاً اجرا می‌شه است).

import pandas as pd

WEIGHTS = {"funding": 0.40, "flow": 0.30, "ma50": 0.20, "volume": 0.10}
SCORE_THRESHOLD = 0.70
MIN_VOLUME_USD = 50_000_000


def funding_score(funding_rate: float, funding_hist: pd.Series) -> float:
    """
    آستانه از صدک تاریخی خودِ دارایی محاسبه می‌شه (نه عدد ثابت حدسی).
    +1 = اشباع فروش شدید (سیگنال خرید) / -1 = اشباع خرید شدید (سیگنال فروش)
    """
    if len(funding_hist) < 100:
        return 0.0
    p05 = funding_hist.quantile(0.05)
    p95 = funding_hist.quantile(0.95)
    if funding_rate <= p05:
        return 1.0
    if funding_rate >= p95:
        return -1.0
    return 0.0


def flow_score(buy_sell_ratio: float) -> float:
    """
    buy_sell_ratio = volume_buy / volume_sell از GET /futures/market-ticker در CoinEx.
    جایگزین Open Interest (که fetchOpenInterestHistory برای CoinEx در ccxt پشتیبانی نمی‌شه).
    """
    if buy_sell_ratio > 1.15:
        return 1.0
    if buy_sell_ratio < 0.87:
        return -1.0
    return 0.0


def ma50_score(price: float, ma50: float) -> float:
    ratio = price / ma50
    if ratio < 0.85:
        return 1.0
    if ratio > 1.15:
        return -1.0
    return 0.0


def volume_score(volume_24h_usd: float, min_volume_usd: float = MIN_VOLUME_USD) -> float:
    return 1.0 if volume_24h_usd > min_volume_usd else 0.0


def compute_signal(row: pd.Series, funding_hist: pd.Series) -> tuple[str, float]:
    """
    row باید شامل کلیدهای: close, funding_rate, buy_sell_ratio, ma50, volume_24h_usd باشه.
    خروجی: ("BUY" | "SELL" | "HOLD", raw_score)
    """
    vs = volume_score(row["volume_24h_usd"])
    if vs == 0.0:
        return "HOLD", 0.0

    fs = funding_score(row["funding_rate"], funding_hist)
    fl = flow_score(row["buy_sell_ratio"])
    ms = ma50_score(row["close"], row["ma50"])

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
