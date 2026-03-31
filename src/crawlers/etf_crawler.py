"""
ETF price history crawler using yfinance + yahooquery.
Replaces: python-job/crawl-etf-detail.py
"""
import logging
from typing import Optional

import yfinance as yf
import pandas as pd
from yahooquery import Ticker

from src.utils import s3_util

logger = logging.getLogger(__name__)


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten MultiIndex columns returned by yfinance >= 0.2.31."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def _crawl_single_etf(symbol: str) -> Optional[dict]:
    """Download historical data for a single ETF and return structured dict."""
    try:
        data = yf.download(symbol, start="1990-01-01", interval="1d", auto_adjust=False)
        if data.empty:
            logger.warning(f"No data for ETF {symbol} (possibly delisted)")
            return None

        data = _flatten_columns(data)

        required = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
        missing = [c for c in required if c not in data.columns]
        if missing:
            logger.error(f"Missing columns for ETF {symbol}: {missing}")
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
            logger.warning(f"No valid price rows for ETF {symbol}")
            return None

        # yahooquery for fund info
        t = Ticker(symbol)
        fund_sector_weightings = {}
        if isinstance(t.fund_sector_weightings, pd.DataFrame):
            try:
                fund_sector_weightings = t.fund_sector_weightings.to_dict("index")
            except (KeyError, Exception):
                pass

        summary = t.summary_detail.get(symbol, {})
        if isinstance(summary, str):
            summary = {}
        fund_holding = t.fund_holding_info.get(symbol, {})
        if isinstance(fund_holding, str):
            fund_holding = {}

        tick = yf.Ticker(symbol)

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
            "symbol": symbol,
            "summary": summary,
            "fund_holding_info": fund_holding,
            "dividends": dividends,
            "splits": splits,
            "histories": rows,
        }
    except Exception as e:
        logger.error(f"Error crawling ETF {symbol}: {e}")
        return None


def crawl_etfs():
    """Crawl all ETF data. Downloads symbol list from S3, then crawls each."""
    logger.info("Starting ETF crawl")
    symbol_list_key = "crawl-result/v2/json/investment/etf/symbol_list.json"
    symbol_data = s3_util.download_json(symbol_list_key)
    symbols = ["SPY", "QQQ"]
    for item in symbol_data:
        s = item["symbol"]
        if s not in symbols:
            symbols.append(s)

    error_list = []
    for symbol in symbols:
        logger.info(f"Crawling ETF: {symbol}")
        result = _crawl_single_etf(symbol)
        if result:
            object_key = f"crawl-result/v2/json/investment/etf-detail/{symbol}.json"
            s3_util.upload_json(object_key, result)
        else:
            error_list.append(symbol)

    if error_list:
        s3_util.upload_json(
            "crawl-result/v2/json/investment/etf-detail-error_list.json", error_list
        )
        logger.warning(f"ETF errors ({len(error_list)}): {error_list[:10]}")
    return error_list
