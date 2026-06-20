"""
Backfill stocks.website (for company logos/favicons) for symbols that appear in
the US / world / KR market-cap rankings, then regenerate those ranking JSONs so
the `domain` field is populated, and invalidate the CDN cache.

Website is fetched from yfinance ``Ticker.info['website']``. Only symbols whose
website is currently empty are fetched. Runs lookups in parallel for speed.

Usage:
  python -m scripts.backfill_logo_domains
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
warnings.filterwarnings("ignore")

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import yfinance as yf

from src.models.database import SessionLocal, Stock
from src.utils import s3_util

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_logo")

RANKING_KEYS = [
    "api-data/v3/json/investment/stock/us/all/recent/ranking/list.json",
    "api-data/v3/json/investment/stock/world/all/recent/ranking/list.json",
    "api-data/v3/json/investment/stock/kr/all/recent/ranking/list.json",
]


def collect_ranking_symbols():
    symbols = set()
    for key in RANKING_KEYS:
        try:
            data = s3_util.download_json(key)
            for item in data.get("list", []):
                if item.get("symbol"):
                    symbols.add(item["symbol"])
        except Exception as e:
            logger.warning(f"skip {key}: {e}")
    return symbols


def fetch_website(symbol):
    try:
        info = yf.Ticker(symbol).info or {}
        return symbol, info.get("website") or info.get("irWebsite")
    except Exception as e:
        logger.warning(f"{symbol} website fetch failed: {e}")
        return symbol, None


def main():
    symbols = collect_ranking_symbols()
    logger.info(f"ranking symbols: {len(symbols)}")

    # Only fetch symbols whose website is currently empty.
    session = SessionLocal()
    try:
        rows = session.query(Stock).filter(Stock.symbol.in_(symbols)).all()
        todo = [r.symbol for r in rows if not r.website]
    finally:
        session.close()
    logger.info(f"missing website: {len(todo)}")

    results = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(fetch_website, s) for s in todo]
        for fut in as_completed(futures):
            sym, web = fut.result()
            if web:
                results[sym] = web

    logger.info(f"fetched websites: {len(results)}")

    # Persist
    session = SessionLocal()
    try:
        for sym, web in results.items():
            stock = session.query(Stock).filter(Stock.symbol == sym).first()
            if stock:
                stock.website = web
        session.commit()
        logger.info("DB updated")
    except Exception as e:
        session.rollback()
        logger.error(f"DB update failed: {e}")
    finally:
        session.close()

    # Regenerate rankings so the domain field is populated
    from src.services.stock_list_service import (
        prepare_api_for_us_stock,
        prepare_api_for_korean_stock,
        prepare_api_for_world_stock,
    )
    prepare_api_for_us_stock()
    prepare_api_for_korean_stock()
    prepare_api_for_world_stock()
    logger.info("rankings regenerated")

    try:
        from src.utils.cloudfront_util import create_invalidation
        create_invalidation()
        logger.info("CloudFront invalidation requested")
    except Exception as e:
        logger.warning(f"invalidation skipped: {e}")


if __name__ == "__main__":
    main()
