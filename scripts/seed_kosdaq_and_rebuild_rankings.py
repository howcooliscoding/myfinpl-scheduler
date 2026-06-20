"""
1) Fetch the top KOSDAQ tickers by market cap from FinanceDataReader (KRX data),
   seed them into manual_symbols (country=kr) with Korean names (stock_names),
   and process them so KOSDAQ stocks (exchange=KOE/KSQ) exist in the DB.
2) Rebuild all market-cap rankings (US all/nasdaq/nyse, KR all, KOSPI/KOSDAQ,
   World) so the SEO titles/descriptions and the KOSPI/KOSDAQ pages are current.
3) Invalidate the CDN.

Invalid/delisted symbols are skipped automatically (no data => not stored).
We process slightly more than 100 to absorb any yfinance misses.

Usage:
  python -m scripts.seed_kosdaq_and_rebuild_rankings [count]   # default 110
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
warnings.filterwarnings("ignore")

import logging
from datetime import datetime

import FinanceDataReader as fdr

from src.models.database import SessionLocal, ManualSymbol, StockName, Stock
from src.services.stock_detail_service import StockDetailService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_kosdaq")

TARGET_COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 110


def fetch_top_kosdaq(count):
    df = fdr.StockListing("KOSDAQ")
    df = df[df["Marcap"].notna()].sort_values("Marcap", ascending=False).head(count)
    # (symbol, korean_name)
    return [(f"{row.Code}.KQ", str(row.Name)) for row in df.itertuples()]


def seed(items):
    session = SessionLocal()
    now = datetime.now()
    try:
        for i, (sym, ko) in enumerate(items):
            # manual_symbols (always-include)
            row = session.query(ManualSymbol).filter(ManualSymbol.symbol == sym).first()
            if row:
                row.country_code = "kr"; row.enabled = 1; row.name = ko; row.updated_at = now
            else:
                session.add(ManualSymbol(
                    symbol=sym, name=ko, country_code="kr",
                    enabled=1, sort_order=100 + i, created_at=now, updated_at=now,
                ))
            # stock_names (Korean display name)
            sn = session.query(StockName).filter(StockName.symbol == sym, StockName.locale == "ko").first()
            if sn:
                sn.name = ko; sn.updated_at = now
            else:
                session.add(StockName(symbol=sym, locale="ko", name=ko, short_name=ko, created_at=now, updated_at=now))
        session.commit()
        logger.info(f"seeded {len(items)} KOSDAQ symbols (manual_symbols + stock_names)")
    finally:
        session.close()


def process_symbols(items):
    ok, fail = 0, 0
    for sym, _ in items:
        try:
            StockDetailService("kr").process(sym)
            ok += 1
        except Exception as e:
            fail += 1
            logger.warning(f"{sym} process failed: {e}")
    logger.info(f"processed: ok={ok} fail={fail}")


def rebuild_rankings():
    from src.services.stock_list_service import (
        prepare_api_for_us_stock,
        prepare_api_for_korean_stock,
        prepare_api_for_kr_sub_markets,
        prepare_api_for_world_stock,
    )
    prepare_api_for_us_stock()
    prepare_api_for_korean_stock()
    prepare_api_for_kr_sub_markets()
    prepare_api_for_world_stock()
    logger.info("all rankings rebuilt")


def main():
    items = fetch_top_kosdaq(TARGET_COUNT)
    logger.info(f"fetched top {len(items)} KOSDAQ tickers from FDR")
    seed(items)
    process_symbols(items)
    rebuild_rankings()
    try:
        from src.utils.cloudfront_util import create_invalidation
        create_invalidation()
        logger.info("CloudFront invalidation requested")
    except Exception as e:
        logger.warning(f"invalidation skipped: {e}")


if __name__ == "__main__":
    main()
