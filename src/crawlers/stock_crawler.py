"""
Stock price history crawler using yfinance.
Replaces: python-job/crawl-stock-detail.py, python-job/crawl-korean-stock-detail.py
"""
import logging
from typing import Optional

import yfinance as yf
import pandas as pd

from src.utils import s3_util

logger = logging.getLogger(__name__)


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten MultiIndex columns returned by yfinance >= 0.2.31."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def _crawl_single_stock(symbol: str) -> Optional[dict]:
    """Download historical data for a single stock and return structured dict."""
    try:
        data = yf.download(symbol, start="1990-01-01", interval="1d", auto_adjust=False)
        if data.empty:
            logger.warning(f"No data for {symbol} (possibly delisted)")
            return None

        data = _flatten_columns(data)

        # Validate required columns exist
        required = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
        missing = [c for c in required if c not in data.columns]
        if missing:
            logger.error(f"Missing columns for {symbol}: {missing}")
            return None

        rows = []
        for index, row in data.iterrows():
            close_val = row["Close"]
            if pd.isna(close_val):
                continue
            rows.append({
                "date": index.strftime("%Y-%m-%d"),
                "open": float(row["Open"]) if pd.notna(row["Open"]) else None,
                "high": float(row["High"]) if pd.notna(row["High"]) else None,
                "low": float(row["Low"]) if pd.notna(row["Low"]) else None,
                "close": float(close_val),
                "adjClose": float(row["Adj Close"]) if pd.notna(row["Adj Close"]) else None,
                "volume": float(row["Volume"]) if pd.notna(row["Volume"]) else None,
            })

        if not rows:
            logger.warning(f"No valid price rows for {symbol}")
            return None

        tick = yf.Ticker(symbol)

        # Safely get info (some delisted tickers have minimal info)
        try:
            tick_info = tick.info or {}
        except Exception:
            tick_info = {}

        try:
            fast = tick.fast_info
            info = {
                "shortName": tick_info.get("shortName", ""),
                "longName": tick_info.get("longName", ""),
                "displayName": tick_info.get("shortName", ""),
                "dividendYield": tick_info.get("dividendYield", ""),
                "dividendRate": tick_info.get("dividendRate", ""),
                "forwardPE": tick_info.get("forwardPE", ""),
                "currency": fast.currency,
                "exchange": fast.exchange,
                "timezone": fast.timezone,
                "market_cap": fast.market_cap,
                "last_price": fast.last_price,
                "previous_close": fast.previous_close,
                "open": fast.open,
                "day_high": fast.day_high,
                "day_low": fast.day_low,
                "regular_market_previous_close": fast.regular_market_previous_close,
                "last_volume": fast.last_volume,
                "fifty_day_average": fast.fifty_day_average,
                "two_hundred_day_average": fast.two_hundred_day_average,
                "ten_day_average_volume": fast.ten_day_average_volume,
                "three_month_average_volume": fast.three_month_average_volume,
                "year_high": fast.year_high,
                "year_low": fast.year_low,
                "year_change": fast.year_change,
            }
            market_cap = fast.market_cap
        except Exception as e:
            logger.warning(f"fast_info unavailable for {symbol}: {e}")
            info = {
                "shortName": tick_info.get("shortName", ""),
                "longName": tick_info.get("longName", ""),
                "displayName": tick_info.get("shortName", ""),
                "dividendYield": tick_info.get("dividendYield", ""),
                "dividendRate": tick_info.get("dividendRate", ""),
            }
            market_cap = tick_info.get("marketCap")

        dividends = []
        try:
            for k, v in tick.dividends.items():
                dividends.append({"date": k.strftime("%Y-%m-%d"), "value": float(v)})
        except Exception:
            pass

        splits = []
        try:
            for k, v in tick.splits.items():
                splits.append({"date": k.strftime("%Y-%m-%d"), "value": float(v)})
        except Exception:
            pass

        return {
            "info": info,
            "market_cap": market_cap,
            "symbol": symbol,
            "dividends": dividends,
            "splits": splits,
            "histories": rows,
        }
    except Exception as e:
        logger.error(f"Error crawling {symbol}: {e}")
        return None


def crawl_us_stocks():
    """Crawl US stock data. Downloads symbol list from S3, then crawls each."""
    logger.info("Starting US stock crawl")
    symbol_list_key = "api-data/v1/json/investment/stock/us-stock/symbol-list.json"
    symbol_data = s3_util.download_json(symbol_list_key)
    symbols = [s["symbol"] for s in symbol_data]

    skip_list = ["WLTW", "XLNX", "CERN", "FB"]
    symbols = [s for s in symbols if s not in skip_list]

    error_list = []
    for symbol in symbols:
        logger.info(f"Crawling US stock: {symbol}")
        result = _crawl_single_stock(symbol)
        if result:
            object_key = f"crawl-result/v3/json/investment/us-stock-detail/{symbol}.json"
            s3_util.upload_json(object_key, result)
        else:
            error_list.append(symbol)

    if error_list:
        logger.warning(f"US stock errors ({len(error_list)}): {error_list[:10]}")
    return error_list


def crawl_korean_stocks():
    """Crawl Korean stock data. Downloads symbol list from S3, then crawls each."""
    logger.info("Starting Korean stock crawl")
    symbol_list_key = "api-data/v1/json/investment/stock/ko-stock/symbol-list.json"
    symbol_data = s3_util.download_json(symbol_list_key)
    symbols = [s["symbol"] for s in symbol_data]

    error_list = []
    for symbol in symbols:
        logger.info(f"Crawling KR stock: {symbol}")
        result = _crawl_single_stock(symbol)
        if result:
            object_key = f"crawl-result/v3/json/investment/kr-stock-detail/{symbol}.json"
            s3_util.upload_json(object_key, result)
        else:
            error_list.append(symbol)

    if error_list:
        logger.warning(f"KR stock errors ({len(error_list)}): {error_list[:10]}")
    return error_list
