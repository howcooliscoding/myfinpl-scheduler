"""
Refresh ETF home and theme/sector list data only.
Skips individual ETF processing (yfinance fetch, S3 upload per ticker).
Reads from DB mapping tables and uploads aggregated list JSONs to S3.

Usage:
  python run_refresh_etf_list.py
  python run_refresh_etf_list.py --debug-s3
"""
import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("refresh_etf_list")


def main():
    if "--debug-s3" in sys.argv:
        from src.utils.s3_util import set_log_upload_payload
        set_log_upload_payload(True)
        logger.info("S3 upload payload logging ENABLED")

    from src.services.etf_list_service import prepare_home_and_list

    logger.info("Refreshing ETF home, sector, theme lists...")
    start_time = time.time()
    prepare_home_and_list()
    took = time.time() - start_time
    logger.info(f"Done! (took: {took:.0f}s)")


if __name__ == "__main__":
    main()
