"""
Stock home contents + sector ranking + CAGR ranking.
Replaces:
  - lib/tasks/my_fin_pl/investment/stock/prepare_home_contents.rb
  - PrepareStockData#prepare_list_by_cagr
  - StockTag.prepare_sector_api_list
"""
import logging
from datetime import datetime
from sqlalchemy import desc

from src.models.database import SessionLocal, Stock, StockTag, StockSector
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


def prepare_home_contents():
    """Prepare home page stock collections (top 100 by various criteria)."""
    exchange_rate = get_exchange_rate()
    session = SessionLocal()
    try:
        collections = [
            {
                "slug": "us_top_100_current_drawdown",
                "title": "미국 주식 시총 100위 기업 고점대비 하락율",
                "description": "미국 주식 시총 100위 기업들의 고점대비 하락율 입니다.",
                "stocks": (
                    session.query(Stock)
                    .filter(Stock.stock_class.is_(None), Stock.exchange.in_(["NMS", "NYQ"]))
                    .order_by(desc(Stock.market_cap))
                    .limit(100)
                    .all()
                ),
            },
            {
                "slug": "top_100_tech_current_drawdown",
                "title": "미국 Tech 기업 시총 100위 기업 고점대비 하락율",
                "description": "미국 Tech 기업 시총 100위 기업들의 고점대비 하락율 입니다.",
                "stocks": (
                    session.query(Stock)
                    .filter(Stock.stock_class.is_(None), Stock.sector == "Technology")
                    .order_by(desc(Stock.market_cap))
                    .limit(100)
                    .all()
                ),
            },
            {
                "slug": "nasdaq_top_100_current_drawdown",
                "title": "미국 NASDAQ 시총 100위 기업 고점대비 하락율",
                "description": "미국 NASDAQ 시총 100위 기업들의 고점대비 하락율 입니다.",
                "stocks": (
                    session.query(Stock)
                    .filter(Stock.stock_class.is_(None), Stock.exchange == "NMS")
                    .order_by(desc(Stock.market_cap))
                    .limit(100)
                    .all()
                ),
            },
        ]

        for col in collections:
            stock_list = [s.to_list_item(exchange_rate) for s in col["stocks"]]
            result = _deep_camel_keys({
                "slug": col["slug"],
                "title": col["title"],
                "description": col["description"],
                "list": stock_list,
                "exchange_rate": exchange_rate,
                "last_updated_at": datetime.now().strftime("%Y-%m-%d"),
            })
            key = f"api-data/v2/json/investment/stock/us-stock/collections/{col['slug']}.json"
            s3_util.upload_json(key, result)
            logger.info(f"Uploaded collection: {col['slug']}")
    finally:
        session.close()


