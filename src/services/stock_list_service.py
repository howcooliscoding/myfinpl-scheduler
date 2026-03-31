"""
Stock list preparation service.
Replaces: lib/tasks/my_fin_pl/investment/stock_list_service.rb
"""
import logging
from typing import List
from datetime import datetime
from sqlalchemy import desc

from src.models.database import SessionLocal, Stock, StockTag
from src.utils import s3_util
from src.utils.exchange_rate import get_exchange_rate

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


def prepare_api_all_symbol_list():
    """Build and upload US/KR stock symbol lists to S3."""
    session = SessionLocal()
    try:
        nasdaq = (
            session.query(Stock)
            .filter(Stock.stock_class.is_(None), Stock.exchange == "NMS")
            .order_by(desc(Stock.market_cap))
            .limit(200)
            .all()
        )
        nyse = (
            session.query(Stock)
            .filter(Stock.stock_class.is_(None), Stock.exchange == "NYQ")
            .order_by(desc(Stock.market_cap))
            .limit(200)
            .all()
        )

        # Tagged stocks
        tag_symbols = [t.symbol for t in session.query(StockTag.symbol).distinct().all()]
        other_stocks = session.query(Stock).filter(Stock.symbol.in_(tag_symbols)).all() if tag_symbols else []

        symbols_set = set()
        symbols = [{"symbol": "META", "name": "Meta Platforms Inc"}]
        symbols_set.add("META")
        for stock_list in [nasdaq, nyse, other_stocks]:
            for s in stock_list:
                if s.symbol not in symbols_set:
                    symbols.append({"symbol": s.symbol, "name": s.name})
                    symbols_set.add(s.symbol)

        s3_util.upload_json("api-data/v1/json/investment/stock/us-stock/symbol-list.json", symbols)
        logger.info(f"Uploaded US symbol list: {len(symbols)} symbols")

        # Korean stocks
        kr_stocks = session.query(Stock).filter(Stock.country_code == "kr").all()
        kr_symbols = [
            {"symbol": s.symbol, "name": s.name, "name_ko": s.name_ko, "slug": s.slug}
            for s in kr_stocks
        ]
        s3_util.upload_json("api-data/v1/json/investment/stock/ko-stock/symbol-list.json", kr_symbols)
        logger.info(f"Uploaded KR symbol list: {len(kr_symbols)} symbols")
    finally:
        session.close()


def get_api_data_symbol_list() -> List[str]:
    """Download US stock symbol list from S3 and return list of symbols."""
    data = s3_util.download_json("api-data/v1/json/investment/stock/us-stock/symbol-list.json")
    return [item["symbol"] for item in data]


def prepare_api_for_us_stock():
    """Generate ranked US stock lists (all, NASDAQ, NYSE) and upload to S3."""
    exchange_rate = get_exchange_rate()
    session = SessionLocal()
    try:
        us_all = (
            session.query(Stock)
            .filter(Stock.stock_class.is_(None), Stock.exchange.in_(["NMS", "NYQ"]))
            .order_by(desc(Stock.market_cap))
            .limit(200)
            .all()
        )
        nasdaq = (
            session.query(Stock)
            .filter(Stock.stock_class.is_(None), Stock.exchange == "NMS")
            .order_by(desc(Stock.market_cap))
            .limit(200)
            .all()
        )
        nyse = (
            session.query(Stock)
            .filter(Stock.stock_class.is_(None), Stock.exchange == "NYQ")
            .order_by(desc(Stock.market_cap))
            .limit(200)
            .all()
        )

        def _names(stocks):
            return ", ".join(
                f"{s.name_ko or s.name}({s.symbol})" for s in stocks[:10]
            )

        exchange_types = {
            "all": {
                "title": "미국주식 전체 시가총액 기업 순위 TOP100",
                "description": f"미국주식 전체 시가총액 (Market Cap) 기업 순위 TOP100 입니다. {_names(us_all)} 등 미국 상장 기업들의 시가총액 순위를 확인 할수 있습니다.",
                "stocks": us_all,
            },
            "nasdaq": {
                "title": "미국주식 - 나스닥(Nasdaq) 시가총액 기업 순위 TOP100",
                "description": f"미국주식 나스닥(Nasdaq) 시가총액 (Market Cap) 기업 순위 TOP100 입니다. {_names(nasdaq)} 등 나스닥 기업들의 시가총액 순위 입니다.",
                "stocks": nasdaq,
            },
            "nyse": {
                "title": "미국주식 - 뉴욕증권거래소(NYSE) 시가총액 기업 순위 TOP100",
                "description": f"미국주식 뉴욕증권거래소(NYSE) 시가총액 (Market Cap) 기업 순위 TOP100 입니다. {_names(nyse)} 등 뉴욕증권거래소(NYSE) 기업들의 시가총액 순위 입니다.",
                "stocks": nyse,
            },
        }

        for exchange_type, value in exchange_types.items():
            stock_list = []
            for idx, stock in enumerate(value["stocks"][:100]):
                exchange_name = {"NMS": "NASDAQ", "NYQ": "NYSE"}.get(stock.exchange, stock.exchange)
                item = {
                    "rank": idx + 1,
                    "name": stock.name,
                    "name_ko": stock.name_ko,
                    "sector": stock.sector,
                    "sector_ko": stock.sector_ko,
                    "industry": stock.industry,
                    "industry_ko": stock.industry_ko,
                    "symbol": stock.symbol,
                    "market_cap_dollor": stock.market_cap,
                    "market_cap_bi_dollor": int((stock.market_cap or 0) / 1_000_000_000),
                    "market_cap_bi_won": int(((stock.market_cap or 0) * exchange_rate) / 1_000_000_000_000),
                    "country": stock.country,
                    "exchange": exchange_name,
                    "dividend": stock.dividend,
                    "yield": stock.dividend_yield,
                    "increase_rate": {
                        "ytd": stock.increase_rate_ytd,
                        "month": stock.increase_rate_month,
                        "year": stock.increase_rate_year,
                        "3year": stock.increase_rate_year3,
                    },
                }
                stock_list.append(item)

            result = _deep_camel_keys({
                "title": value["title"],
                "description": value["description"],
                "list": stock_list,
                "exchange_rate": exchange_rate,
                "last_updated_at": datetime.now().isoformat(),
            })

            key = f"api-data/v3/json/investment/stock/us/{exchange_type}/recent/ranking/list.json"
            s3_util.upload_json(key, result)
            logger.info(f"Uploaded US stock ranking: {exchange_type}")
    finally:
        session.close()


