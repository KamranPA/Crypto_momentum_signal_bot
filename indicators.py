# -*- coding: utf-8 -*-
"""
محاسبهٔ اندیکاتورها به‌صورت دستی با pandas خالص.
عمداً از pandas_ta استفاده نشده تا وابستگی کمتر و کنترل بیشتری روی فرمول دقیق داشته باشیم
(و چون نسخه‌های pandas_ta گاهی با نسخه‌های جدید pandas ناسازگار می‌شوند).
"""
import numpy as np
import pandas as pd


def momentum(close: pd.Series, period: int) -> pd.Series:
    """درصد تغییر قیمت نسبت به `period` کندل قبل."""
    return ((close / close.shift(period)) - 1.0) * 100.0


def cmf(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int) -> pd.Series:
    """Chaikin Money Flow استاندارد."""
    hl_range = (high - low).replace(0, np.nan)  # جلوگیری از تقسیم بر صفر در کندل‌های بدون رنج
    mf_multiplier = ((close - low) - (high - close)) / hl_range
    mf_multiplier = mf_multiplier.fillna(0.0)
    mf_volume = mf_multiplier * volume
    cmf_val = mf_volume.rolling(period).sum() / volume.rolling(period).sum()
    return cmf_val


def ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    """Average True Range - برای حد ضرر/سود دینامیک در بک‌تست."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def btc_regime(momentum_val: float, cmf_val: float, bullish_cmf: float, bearish_cmf: float) -> str:
    """تعیین رژیم BTC بر اساس آخرین مقدار momentum و cmf (4H)."""
    if pd.isna(momentum_val) or pd.isna(cmf_val):
        return "UNKNOWN"
    if momentum_val > 0 and cmf_val > bullish_cmf:
        return "BULLISH"
    if momentum_val < 0 and cmf_val < bearish_cmf:
        return "BEARISH"
    return "RANGING"
