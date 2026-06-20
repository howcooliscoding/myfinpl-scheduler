"""
Stock list preparation service.
Replaces: lib/tasks/my_fin_pl/investment/stock_list_service.rb
"""
import logging
from typing import List
from datetime import datetime
from sqlalchemy import desc

from src.models.database import SessionLocal, Stock, StockTag, ManualSymbol
from src.utils import s3_util
from src.utils.exchange_rate import get_exchange_rate, get_usd_conversion_rates

logger = logging.getLogger(__name__)


def _get_manual_symbols(session, country_code: str):
    """Return enabled manual symbols for a country, ordered by sort_order.

    These are curated tickers (e.g. SPCX/SpaceX) that must always be included
    regardless of market-cap ranking or exchange. Falls back gracefully if the
    manual_symbols table does not exist yet.
    """
    try:
        rows = (
            session.query(ManualSymbol)
            .filter(ManualSymbol.country_code == country_code, ManualSymbol.enabled == 1)
            .order_by(ManualSymbol.sort_order)
            .all()
        )
        return [{"symbol": r.symbol, "name": r.name} for r in rows]
    except Exception as e:
        logger.warning(f"manual_symbols unavailable ({country_code}): {e}")
        return []


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
        symbols = []

        # Manual / curated symbols always come first (e.g. SPCX/SpaceX, META).
        # These are included regardless of market-cap ranking or exchange.
        manual_us = _get_manual_symbols(session, "us")
        for m in manual_us:
            if m["symbol"] not in symbols_set:
                symbols.append({"symbol": m["symbol"], "name": m["name"]})
                symbols_set.add(m["symbol"])

        for stock_list in [nasdaq, nyse, other_stocks]:
            for s in stock_list:
                if s.symbol not in symbols_set:
                    symbols.append({"symbol": s.symbol, "name": s.name})
                    symbols_set.add(s.symbol)

        s3_util.upload_json("api-data/v1/json/investment/stock/us-stock/symbol-list.json", symbols)
        logger.info(f"Uploaded US symbol list: {len(symbols)} symbols ({len(manual_us)} manual)")

        # Korean stocks (DB + manual)
        kr_symbols = []
        kr_set = set()

        manual_kr = _get_manual_symbols(session, "kr")
        for m in manual_kr:
            if m["symbol"] not in kr_set:
                kr_symbols.append({"symbol": m["symbol"], "name": m["name"], "name_ko": None, "slug": None})
                kr_set.add(m["symbol"])

        kr_stocks = session.query(Stock).filter(Stock.country_code == "kr").all()
        for s in kr_stocks:
            if s.symbol not in kr_set:
                kr_symbols.append({"symbol": s.symbol, "name": s.name, "name_ko": s.name_ko, "slug": s.slug})
                kr_set.add(s.symbol)

        s3_util.upload_json("api-data/v1/json/investment/stock/ko-stock/symbol-list.json", kr_symbols)
        logger.info(f"Uploaded KR symbol list: {len(kr_symbols)} symbols ({len(manual_kr)} manual)")
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
                "title": "미국 주식 시가총액 순위 TOP 100",
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


# 영문 국가명 -> 한글 국가명 (전세계 랭킹 표시용). 미매핑 국가는 영문 그대로 노출.
COUNTRY_KO_MAP = {
    "United States": "미국", "South Korea": "한국", "China": "중국",
    "Hong Kong": "홍콩", "Taiwan": "대만", "Japan": "일본", "India": "인도",
    "United Kingdom": "영국", "Canada": "캐나다", "Germany": "독일",
    "France": "프랑스", "Switzerland": "스위스", "Netherlands": "네덜란드",
    "Ireland": "아일랜드", "Israel": "이스라엘", "Bermuda": "버뮤다",
    "Brazil": "브라질", "Mexico": "멕시코", "Luxembourg": "룩셈부르크",
    "Saudi Arabia": "사우디아라비아", "Denmark": "덴마크", "Australia": "호주",
    "Spain": "스페인", "Italy": "이탈리아", "Sweden": "스웨덴",
    "Singapore": "싱가포르", "Argentina": "아르헨티나", "Norway": "노르웨이",
    "Finland": "핀란드", "Belgium": "벨기에", "South Africa": "남아프리카공화국",
    "Cayman Islands": "케이맨제도", "Indonesia": "인도네시아", "Thailand": "태국",
    "United Arab Emirates": "아랍에미리트", "Russia": "러시아", "Turkey": "튀르키예",
    "Chile": "칠레", "Austria": "오스트리아", "Portugal": "포르투갈",
    "Uruguay": "우루과이", "Belgium": "벨기에", "Norway": "노르웨이",
}


