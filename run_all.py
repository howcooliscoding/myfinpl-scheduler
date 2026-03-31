"""
Run both prepare_stock_data and prepare_etf_list_data sequentially.

Usage:
  python run_all.py
  python run_all.py --debug-s3    # log S3 upload payloads
"""
import sys
import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_all")


def main():
    if "--debug-s3" in sys.argv:
        from src.utils.s3_util import set_log_upload_payload
        set_log_upload_payload(True)
        logger.info("S3 upload payload logging ENABLED")

    from src.utils.slack_util import send_message

    total_start = time.time()
    send_message("myfinpl-scheduler: 전체 데이터 수집 시작")

    logger.info("=" * 60)
    logger.info("Phase 1: Stock Data")
    logger.info("=" * 60)
    from run_prepare_stock_data import main as run_stock
    run_stock()

    logger.info("=" * 60)
    logger.info("Phase 2: ETF Data")
    logger.info("=" * 60)
    from run_prepare_etf_list_data import main as run_etf
    run_etf()

    total_took = time.time() - total_start
    send_message(f"myfinpl-scheduler: 전체 완료! (총 소요: {total_took:.0f}s)")
    logger.info(f"All done! Total: {total_took:.0f}s")


if __name__ == "__main__":
    main()