def prepare_list_by_cagr():
    """Prepare CAGR ranking for US stocks (5yr, 10yr, 20yr)."""
    exchange_rate = get_exchange_rate()
    session = SessionLocal()
    try:
        nasdaq_symbols = [
            s.symbol for s in
            session.query(Stock.symbol)
            .filter(Stock.stock_class.is_(None), Stock.exchange == "NMS")
            .order_by(desc(Stock.market_cap))
            .limit(100)
            .all()
        ]
        nyse_symbols = [
            s.symbol for s in
            session.query(Stock.symbol)
            .filter(Stock.stock_class.is_(None), Stock.exchange == "NYQ")
            .order_by(desc(Stock.market_cap))
            .limit(100)
            .all()
        ]
        target_symbols = set(nasdaq_symbols + nyse_symbols)

        def _build_ranking(field, period_years, top_limit=100):
            stocks = (
                session.query(Stock)
                .filter(field.isnot(None))
                .order_by(desc(field))
                .limit(top_limit)
                .all()
            )
            items = []
            for s in stocks:
                if s.symbol in target_symbols:
                    items.append(s.to_list_item(exchange_rate))
            return items

        five_year = _build_ranking(Stock.cagr_5year, 5)
        ten_year = _build_ranking(Stock.cagr_10year, 10)
        twenty_year = _build_ranking(Stock.cagr_20year, 20)

        def _make_group(highlight_year, menu_name, title, desc_text, link_url, items):
            names = ", ".join(i.get("nameKo", i.get("name", "")) for i in items[:10])
            return {
                "highlightYear": highlight_year,
                "menuName": menu_name,
                "title": title,
                "description": f"{desc_text} {names} 등 각 주식별 연평균 수익률, 년도별 수익률 변화, 최대낙폭 등도 확인 할수 있습니다.",
                "linkUrl": link_url,
                "list": items,
                "exchangeRate": exchange_rate,
                "lastUpdatedAt": datetime.now().strftime("%Y-%m-%d"),
            }

        five_yr_group = _make_group(
            5, "5년 CAGR", "미국 주식 최근 5년 연평균 수익률 순위",
            "NYSE와 나스닥 순위 100위 기업들의 최근 5년 연평균 수익률 순위 입니다.",
            "/investment/stock/ranking/cagr/five-year", five_year,
        )
        ten_yr_group = _make_group(
            10, "10년 CAGR", "미국 주식 최근 10년 연평균 수익률 순위",
            "NYSE와 나스닥 순위 100위 기업들의 최근 10년 연평균 수익률 순위 입니다.",
            "/investment/stock/ranking/cagr/ten-year", ten_year,
        )
        twenty_yr_group = _make_group(
            20, "20년 CAGR", "미국 주식 최근 20년 연평균 수익률 순위",
            "NYSE와 나스닥 순위 100위 기업들의 20년 연평균 수익률 순위 입니다.",
            "/investment/stock/ranking/cagr/twenty-year", twenty_year,
        )

        menu_tags = [
            {"highlightYear": g["highlightYear"], "name": g["menuName"], "title": g["title"], "link": g["linkUrl"]}
            for g in [five_yr_group, ten_yr_group, twenty_yr_group]
        ]

        result = _deep_camel_keys({
            "title": "미국 주식 연평균 수익률 순위 (최근 5년, 10년, 20년 기준)",
            "description": "NYSE와 나스닥 순위 100위 기업중 최근 5년, 10년, 20년 간 연평균 수익률 순위 입니다.",
            "exchange_rate": exchange_rate,
            "last_updated_at": datetime.now().strftime("%Y-%m-%d"),
            "twenty_year_cagr_stock_ranking": twenty_yr_group,
            "ten_year_cagr_stock_ranking": ten_yr_group,
            "five_year_cagr_stock_ranking": five_yr_group,
            "menu_tags": menu_tags,
            "groups": [five_yr_group, ten_yr_group, twenty_yr_group],
        })

        s3_util.upload_json("api-data/v2/json/investment/stock/us-stock/cagr-ranking-home.json", result)
        logger.info("Uploaded stock CAGR ranking")
    finally:
        session.close()


def prepare_sector_api_list():
    """Prepare sector-based stock ranking and upload to S3."""
    exchange_rate = get_exchange_rate()
    session = SessionLocal()
    try:
        sectors = session.query(StockSector).all()
        sector_groups = []
        for sector in sectors:
            stocks = (
                session.query(Stock)
                .filter(Stock.sector == sector.name, Stock.stock_class.is_(None))
                .order_by(desc(Stock.market_cap))
                .limit(50)
                .all()
            )
            items = [s.to_list_item(exchange_rate) for s in stocks]
            group = {
                "slug": sector.slug,
                "nameOriginal": sector.name,
                "name": sector.name_ko or sector.name,
                "title": f"{sector.name_ko or sector.name} 섹터 주식 시가총액 순위",
                "description": sector.description or "",
                "list": items,
            }
            sector_groups.append(group)

        result = _deep_camel_keys({
            "title": "미국 주식 섹터별 시가총액 순위",
            "description": "미국 주식 섹터별 시가총액 순위 입니다.",
            "exchange_rate": exchange_rate,
            "last_updated_at": datetime.now().strftime("%Y-%m-%d"),
            "groups": sector_groups,
        })

        s3_util.upload_json("api-data/v2/json/investment/stock/us-stock/ranking/by_sector/home.json", result)
        logger.info("Uploaded stock sector ranking")
    finally:
        session.close()
