# نام فایل: fetch_historical_data.py
# مسیر: fetch_historical_data.py  (ریشهٔ ریپازیتوری)
#
# قیمت (OHLCV): از Yahoo Finance با yfinance (دیتای ۱ ساعته -> resample به ۴ ساعته)
# funding rate: از CoinEx با ccxt (چون Yahoo Finance اصلاً مفهوم فاندینگ ریت رو نداره،
#               این بخش مخصوص بازار فیوچرزه و فقط از صرافی‌های مشتقه در دسترسه)
#
# خروجی: پوشهٔ result/ با فایل‌های history_BTC.csv, history_ETH.csv, ...
#
# نکته: yfinance برای دیتای ساعتی حداکثر ۷۳۰ روز گذشته رو می‌ده -- که دقیقاً
# همون بازهٔ ۲ سالهٔ بک‌تست قبلی پروژه‌ست.

import os
import time
import ccxt
import pandas as pd
import yfinance as yf

# نگاشت نماد -> (تیکر yahoo finance, نماد ccxt در CoinEx)
SYMBOLS = {
    "BTC": ("BTC-USD", "BTC/USDT:USDT"),
    "ETH": ("ETH-USD", "ETH/USDT:USDT"),
    "SOL": ("SOL-USD", "SOL/USDT:USDT"),
    "BNB": ("BNB-USD", "BNB/USDT:USDT"),
}

DAYS_BACK = 729  # کمی زیر سقف ۷۳۰ روزهٔ yfinance برای دیتای ساعتی
OUT_DIR = "result"


def fetch_price_yfinance(yahoo_ticker: str) -> pd.DataFrame:
    """دیتای ۱ ساعته از یاهو فایننس می‌گیره و به ۴ ساعته resample می‌کنه."""
    df = yf.download(yahoo_ticker, period=f"{DAYS_BACK}d", interval="1h", progress=False)
    if df.empty:
        raise RuntimeError(f"دیتایی از یاهو فایننس برای {yahoo_ticker} برنگشت.")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
    df.index.name = "timestamp"

    df_4h = df.resample("4h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna().reset_index()

    df_4h["timestamp"] = pd.to_datetime(df_4h["timestamp"]).dt.tz_localize(None)
    return df_4h


def fetch_full_funding_history(exchange, symbol: str, since_ms: int) -> pd.DataFrame:
    all_rows = []
    while True:
        batch = exchange.fetch_funding_rate_history(symbol, since=since_ms, limit=1000)
        if not batch:
            break
        all_rows += batch
        since_ms = batch[-1]["timestamp"] + 1
        if len(batch) < 1000:
            break
        time.sleep(exchange.rateLimit / 1000)

    fdf = pd.DataFrame(all_rows)
    fdf["timestamp"] = pd.to_datetime(fdf["timestamp"], unit="ms").dt.tz_localize(None)
    return fdf[["timestamp", "fundingRate"]].rename(columns={"fundingRate": "funding_rate"})


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    exchange = ccxt.coinex({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    since_ms = exchange.milliseconds() - DAYS_BACK * 24 * 60 * 60 * 1000

    for name, (yahoo_ticker, ccxt_symbol) in SYMBOLS.items():
        print(f"در حال دریافت {name} ...")

        price_df = fetch_price_yfinance(yahoo_ticker)
        funding_df = fetch_full_funding_history(exchange, ccxt_symbol, since_ms)

        price_df = price_df.sort_values("timestamp")
        funding_df = funding_df.sort_values("timestamp")
        merged = pd.merge_asof(price_df, funding_df, on="timestamp", direction="backward")
        merged["funding_rate"] = merged["funding_rate"].bfill()
        merged["volume_24h_usd"] = merged["volume"] * merged["close"]
        merged = merged.dropna(subset=["funding_rate"])

        out_path = f"{OUT_DIR}/history_{name}.csv"
        merged.to_csv(out_path, index=False)
        print(f"  ذخیره شد: {out_path} ({len(merged)} ردیف)")


if __name__ == "__main__":
    main()
