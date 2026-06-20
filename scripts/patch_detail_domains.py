"""
Lightweight patch: add the `domain` field to existing stock DETAIL JSONs
(api-data/v1 & v2 .../investment/stock/{symbol}.json) using stocks.website,
WITHOUT a full re-fetch/recompute. Makes company logos show on detail pages
immediately. Then invalidates the CDN cache.

Usage:
  python -m scripts.patch_detail_domains
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
warnings.filterwarnings("ignore")

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.models.database import SessionLocal, Stock
from src.utils import s3_util
from src.services.stock_detail_service import domain_from_website

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("patch_detail_domains")


def patch_symbol(symbol, domain):
    patched = 0
    for ver in ("v1", "v2"):
        key = f"api-data/{ver}/json/investment/stock/{symbol}.json"
        try:
            data = s3_util.download_json(key)
        except Exception:
            continue  # detail JSON may not exist for this version
        if data.get("domain") == domain:
            continue
        data["domain"] = domain
        try:
            s3_util.upload_json(key, data)
            patched += 1
        except Exception as e:
            logger.warning(f"{key} upload failed: {e}")
    return symbol, patched


def main():
    session = SessionLocal()
    try:
        rows = session.query(Stock).filter(Stock.website.isnot(None)).all()
        targets = [(r.symbol, domain_from_website(r.website)) for r in rows]
    finally:
        session.close()
    targets = [(s, d) for s, d in targets if d]
    logger.info(f"symbols with website: {len(targets)}")

    total = 0
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = [ex.submit(patch_symbol, s, d) for s, d in targets]
        for fut in as_completed(futures):
            _, n = fut.result()
            total += n
    logger.info(f"detail JSONs patched: {total}")

    try:
        from src.utils.cloudfront_util import create_invalidation
        create_invalidation()
        logger.info("CloudFront invalidation requested")
    except Exception as e:
        logger.warning(f"invalidation skipped: {e}")


if __name__ == "__main__":
    main()
