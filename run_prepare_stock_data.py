"""
Prepare Stock Data - Full pipeline.
yfinance -> calculate -> S3 + DB per ticker, then generate list data.

Usage:
  python run_prepare_stock_data.py
  python run_prepare_stock_data.py --debug-s3
"""
import sys
import json
import os
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("prepare_stock_data")


def main():
    if "--debug-s3" in sys.argv:
        from src.utils.s3_util import set_log_upload_payload
        set_log_upload_payload(True)
        logger.info("S3 upload payload logging ENABLED")

    from src.utils.slack_util import send_message
    from src.utils.cloudfront_util import create_invalidation
    from src.utils.exchange_rate import update_exchange_rate

    # Update exchange rate first
    try:
        update_exchange_rate()
    except Exception as e:
        logger.error(f"Exchange rate update failed: {e}")
    from src.services.stock_list_service import (
        prepare_api_all_symbol_list,
        get_api_data_symbol_list,
        prepare_api_for_us_stock,
        prepare_api_for_korean_stock,
        prepare_api_for_world_stock,
    )
    from src.services.stock_detail_service import StockDetailService
    from src.services.stock_home_service import (
        prepare_home_contents,
        prepare_list_by_cagr,
        prepare_sector_api_list,
    )

    # Step 1: Prepare symbol list
    logger.info("Step 1: Preparing symbol list")
    prepare_api_all_symbol_list()

    # Step 2: Process US stocks (fetch + calculate + S3 + DB per ticker)
    logger.info("Step 2: Processing US stocks")
    start_time = time.time()
    error_list = []
    symbols = get_api_data_symbol_list()

    for symbol in symbols:
        try:
            StockDetailService("us").process(symbol)
        except Exception as e:
            error_list.append({"symbol": symbol, "error": str(e)})
            logger.error(f"[Stock] {symbol} ERROR: {e}")

    send_message(f"PrepareStockData - 1) US stocks done! ({len(symbols)} symbols)")

    # Step 3: Process Korean stocks
    logger.info("Step 3: Processing Korean stocks")
    ko_symbol_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "lib", "data", "ko_symbol-list.json",
    )
    if os.path.exists(ko_symbol_file):
        with open(ko_symbol_file, "r") as f:
            ko_symbols = json.load(f)
    else:
        from src.utils import s3_util
        ko_data = s3_util.download_json("api-data/v1/json/investment/stock/ko-stock/symbol-list.json")
        ko_symbols = [s["symbol"] if isinstance(s, dict) else s for s in ko_data]

    for symbol in ko_symbols:
        try:
            StockDetailService("kr").process(symbol)
        except Exception as e:
            error_list.append({"symbol": symbol, "error": str(e)})

    if error_list:
        msg = f"Errors at PrepareStockData (count: {len(error_list)})\n"
        for err in error_list[:10]:
            msg += f"{err['symbol']}: {err['error']}\n"
        send_message(msg)

    took = time.time() - start_time
    send_message(f"PrepareStockData - 2) detail done! (took: {took:.0f}s)")

    # Step 4: Prepare list data
    logger.info("Step 4: Preparing list data")
    start_time = time.time()
    prepare_home_contents()
    prepare_api_for_us_stock()
    prepare_api_for_korean_stock()
    prepare_api_for_world_stock()
    prepare_list_by_cagr()
    prepare_sector_api_list()

    took = time.time() - start_time
    send_message(f"PrepareStockData - 3) list done! (took: {took:.0f}s)")

    # Step 5: CloudFront invalidation
    logger.info("Step 5: CloudFront invalidation")
    create_invalidation()

    logger.info("PrepareStockData complete!")


if __name__ == "__main__":
    main()
