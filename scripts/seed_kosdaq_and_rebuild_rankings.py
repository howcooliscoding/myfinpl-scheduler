"""
1) Seed major KOSDAQ tickers into manual_symbols (country=kr) and process them
   so KOSDAQ stocks (exchange=KOE) exist in the DB.
2) Rebuild all market-cap rankings (US all/nasdaq/nyse, KR all, KOSPI/KOSDAQ,
   World) so the new SEO titles/descriptions and the KOSPI/KOSDAQ pages are
   populated.
3) Invalidate the CDN.

Invalid/delisted symbols are skipped automatically (no data => not stored).

Usage:
  python -m scripts.seed_kosdaq_and_rebuild_rankings
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
warnings.filterwarnings("ignore")

import logging
from datetime import datetime

from src.models.database import SessionLocal, ManualSymbol
from src.services.stock_detail_service import StockDetailService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_kosdaq")

# 코스닥 시총 상위 주요 종목 (.KQ). 유효하지 않은 심볼은 수집 단계에서 자동 제외된다.
KOSDAQ_SYMBOLS = [
    "247540.KQ",  # 에코프로비엠
    "196170.KQ",  # 알테오젠
    "086520.KQ",  # 에코프로
    "028300.KQ",  # HLB
    "058470.KQ",  # 리노공업
    "348370.KQ",  # 엔켐
    "263750.KQ",  # 펄어비스
    "068760.KQ",  # 셀트리온제약
    "214150.KQ",  # 클래시스
    "141080.KQ",  # 리가켐바이오
    "035900.KQ",  # JYP Ent.
    "041510.KQ",  # 에스엠
    "145020.KQ",  # 휴젤
    "214450.KQ",  # 파마리서치
    "257720.KQ",  # 실리콘투
    "277810.KQ",  # 레인보우로보틱스
    "403870.KQ",  # HPSP
    "039030.KQ",  # 이오테크닉스
    "005290.KQ",  # 동진쎄미켐
    "357780.KQ",  # 솔브레인
    "293490.KQ",  # 카카오게임즈
    "112040.KQ",  # 위메이드
    "095660.KQ",  # 네오위즈
    "240810.KQ",  # 원익IPS
    "036930.KQ",  # 주성엔지니어링
    "067160.KQ",  # 아프리카TV(숲)
    "086900.KQ",  # 메디톡스
    "078600.KQ",  # 대주전자재료
    "222800.KQ",  # 심텍
    "098460.KQ",  # 고영
]


def seed_manual():
    session = SessionLocal()
    now = datetime.now()
    try:
        for i, sym in enumerate(KOSDAQ_SYMBOLS):
            row = session.query(ManualSymbol).filter(ManualSymbol.symbol == sym).first()
            if row:
                row.country_code = "kr"
                row.enabled = 1
                row.updated_at = now
            else:
                session.add(ManualSymbol(
                    symbol=sym, name=sym, country_code="kr",
                    enabled=1, sort_order=100 + i, created_at=now, updated_at=now,
                ))
        session.commit()
        logger.info(f"seeded {len(KOSDAQ_SYMBOLS)} KOSDAQ manual symbols")
    finally:
        session.close()


def process_symbols():
    ok, fail = 0, 0
    for sym in KOSDAQ_SYMBOLS:
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
    seed_manual()
    process_symbols()
    rebuild_rankings()
    try:
        from src.utils.cloudfront_util import create_invalidation
        create_invalidation()
        logger.info("CloudFront invalidation requested")
    except Exception as e:
        logger.warning(f"invalidation skipped: {e}")


if __name__ == "__main__":
    main()
