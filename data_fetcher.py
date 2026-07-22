# نام فایل: data_fetcher.py
# مسیر: data_fetcher.py  (ریشهٔ ریپازیتوری)
#
# دریافت دیتای زنده از CoinEx برای محاسبهٔ سیگنال.
# نیازی به API Key نیست چون همهٔ این داده‌ها عمومی هستن (endpoint های public).
#
# منابع دیتا:
#   - OHLCV                -> ccxt یکپارچه: exchange.fetch_ohlcv (برای MA50 و ATR)
#   - Funding Rate History -> ccxt یکپارچه: exchange.fetch_funding_rate_history
#   - Buy/Sell Volume      -> فیلد خام CoinEx (volume_buy / volume_sell) که در
#                              info خام fetch_tickers برمی‌گرده -- در ccxt یکپارچه
#                              نیست، برای همین از دادهٔ raw استفاده می‌کنیم.

import ccxt
import pandas as pd


def get_exchange() -> ccxt.coinex:
    return ccxt.coinex({"enableRateLimit": True, "options": {"defaultType": "swap"}})


def fetch_ohlcv_df(exchange: ccxt.coinex, symbol: str, timeframe: str = "4h", limit: int = 500) -> pd.DataFrame:
    """symbol مثل 'BTC/USDT:USDT' (فرمت ccxt برای فیوچرز خطی)."""
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def fetch_funding_rate_history_series(exchange: ccxt.coinex, symbol: str, limit: int = 500) -> pd.Series:
    raw = exchange.fetch_funding_rate_history(symbol, limit=limit)
    rates = [r["fundingRate"] for r in raw if r.get("fundingRate") is not None]
    return pd.Series(rates)


def fetch_current_funding_rate(exchange: ccxt.coinex, symbol: str) -> float:
    fr = exchange.fetch_funding_rate(symbol)
    return float(fr["fundingRate"])


def fetch_buy_sell_ratio_and_volume(exchange: ccxt.coinex, symbol: str) -> tuple[float, float]:
    """
    برمی‌گردونه: (buy_sell_ratio, volume_24h_usd)
    از فیلدهای خام CoinEx: volume_buy, volume_sell, value (ارزش دلاری ۲۴ ساعته)
    که در ticker['info'] در دسترسن (چون در unified ccxt ticker نیستن).
    """
    ticker = exchange.fetch_ticker(symbol)
    info = ticker.get("info", {})
    volume_buy = float(info.get("volume_buy", 0) or 0)
    volume_sell = float(info.get("volume_sell", 0) or 0)
    volume_24h_usd = float(info.get("value", 0) or 0)

    if volume_sell == 0:
        buy_sell_ratio = 1.0  # حالت خنثی وقتی دیتا در دسترس نیست
    else:
        buy_sell_ratio = volume_buy / volume_sell

    return buy_sell_ratio, volume_24h_usd


def build_signal_row(exchange: ccxt.coinex, symbol: str) -> tuple[dict, pd.Series]:
    """
    یک اسنپ‌شات کامل برای محاسبهٔ سیگنال یک نماد می‌سازه.
    خروجی: (row_dict برای strategy.compute_signal, funding_hist برای صدک‌گیری)
    """
    df = fetch_ohlcv_df(exchange, symbol)
    df["ma50"] = df["close"].rolling(50).mean()
    last = df.iloc[-1]

    funding_hist = fetch_funding_rate_history_series(exchange, symbol)
    current_funding = fetch_current_funding_rate(exchange, symbol)
    buy_sell_ratio, volume_24h_usd = fetch_buy_sell_ratio_and_volume(exchange, symbol)

    row = {
        "close": float(last["close"]),
        "ma50": float(last["ma50"]),
        "funding_rate": current_funding,
        "buy_sell_ratio": buy_sell_ratio,
        "volume_24h_usd": volume_24h_usd,
        "atr14": float(_atr_last(df)),
    }
    return row, funding_hist


def _atr_last(df: pd.DataFrame, period: int = 14) -> float:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1]
