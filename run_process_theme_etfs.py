"""
Process only theme-mapped ETFs, then refresh the list data.
Much faster than the full pipeline - only processes ETFs in theme_etfs table.

Usage:
  python run_process_theme_etfs.py
  python run_process_theme_etfs.py --debug-s3
"""
import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("process_theme_etfs")


def main():
    if "--debug-s3" in sys.argv:
        from src.utils.s3_util import set_log_upload_payload
        set_log_upload_payload(True)
        logger.info("S3 upload payload logging ENABLED")

    from src.models.database import SessionLocal, ThemeEtf
    from src.services.etf_detail_service import process_etf
    from src.services.etf_list_service import prepare_home_and_list

    session = SessionLocal()
    try:
        # Get unique symbols from theme mappings
        rows = session.query(ThemeEtf.symbol).distinct().all()
        symbols = [r.symbol for r in rows]
        logger.info(f"Found {len(symbols)} unique theme ETFs to process")
    finally:
        session.close()

    # Step 1: Process each ETF (yfinance -> calculate -> S3 + DB)
    start_time = time.time()
    error_list = []
    for i, symbol in enumerate(symbols):
        try:
            logger.info(f"[{i+1}/{len(symbols)}] Processing {symbol}")
            process_etf(symbol)
        except Exception as e:
            error_list.append({"symbol": symbol, "error": str(e)})
            logger.error(f"[ETF] {symbol} ERROR: {e}")

    took = time.time() - start_time
    logger.info(f"Step 1 done: {len(symbols)} symbols processed ({len(error_list)} errors, {took:.0f}s)")

    if error_list:
        for err in error_list:
            logger.warning(f"  FAILED: {err['symbol']}: {err['error']}")

    # Step 2: Refresh home + sector/theme lists
    logger.info("Step 2: Refreshing lists...")
    start_time = time.time()
    prepare_home_and_list()
    took = time.time() - start_time
    logger.info(f"Step 2 done: lists refreshed ({took:.0f}s)")


if __name__ == "__main__":
    main()