def prepare_api_for_korean_stock():
    """Generate ranked Korean stock list and upload to S3."""
    exchange_rate = get_exchange_rate()
    session = SessionLocal()
    try:
        kr_all = (
            session.query(Stock)
            .filter(Stock.stock_class.is_(None), Stock.country_code == "kr")
            .order_by(desc(Stock.market_cap))
            .all()
        )

        names = ", ".join(f"{s.name_ko or s.name}({s.symbol})" for s in kr_all[:10])

        # Slug-symbol map
        slug_symbol_map = {s.slug: s.symbol for s in kr_all if s.slug}
        s3_util.upload_json(
            "api-data/v3/json/investment/stock/kr/all/slug_and_symbol_map.json",
            slug_symbol_map,
        )

        stock_list = []
        for idx, stock in enumerate(kr_all[:200]):
            exchange_name = {"NMS": "NASDAQ", "NYQ": "NYSE"}.get(stock.exchange, stock.exchange)
            item = {
                "rank": idx + 1,
                "name": stock.name,
                "name_ko": stock.name_ko,
                "sector": stock.sector,
                "sector_ko": stock.sector_ko,
                "industry": stock.industry,
                "industry_ko": stock.industry_ko,
                "symbol": stock.symbol,
                "slug": stock.slug,
                "market_cap_won": stock.market_cap,
                "market_cap_100mi_won": int((stock.market_cap or 0) / 100_000_000),
                "market_cap_bi_won": int((stock.market_cap or 0) / 1_000_000_000_000),
                "cagr_3year": stock.cagr_3year,
                "cagr_5year": stock.cagr_5year,
                "cagr_7year": stock.cagr_7year,
                "cagr_10year": stock.cagr_10year,
                "cagr_20year": stock.cagr_20year,
                "cagr_30year": stock.cagr_30year,
                "country": stock.country,
                "exchange": exchange_name,
                "dividend": stock.dividend,
                "yield": stock.dividend_yield,
                "increase_rate": {
                    "ytd": stock.increase_rate_ytd,
                    "month": stock.increase_rate_month,
                    "year": stock.increase_rate_year,
                    "3year": stock.increase_rate_year3,
                },
            }
            stock_list.append(item)

        result = _deep_camel_keys({
            "title": "국내 기업 시가 총액 기업 순위 TOP200",
            "description": f"국내 기업 전체 시가 총액 기준 기업 순위 TOP200 입니다. {names} 등 국내 상장 기업들의 시가 총액 순위를 확인 할수 있습니다.",
            "list": stock_list,
            "exchange_rate": exchange_rate,
            "last_updated_at": datetime.now().isoformat(),
        })

        s3_util.upload_json("api-data/v3/json/investment/stock/kr/all/recent/ranking/list.json", result)
        logger.info("Uploaded KR stock ranking")
    finally:
        session.close()