def prepare_api_for_world_stock():
    """Generate a worldwide market-cap ranking across ALL exchanges/countries.

    Market caps are stored in each stock's local trading currency (USD, KRW,
    CNY, JPY, EUR, ...), so they must be normalized to USD before they can be
    ranked against each other - otherwise high-denomination currencies (e.g.
    KRW) dominate the top of the list purely due to their larger raw numbers.

    Each result carries both USD and KRW market caps plus currency/country
    metadata so the front-end can present a true global ranking.
    """
    exchange_rate = get_exchange_rate()  # 1 USD = N KRW
    session = SessionLocal()
    try:
        candidates = (
            session.query(Stock)
            .filter(
                Stock.stock_class.is_(None),
                Stock.market_cap.isnot(None),
                Stock.market_cap > 0,
            )
            .all()
        )

        def _currency_of(st):
            if st.currency:
                return st.currency.upper()
            return "KRW" if st.country_code == "kr" else "USD"

        currencies = {_currency_of(st) for st in candidates}
        # 1 USD = N CUR. Keep KRW consistent with the displayed KRW exchange rate.
        usd_rates = get_usd_conversion_rates(currencies)
        usd_rates["KRW"] = exchange_rate

        # Convert every market cap to USD, then rank globally.
        ranked = []
        skipped = set()
        for st in candidates:
            cur = _currency_of(st)
            rate = usd_rates.get(cur)
            if not rate or rate <= 0:
                skipped.add(cur)
                continue
            cap_usd = st.market_cap / rate
            ranked.append((cap_usd, cur, st))
        if skipped:
            logger.warning(f"[World] skipped stocks with no FX rate: {sorted(skipped)}")

        ranked.sort(key=lambda x: x[0], reverse=True)
        ranked = ranked[:100]

        names = ", ".join(f"{st.name_ko or st.name}({st.symbol})" for _, _, st in ranked[:10])

        exchange_name_map = {"NMS": "NASDAQ", "NYQ": "NYSE"}
        stock_list = []
        for idx, (cap_usd, cur, stock) in enumerate(ranked):
            cap_won = cap_usd * exchange_rate
            country_ko = COUNTRY_KO_MAP.get(stock.country, stock.country)
            item = {
                "rank": idx + 1,
                "name": stock.name,
                "name_ko": stock.name_ko or stock.name,
                "sector": stock.sector,
                "sector_ko": stock.sector_ko,
                "industry": stock.industry,
                "industry_ko": stock.industry_ko,
                "symbol": stock.symbol,
                "currency": cur,
                "country": stock.country,
                "country_ko": country_ko,
                "country_code": stock.country_code,
                "exchange": exchange_name_map.get(stock.exchange, stock.exchange),
                "market_cap_dollor": cap_usd,
                "market_cap_bi_dollor": int(cap_usd / 1_000_000_000),
                "market_cap_bi_won": int(cap_won / 1_000_000_000_000),
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
            "title": "전세계 시가총액 기업 순위 TOP 100",
            "description": f"전세계 시가총액 (Market Cap) 기업 순위 TOP 100 입니다. 각국 통화로 표시된 시가총액을 달러(USD) 기준으로 환산하여 순위를 매겼습니다. {names} 등 전세계 상장 기업들의 시가총액 순위를 달러와 원화로 확인 할수 있습니다.",
            "list": stock_list,
            "exchange_rate": exchange_rate,
            "last_updated_at": datetime.now().isoformat(),
        })

        s3_util.upload_json("api-data/v3/json/investment/stock/world/all/recent/ranking/list.json", result)
        logger.info(f"Uploaded world stock ranking: {len(stock_list)} stocks (FX rates: {usd_rates})")
    finally:
        session.close()
