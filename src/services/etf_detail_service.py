"""
ETF detail service: yfinance fetch -> calculate -> S3 upload -> DB save (one pass per ticker)
"""
import logging
from typing import List
from datetime import datetime
from dateutil.relativedelta import relativedelta

import yfinance as yf
import pandas as pd
from yahooquery import Ticker

from src.models.database import SessionLocal, Etf
from src.utils import s3_util
from src.utils.fin_calculator import calc_cagr, mdd_histories, year_increase_rate

logger = logging.getLogger(__name__)


def _deep_camel_keys(obj):
    def _to_camel(s):
        parts = s.split("_")
        return parts[0] + "".join(w.capitalize() for w in parts[1:])
    if isinstance(obj, dict):
        return {_to_camel(k): _deep_camel_keys(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_camel_keys(i) for i in obj]
    return obj


def _flatten_columns(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


# S3 심볼 리스트에 없더라도 항상 포함할 ETF 심볼
FIXED_SYMBOLS = [
    "SOXQ", "PSI", "FTXL", "CHPS",
]


def get_all_etf_symbols() -> List[str]:
    data = s3_util.download_json("crawl-result/v2/json/investment/etf/symbol_list.json")
    symbols = [item["symbol"] for item in data]
    seen = set(symbols)
    for sym in FIXED_SYMBOLS:
        if sym not in seen:
            symbols.append(sym)
            seen.add(sym)
    return symbols


def process_etf(symbol: str):
    """yfinance fetch -> calculate -> S3 upload -> DB save"""

    # --- 1) Fetch from yfinance ---
    logger.info(f"[ETF] {symbol} FETCHING from yfinance...")
    try:
        data = yf.download(symbol, start="1990-01-01", interval="1d", auto_adjust=False)
        if data.empty:
            logger.warning(f"[ETF] {symbol} FETCH FAILED: no data (possibly delisted)")
            return
        data = _flatten_columns(data)
    except Exception as e:
        logger.error(f"[ETF] {symbol} FETCH FAILED: {e}")
        return

    required = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    missing = [c for c in required if c not in data.columns]
    if missing:
        logger.error(f"[ETF] {symbol} FETCH FAILED: missing columns {missing}")
        return

    histories = []
    for index, row in data.iterrows():
        if pd.isna(row["Close"]):
            continue
        histories.append({
            "date": index.strftime("%Y-%m-%d"),
            "open": float(row["Open"]) if pd.notna(row["Open"]) else None,
            "high": float(row["High"]) if pd.notna(row["High"]) else None,
            "low": float(row["Low"]) if pd.notna(row["Low"]) else None,
            "close": float(row["Close"]),
            "adjClose": float(row["Adj Close"]) if pd.notna(row["Adj Close"]) else None,
            "volume": float(row["Volume"]) if pd.notna(row["Volume"]) else None,
        })

    if not histories:
        logger.warning(f"[ETF] {symbol} FETCH FAILED: no valid rows")
        return

    # yahooquery for fund info
    t = Ticker(symbol)
    summary = t.summary_detail.get(symbol, {})
    if isinstance(summary, str):
        summary = {}
    fund_holding = t.fund_holding_info.get(symbol, {})
    if isinstance(fund_holding, str):
        fund_holding = {}
    fund_profile = t.fund_profile.get(symbol, {})
    if isinstance(fund_profile, str):
        fund_profile = {}

    # top holdings
    holdings = []
    try:
        fth = t.fund_top_holdings
        if isinstance(fth, pd.DataFrame) and not fth.empty:
            for _, row in fth.iterrows():
                holdings.append({
                    "symbol": row.get("symbol", ""),
                    "name": row.get("holdingName", ""),
                    "holding_percent": float(row["holdingPercent"]) if pd.notna(row.get("holdingPercent")) else 0,
                })
    except Exception:
        pass

    # sector weightings
    sector_weightings = []
    try:
        fsw = t.fund_sector_weightings
        if isinstance(fsw, pd.DataFrame) and not fsw.empty:
            for idx, row in fsw.iterrows():
                name = idx if isinstance(idx, str) else str(idx)
                ratio = float(row.iloc[0]) if pd.notna(row.iloc[0]) else 0
                sector_weightings.append({"name": name, "ratio": ratio})
    except Exception:
        pass

    # fund profile fields
    crawled_issuer = fund_profile.get("family")
    crawled_category_name = fund_profile.get("categoryName")
    crawled_legal_type = fund_profile.get("legalType")
    fees_info = fund_profile.get("feesExpensesInvestment", {})
    crawled_expense_ratio = fees_info.get("annualReportExpenseRatio")

    crawled_currency = summary.get("currency")

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

    crawled_aum = summary.get("totalAssets")
    crawled_volume = summary.get("volume") or summary.get("regularMarketVolume")
    crawled_yield = summary.get("yield")
    crawled_price = histories[-1]["close"]

    logger.info(
        f"[ETF] {symbol} FETCHED: {len(histories)} rows, "
        f"range={histories[0]['date']}~{histories[-1]['date']}, "
        f"last_close={crawled_price}, aum={crawled_aum}, volume={crawled_volume}"
    )

    # --- 2) Get DB info + Calculate ---
    session = SessionLocal()
    try:
        etf = session.query(Etf).filter(Etf.symbol == symbol).first()
        result = {
            "symbol": symbol,
            "name": etf.name if etf else "",
            "aum": crawled_aum or (etf.aum if etf else None),
            "price": crawled_price,
            "volume": crawled_volume or (etf.volume if etf else None),
            "segment": etf.segment if etf else "",
            "category": etf.category if etf else "",
            "issuer": crawled_issuer,
            "brand": crawled_issuer,
            "index_tracked": crawled_category_name,
            "expense_ratio": f"{crawled_expense_ratio:.2%}" if crawled_expense_ratio else None,
            "currency": crawled_currency,
            "holdings": holdings or None,
            "sector_weightings": sector_weightings or None,
        }
    finally:
        session.close()

    end_value = float(histories[-1]["close"])
    end_date = datetime.strptime(histories[-1]["date"], "%Y-%m-%d")

    period_map = {6: "six_month", 12: "one_year", 36: "three_year", 60: "five_year", -1: "ytd"}
    compare = {}
    for months, key in period_map.items():
        if months <= 0:
            target = datetime(end_date.year - 1, 12, 31).strftime("%Y-%m-%d")
        else:
            target = (end_date - relativedelta(months=months)).strftime("%Y-%m-%d")
        starts = [h for h in histories if h["date"] < target]
        if starts:
            sv = float(starts[-1]["close"])
            if sv > 0:
                compare[key] = round((end_value - sv) / sv * 100, 2)

    increase_stat = []
    for period in [3, 5, 7, 10, 20]:
        target = (end_date - relativedelta(years=period)).strftime("%Y-%m-%d")
        starts = [h for h in histories if h["date"] < target]
        if starts:
            sv = float(starts[-1]["close"])
            if sv > 0:
                increase_stat.append({
                    "start_value": sv, "end_value": end_value,
                    "increase_rate": round((end_value - sv) / sv * 100, 2),
                    "cagr": calc_cagr(sv, end_value, period),
                    "period": period,
                })

    mdd_hist = mdd_histories(histories)
    mdd = min((h["mdd"] for h in mdd_hist), default=0)
    year_hist = year_increase_rate(histories)
    max_price = max((h["close"] for h in histories if h.get("close")), default=end_value)
    current_drawdown = -((max_price - end_value) / max_price) * 100

    def _get_cagr(p):
        item = next((s for s in increase_stat if s["period"] == p), None)
        return item["cagr"] if item else None

    result.update({
        "end_close": end_value,
        "yield": crawled_yield,
        "summary": {
            "fifty_two_week_high": summary.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": summary.get("fiftyTwoWeekLow"),
        },
        "compare_to_max_in_1_year": compare.get("one_year"),
        "compare_to_max_in_period": compare,
        "increase_stat": increase_stat,
        "current_drawdown": current_drawdown,
        "mdd": mdd,
        "best_year": max((h["intrease_rate"] for h in year_hist), default=None),
        "worst_year": min((h["intrease_rate"] for h in year_hist), default=None),
        "year_increase_histories": year_hist,
        "cagr_recent_3year": _get_cagr(3), "cagr_recent_5year": _get_cagr(5),
        "cagr_recent_7year": _get_cagr(7), "cagr_recent_10year": _get_cagr(10),
        "cagr_recent_20year": _get_cagr(20),
        "increase_rate_ytd": compare.get("ytd"),
        "increase_rate_6month": compare.get("six_month"),
        "increase_rate_1year": compare.get("one_year"),
        "increase_rate_3year": compare.get("three_year"),
        "increase_rate_5year": compare.get("five_year"),
        "fund_holding_info": fund_holding,
        "dividends": dividends,
        "splits": splits,
    })

    result["meta"] = {
        "title": f"{symbol}: {result.get('name', '')} ETF 수익률 및 정보",
        "description": f"{result.get('name', '')}({symbol}) ETF 수익률 및 상세 정보",
        "page_url": f"/investment/etf/{symbol}",
        "last_updated_at": datetime.now().strftime("%Y-%m-%d"),
    }

    logger.info(
        f"[ETF] {symbol} CALCULATED: aum={result.get('aum')} | price={crawled_price} | volume={result.get('volume')} "
        f"| cagr5y={_get_cagr(5)} | cagr10y={_get_cagr(10)} | mdd={round(mdd,2)} "
        f"| ytd={compare.get('ytd')} | drawdown={round(current_drawdown,2)}"
    )

    # --- 3) Upload to S3 ---
    result_camel = _deep_camel_keys(result)
    s3_util.upload_json(f"api-data/v1/json/investment/etf/{symbol}.json", result_camel)
    s3_util.upload_json(f"api-data/v2/json/investment/etf/{symbol}.json", result_camel)

    mdd_chart = [[h["timestamp"], h["mdd"]] for h in mdd_hist]
    s3_util.upload_json(f"api-data/v1/json/investment/etf/{symbol}/mdd-histories.json", mdd_chart)
    s3_util.upload_json(f"api-data/v2/json/investment/etf/{symbol}/mdd-histories.json", mdd_chart)

    chart_data = []
    for h in histories:
        ts = int(datetime.strptime(h["date"], "%Y-%m-%d").timestamp() * 1000)
        chart_data.append([ts, h.get("open"), h.get("high"), h.get("low"), h.get("close"), h.get("adjClose")])
    s3_util.upload_json(f"api-data/v1/json/investment/etf/{symbol}/chart-data.json", chart_data)
    s3_util.upload_json(f"api-data/v2/json/investment/etf/{symbol}/chart-data.json", chart_data)

    # Raw crawl data for backward compatibility
    raw = {"symbol": symbol, "summary": summary, "fund_holding_info": fund_holding,
           "dividends": dividends, "splits": splits, "histories": histories}
    s3_util.upload_json(f"crawl-result/v2/json/investment/etf-detail/{symbol}.json", raw)

    logger.info(f"[ETF] {symbol} S3 SAVED: detail + chart + mdd + raw")

    # --- 4) Save to DB ---
    session = SessionLocal()
    try:
        etf = session.query(Etf).filter(Etf.symbol == symbol).first()
        if not etf:
            logger.warning(f"[ETF] {symbol} DB SKIPPED: not found in etfs table")
            return

        if crawled_aum:
            etf.aum = crawled_aum
        if crawled_volume:
            etf.volume = crawled_volume
        if crawled_price:
            etf.price = crawled_price

        etf.cagr_recent_3year = _get_cagr(3)
        etf.cagr_recent_5year = _get_cagr(5)
        etf.cagr_recent_7year = _get_cagr(7)
        etf.cagr_recent_10year = _get_cagr(10)
        etf.cagr_recent_20year = _get_cagr(20)
        etf.increase_rate_ytd = compare.get("ytd")
        etf.increase_rate_6month = compare.get("six_month")
        etf.increase_rate_1year = compare.get("one_year")
        etf.increase_rate_3year = compare.get("three_year")
        etf.increase_rate_5year = compare.get("five_year")
        etf.current_drawdown = current_drawdown
        etf.mdd = mdd
        etf.best_year = result.get("best_year")
        etf.worst_year = result.get("worst_year")
        etf.last_updated_at = datetime.now()
        session.commit()
        logger.info(f"[ETF] {symbol} DB SAVED")
    except Exception as e:
        session.rollback()
        logger.error(f"[ETF] {symbol} DB FAILED: {e}")
    finally:
        session.close()
