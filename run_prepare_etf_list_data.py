"""
Prepare ETF List Data - Full pipeline.
yfinance -> calculate -> S3 + DB per ticker, then generate list data.

Usage:
  python run_prepare_etf_list_data.py
  python run_prepare_etf_list_data.py --debug-s3
"""
import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("prepare_etf_list_data")


def main():
    if "--debug-s3" in sys.argv:
        from src.utils.s3_util import set_log_upload_payload
        set_log_upload_payload(True)
        logger.info("S3 upload payload logging ENABLED")

    from src.utils.slack_util import send_message
    from src.services.etf_detail_service import get_all_etf_symbols, process_etf
    from src.services.etf_list_service import (
        prepare_home_and_list,
        prepare_list_by_cagr,
        prepare_compare_list,
    )

    # Step 1: Process ETFs (fetch + calculate + S3 + DB per ticker)
    logger.info("Step 1: Processing ETFs")
    start_time = time.time()
    symbols = get_all_etf_symbols()

    # SPY first
    priority = ["SPY", "QQQ"]
    ordered = [s for s in priority if s in symbols] + [s for s in symbols if s not in priority]

    error_list = []
    for symbol in ordered:
        try:
            process_etf(symbol)
        except Exception as e:
            error_list.append({"symbol": symbol, "error": str(e)})
            logger.error(f"[ETF] {symbol} ERROR: {e}")

    took = time.time() - start_time
    send_message(f"PrepareEtfListData - 1) detail done! ({len(symbols)} symbols, took: {took:.0f}s)")

    if error_list:
        msg = f"ETF errors (count: {len(error_list)})\n"
        for err in error_list[:10]:
            msg += f"{err['symbol']}: {err['error']}\n"
        send_message(msg)

    # Step 2: Prepare list data
    logger.info("Step 2: Preparing list data")
    start_time = time.time()
    prepare_home_and_list()
    prepare_list_by_cagr()
    prepare_compare_list()

    took = time.time() - start_time
    send_message(f"PrepareEtfListData - 2) list done! (took: {took:.0f}s)")

    logger.info("PrepareEtfListData complete!")


if __name__ == "__main__":
    main()
