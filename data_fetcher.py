# data_fetcher.py
# -*- coding: utf-8 -*-
"""
لایهٔ دریافت دیتا.

منطق:
1. همیشه اول تلاش می‌کنیم دیتا را از CoinEx (از طریق ccxt) بگیریم،
   چون هدف نهایی معامله روی همین صرافی است و رفتار قیمتی/حجمی آن ممکن است
   با صرافی‌های دیگر کمی فرق داشته باشد.
2. اگر تعداد کندل‌های برگشتی از CoinEx کمتر از حداقل لازم برای بک‌تست بود
   (چون CoinEx معمولاً تاریخچهٔ محدودی می‌دهد)، به‌صورت خودکار سراغ Yahoo Finance
   می‌رویم تا عمق تاریخی کافی برای EMA200 روزانه و بک‌تست چندماهه داشته باشیم.
3. دیتای Yahoo فقط برای *بک‌تست* استفاده می‌شود، نه برای اجرای زنده -
   اجرای زنده و سیگنال‌دهی نهایی همیشه باید از CoinEx بخواند.

نکته دربارهٔ Yahoo + تایم‌فریم 4 ساعته:
Yahoo Finance تایم‌فریم 4h ندارد. حداکثر دقتی که برای بازه‌های طولانی می‌دهد 1h است
(و آن‌هم فقط برای ~730 روز گذشته). بنابراین وقتی به Yahoo فallback می‌کنیم،
دیتای 1h را می‌گیریم و با resample به 4H تبدیل می‌کنیم.
"""
import time
import pandas as pd

try:
    import ccxt
except ImportError:
    ccxt = None

try:
    import yfinance as yf
except ImportError:
    yf = None


def _ohlcv_list_to_df(ohlcv: list) -> pd.DataFrame:
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    return df


def fetch_coinex_ohlcv(symbol: str, timeframe: str, since_ms: int = None, limit: int = 1000) -> pd.DataFrame:
    """
    دریافت کندل از CoinEx با صفحه‌بندی (چون هر درخواست ccxt معمولاً محدود به ~1000 کندل است).
    اگر CoinEx برای این نماد/تایم‌فریم داده نداشته باشد، DataFrame خالی برمی‌گرداند.
    """
    if ccxt is None:
        raise RuntimeError("پکیج ccxt نصب نیست. اجرا کنید: pip install ccxt")

    exchange = ccxt.coinex({"enableRateLimit": True})
    all_rows = []
    fetch_since = since_ms

    while True:
        try:
            batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=fetch_since, limit=limit)
        except Exception as e:
            print(f"[CoinEx] خطا در دریافت {symbol} {timeframe}: {e}")
            break

        if not batch:
            break

        all_rows.extend(batch)

        if len(batch) < limit:
            break

        last_ts = batch[-1][0]
        # جلوگیری از حلقهٔ بی‌نهایت اگر last_ts پیشرفت نکند
        if fetch_since is not None and last_ts <= fetch_since:
            break
        fetch_since = last_ts + 1
        time.sleep(exchange.rateLimit / 1000.0)

    if not all_rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = _ohlcv_list_to_df(all_rows)
    df = df[~df.index.duplicated(keep="first")].sort_index()
    return df


def fetch_yahoo_daily(yahoo_ticker: str, start: str, end: str = None) -> pd.DataFrame:
    """دریافت دیتای روزانه از Yahoo Finance."""
    if yf is None:
        raise RuntimeError("پکیج yfinance نصب نیست. اجرا کنید: pip install yfinance")

    df = yf.download(yahoo_ticker, start=start, end=end, interval="1d", progress=False, auto_adjust=False)
    if df.empty:
        return df
    df = df.rename(columns=str.lower)
    df.index = pd.to_datetime(df.index, utc=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    return df[["open", "high", "low", "close", "volume"]]


def fetch_yahoo_4h(yahoo_ticker: str) -> pd.DataFrame:
    """
    دریافت دیتای 1H از Yahoo (حداکثر ~730 روز گذشته) و resample به 4H.
    """
    if yf is None:
        raise RuntimeError("پکیج yfinance نصب نیست. اجرا کنید: pip install yfinance")

    df = yf.download(yahoo_ticker, period="730d", interval="1h", progress=False, auto_adjust=False)
    if df.empty:
        return df
    df = df.rename(columns=str.lower)
    df.index = pd.to_datetime(df.index, utc=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]]

    resampled = df.resample("4h", origin="epoch").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    resampled = resampled.dropna(subset=["open", "high", "low", "close"])
    return resampled


