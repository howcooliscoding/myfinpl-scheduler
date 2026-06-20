"""
Stock detail service: yfinance fetch -> calculate -> S3 upload -> DB save (one pass per ticker)
"""
import logging
from typing import Optional
from datetime import datetime
from dateutil.relativedelta import relativedelta

import yfinance as yf
import pandas as pd

from src.models.database import SessionLocal, Stock, StockName
from src.utils import s3_util
from src.utils.fin_calculator import calc_cagr, mdd_histories, year_increase_rate

logger = logging.getLogger(__name__)


def _to_camel_case(s):
    parts = s.split("_")
    return parts[0] + "".join(w.capitalize() for w in parts[1:])


def _deep_camel_keys(obj):
    if isinstance(obj, dict):
        return {_to_camel_case(k): _deep_camel_keys(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_camel_keys(i) for i in obj]
    return obj


def _flatten_columns(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def domain_from_website(website):
    """Extract a bare domain (e.g. 'apple.com') from a website URL for use with
    favicon services. Returns None if not parseable."""
    if not website:
        return None
    d = str(website).strip().lower()
    d = d.split("://", 1)[-1]      # strip scheme
    d = d.split("/", 1)[0]          # strip path
    d = d.split("?", 1)[0]
    if d.startswith("www."):
        d = d[4:]
    return d or None


class StockDetailService:
    def __init__(self, country_code: str):
        self.country_code = country_code
        self.market_type = "kr-stock-detail" if country_code == "kr" else "us-stock-detail"

    def process(self, symbol: str):
        """yfinance fetch -> calculate -> S3 upload -> DB save"""

        # --- 1) Fetch from yfinance ---
        logger.info(f"[Stock] {symbol} FETCHING from yfinance...")
        try:
            data = yf.download(symbol, start="1990-01-01", interval="1d", auto_adjust=False)
            if data.empty:
                logger.warning(f"[Stock] {symbol} FETCH FAILED: no data (possibly delisted)")
                return
            data = _flatten_columns(data)
        except Exception as e:
            logger.error(f"[Stock] {symbol} FETCH FAILED: {e}")
            return

        required = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
        missing = [c for c in required if c not in data.columns]
        if missing:
            logger.error(f"[Stock] {symbol} FETCH FAILED: missing columns {missing}")
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
            logger.warning(f"[Stock] {symbol} FETCH FAILED: no valid rows")
            return

        # Ticker info
        tick = yf.Ticker(symbol)
        try:
            tick_info = tick.info or {}
        except Exception:
            tick_info = {}

        try:
            fast = tick.fast_info
            market_cap = fast.market_cap
            info = {
                "shortName": tick_info.get("shortName", ""),
                "longName": tick_info.get("longName", ""),
                "dividendYield": tick_info.get("dividendYield") or None,
                "dividendRate": tick_info.get("dividendRate") or None,
                "forwardPE": tick_info.get("forwardPE", ""),
                "currency": fast.currency,
                "exchange": fast.exchange,
                "market_cap": fast.market_cap,
                "last_price": fast.last_price,
                "previous_close": fast.previous_close,
            }
        except Exception:
            info = {
                "shortName": tick_info.get("shortName", ""),
                "longName": tick_info.get("longName", ""),
                "dividendYield": tick_info.get("dividendYield") or None,
                "dividendRate": tick_info.get("dividendRate") or None,
            }
            market_cap = tick_info.get("marketCap")

        # Descriptive metadata used to fully populate the DB row. This matters
        # for manually-added tickers (e.g. SPCX/SpaceX) that are created here for
        # the first time and would otherwise have no name/exchange/sector and
        # thus be excluded from ranking queries.
        stock_meta = {
            "name": tick_info.get("longName") or tick_info.get("shortName") or info.get("longName") or info.get("shortName") or "",
            "exchange": info.get("exchange") or tick_info.get("exchange"),
            "currency": info.get("currency") or tick_info.get("currency"),
            "country": tick_info.get("country"),
            "sector": tick_info.get("sector"),
            "industry": tick_info.get("industry"),
            "website": tick_info.get("website") or tick_info.get("irWebsite"),
        }

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

        logger.info(
            f"[Stock] {symbol} FETCHED: {len(histories)} rows, "
            f"range={histories[0]['date']}~{histories[-1]['date']}, "
            f"last_close={histories[-1]['close']}, market_cap={market_cap}"
        )

        # --- 2) Calculate metrics ---
        end_element = histories[-1]
        end_value = float(end_element["close"])
        end_date = datetime.strptime(end_element["date"], "%Y-%m-%d")

        if not market_cap:
            logger.error(f"[Stock] {symbol} market_cap is blank, skipping")
            return

        result = {
            "symbol": symbol,
            "yield": info.get("dividendYield") or None,
            "dividend": info.get("dividendRate") or None,
            "end_close": end_value,
            "market_cap": market_cap,
        }

        # Increase rates
        period_key_map = {6: "six_month", 12: "one_year", 36: "three_year", 60: "five_year", -1: "ytd"}
        compare = {}
        for months, key in period_key_map.items():
            if months <= 0:
                target = datetime(end_date.year - 1, 12, 31).strftime("%Y-%m-%d")
            else:
                target = (end_date - relativedelta(months=months)).strftime("%Y-%m-%d")
            starts = [h for h in histories if h["date"] < target]
            if starts:
                sv = float(starts[-1]["close"])
                if sv > 0:
                    compare[key] = round((end_value - sv) / sv * 100, 2)

        # CAGR
        increase_stat = []
        for period in [3, 5, 7, 10, 20, 30]:
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
            "increase_stat": increase_stat,
            "compare_to_max_in_1_year": compare.get("one_year"),
            "compare_to_max_in_period": compare,
            "current_drawdown": current_drawdown,
            "mdd": mdd,
            "best_year": max((h["intrease_rate"] for h in year_hist), default=None),
            "worst_year": min((h["intrease_rate"] for h in year_hist), default=None),
            "year_increase_histories": year_hist,
            "cagr_3_year": _get_cagr(3), "cagr_5_year": _get_cagr(5),
            "cagr_7_year": _get_cagr(7), "cagr_10_year": _get_cagr(10),
            "cagr_20_year": _get_cagr(20), "cagr_30_year": _get_cagr(30),
            "increase_rate_ytd": compare.get("ytd"),
            "increase_rate_month": compare.get("six_month"),
            "increase_rate_year": compare.get("one_year"),
            "increase_rate_year3": compare.get("three_year"),
        })

        # Name/sector lookup
        session = SessionLocal()
        try:
            sn = session.query(StockName).filter(StockName.symbol == symbol, StockName.locale == "ko").first()
            stock_db = session.query(Stock).filter(Stock.symbol == symbol).first()
            # 영문 이름: 데이터소스(longName/shortName) > DB name > 심볼
            english_name = stock_meta.get("name") or (stock_db.name if stock_db else None) or symbol
            result["name"] = english_name
            # 한글 이름: stock_names 우선, 없으면 영문 이름으로 폴백 (절대 빈값/None 아님)
            result["name_ko"] = (sn.name if sn and sn.name else None) or english_name
            # 기업 로고(favicon)용 도메인. 신규 수집값 우선, 없으면 기존 DB 값 유지.
            website = stock_meta.get("website") or (stock_db.website if stock_db else None)
            result["website"] = website
            result["domain"] = domain_from_website(website)
            if stock_db:
                result["sector_ko"] = stock_db.sector_ko or stock_db.sector
                result["industry_ko"] = stock_db.industry_ko or stock_db.industry
        finally:
            session.close()

        result["meta"] = {
            "title": f"{symbol}: {result.get('name_ko', '')} 주가 현황 및 주식 정보",
            "description": f"{result.get('name_ko', '')}({symbol}) 주가 현황 및 주식 정보",
            "page_url": f"/investment/stock/{symbol}",
            "keywords": f"{symbol}, {result.get('name_ko', '')}",
            "last_updated_at": datetime.now().strftime("%Y-%m-%d"),
        }

        logger.info(
            f"[Stock] {symbol} CALCULATED: market_cap={market_cap} | price={end_value} "
            f"| cagr5y={_get_cagr(5)} | cagr10y={_get_cagr(10)} | mdd={round(mdd,2)} "
            f"| ytd={compare.get('ytd')} | drawdown={round(current_drawdown,2)}"
        )

        # --- 3) Upload to S3 ---
        result_camel = _deep_camel_keys(result)
        s3_util.upload_json(f"api-data/v1/json/investment/stock/{symbol}.json", result_camel)
        s3_util.upload_json(f"api-data/v2/json/investment/stock/{symbol}.json", result_camel)

        mdd_chart = [[h["timestamp"], h["mdd"]] for h in mdd_hist]
        s3_util.upload_json(f"api-data/v1/json/investment/stock/{symbol}/mdd-histories.json", mdd_chart)
        s3_util.upload_json(f"api-data/v2/json/investment/stock/{symbol}/mdd-histories.json", mdd_chart)

        chart_data = []
        for h in histories:
            ts = int(datetime.strptime(h["date"], "%Y-%m-%d").timestamp() * 1000)
            chart_data.append([ts, h.get("open"), h.get("high"), h.get("low"), h.get("close"), h.get("adjClose")])
        s3_util.upload_json(f"api-data/v1/json/investment/stock/{symbol}/chart-data.json", chart_data)
        s3_util.upload_json(f"api-data/v2/json/investment/stock/{symbol}/chart-data.json", chart_data)

        # Also save raw crawl data for backward compatibility
        raw = {"info": info, "market_cap": market_cap, "symbol": symbol,
               "dividends": dividends, "splits": splits, "histories": histories}
        s3_util.upload_json(f"crawl-result/v3/json/investment/{self.market_type}/{symbol}.json", raw)

        logger.info(f"[Stock] {symbol} S3 SAVED: detail + chart + mdd + raw")

        # --- 4) Save to DB ---
        session = SessionLocal()
        try:
            stock = session.query(Stock).filter(Stock.symbol == symbol).first()
            if not stock:
                stock = Stock(symbol=symbol)
                session.add(stock)

            stock.country_code = self.country_code

            # Populate descriptive metadata. Refresh exchange/currency from the
            # data source every run (so newly-added tickers become eligible for
            # ranking queries), but preserve any curated name/sector values by
            # only filling them when currently empty.
            if stock_meta.get("exchange"):
                stock.exchange = stock_meta["exchange"]
            if stock_meta.get("currency"):
                stock.currency = stock_meta["currency"]
            if not stock.name and stock_meta.get("name"):
                stock.name = stock_meta["name"]
            if not stock.country and stock_meta.get("country"):
                stock.country = stock_meta["country"]
            if not stock.sector and stock_meta.get("sector"):
                stock.sector = stock_meta["sector"]
            if not stock.industry and stock_meta.get("industry"):
                stock.industry = stock_meta["industry"]
            if stock_meta.get("website"):
                stock.website = stock_meta["website"]

            stock.dividend_yield = result.get("yield")
            stock.dividend = result.get("dividend")
            stock.market_cap = market_cap
            stock.current_drawdown = current_drawdown
            stock.mdd = mdd
            stock.best_year = result.get("best_year")
            stock.worst_year = result.get("worst_year")
            stock.increase_rate_ytd = result.get("increase_rate_ytd")
            stock.increase_rate_month = result.get("increase_rate_month")
            stock.increase_rate_year = result.get("increase_rate_year")
            stock.increase_rate_year3 = result.get("increase_rate_year3")
            stock.cagr_3year = _get_cagr(3)
            stock.cagr_5year = _get_cagr(5)
            stock.cagr_7year = _get_cagr(7)
            stock.cagr_10year = _get_cagr(10)
            stock.cagr_20year = _get_cagr(20)
            stock.cagr_30year = _get_cagr(30)
            stock.name_ko = result.get("name_ko")
            stock.sector_ko = result.get("sector_ko")
            stock.industry_ko = result.get("industry_ko")
            stock.enabled = 1
            stock.last_updated_at = datetime.now()

            session.commit()
            logger.info(f"[Stock] {symbol} DB SAVED")
        except Exception as e:
            session.rollback()
            logger.error(f"[Stock] {symbol} DB FAILED: {e}")
        finally:
            session.close()