def _has_sufficient_coverage(df: pd.DataFrame, start: str, min_bars: int, coverage_tolerance_days: int = 60) -> bool:
    """
    چک واقعی کافی‌بودن دیتا: هم تعداد کندل کافی باشد، هم واقعاً از نزدیکی start شروع شده باشد.
    قبلاً فقط تعداد کندل چک می‌شد که باگ داشت: اگر صرافی فقط ۶۰۰ کندل اخیر (نه از ابتدای بازه) برگرداند
    ولی این عدد از حداقل لازم بیشتر بود، به‌اشتباه "کافی" تشخیص داده می‌شد در حالی که عمق تاریخی واقعی
    خیلی کمتر از بازهٔ درخواستی بود.
    """
    if df.empty or len(df) < min_bars:
        return False
    start_ts = pd.Timestamp(start, tz="utc")
    earliest = df.index.min()
    return earliest <= start_ts + pd.Timedelta(days=coverage_tolerance_days)


def get_daily_data(symbol: str, yahoo_ticker: str, start: str, end: str, min_bars_required: int) -> tuple[pd.DataFrame, str]:
    """
    دیتای روزانه را برمی‌گرداند + منبعی که استفاده شد ('coinex' یا 'yahoo').
    اول CoinEx امتحان می‌شود؛ اگر کافی نبود (چه از نظر تعداد چه از نظر عمق تاریخی واقعی)، Yahoo.
    """
    since_ms = int(pd.Timestamp(start, tz="utc").timestamp() * 1000)
    df_coinex = pd.DataFrame()
    try:
        df_coinex = fetch_coinex_ohlcv(symbol, "1d", since_ms=since_ms)
    except Exception as e:
        print(f"[CoinEx][daily] خطا برای {symbol}: {e}")

    if _has_sufficient_coverage(df_coinex, start, min_bars_required):
        print(f"  [{symbol}][daily] CoinEx کافی است: "
              f"{df_coinex.index.min().date()} تا {df_coinex.index.max().date()} ({len(df_coinex)} کندل)")
        return df_coinex, "coinex"

    if not df_coinex.empty:
        print(f"[Fallback] دیتای روزانهٔ CoinEx برای {symbol} پوشش کافی ندارد "
              f"(فقط از {df_coinex.index.min().date()}, {len(df_coinex)} کندل - نه از {start}) "
              f"-> رفتن سراغ Yahoo Finance")
    else:
        print(f"[Fallback] دیتای روزانهٔ CoinEx برای {symbol} خالی بود -> رفتن سراغ Yahoo Finance")

    df_yahoo = fetch_yahoo_daily(yahoo_ticker, start=start, end=end)
    if not df_yahoo.empty:
        print(f"  [{symbol}][daily] Yahoo: {df_yahoo.index.min().date()} تا {df_yahoo.index.max().date()} "
              f"({len(df_yahoo)} کندل)")
    return df_yahoo, "yahoo"


def get_4h_data(symbol: str, yahoo_ticker: str, start: str, min_bars_required: int) -> tuple[pd.DataFrame, str]:
    """
    دیتای 4 ساعته را برمی‌گرداند + منبعی که استفاده شد.
    اول CoinEx امتحان می‌شود؛ اگر کافی نبود (تعداد یا عمق تاریخی)، Yahoo (resample از 1h).

    توجه مهم: Yahoo برای تایم‌فریم 1H (که پایهٔ resample به 4H است) حداکثر ~730 روز گذشته را می‌دهد.
    یعنی حتی با fallback، عمق تاریخی 4H هرگز نمی‌تواند بیشتر از ~2 سال گذشته باشد -
    این یک محدودیت واقعی Yahoo است، نه باگ.
    """
    since_ms = int(pd.Timestamp(start, tz="utc").timestamp() * 1000)
    df_coinex = pd.DataFrame()
    try:
        df_coinex = fetch_coinex_ohlcv(symbol, "4h", since_ms=since_ms)
    except Exception as e:
        print(f"[CoinEx][4h] خطا برای {symbol}: {e}")

    if _has_sufficient_coverage(df_coinex, start, min_bars_required):
        print(f"  [{symbol}][4h] CoinEx کافی است: "
              f"{df_coinex.index.min().date()} تا {df_coinex.index.max().date()} ({len(df_coinex)} کندل)")
        return df_coinex, "coinex"

    if not df_coinex.empty:
        print(f"[Fallback] دیتای 4Hی CoinEx برای {symbol} پوشش کافی ندارد "
              f"(فقط از {df_coinex.index.min().date()}, {len(df_coinex)} کندل - نه از {start}) "
              f"-> رفتن سراغ Yahoo Finance (resample از 1H، حداکثر ~730 روز گذشته)")
    else:
        print(f"[Fallback] دیتای 4Hی CoinEx برای {symbol} خالی بود -> رفتن سراغ Yahoo Finance")

    df_yahoo = fetch_yahoo_4h(yahoo_ticker)
    if not df_yahoo.empty:
        print(f"  [{symbol}][4h] Yahoo: {df_yahoo.index.min().date()} تا {df_yahoo.index.max().date()} "
              f"({len(df_yahoo)} کندل)")
    return df_yahoo, "yahoo"
