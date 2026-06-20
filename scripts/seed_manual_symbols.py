"""
Create the manual_symbols table and seed curated tickers that must always be
included in the stock pipeline regardless of market-cap ranking or exchange.

This is what makes a newly-added ticker such as SPCX (SpaceX) actually flow
through the pipeline: it gets injected into the US symbol list, processed by
StockDetailService (which creates/updates its DB row with worldwide market cap
and metadata), and surfaced in the worldwide market-cap ranking.

Usage:
  # Create table and seed defaults (idempotent)
  python -m scripts.seed_manual_symbols

  # Add / upsert a single ticker
  python -m scripts.seed_manual_symbols --add SPCX --name "SpaceX" --country us

  # Disable a ticker (kept in table but excluded from the pipeline)
  python -m scripts.seed_manual_symbols --disable SPCX

  # List current manual symbols
  python -m scripts.seed_manual_symbols --list
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import logging
from datetime import datetime

from src.models.database import engine, Base, SessionLocal, ManualSymbol

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# (symbol, name, country_code, sort_order)
DEFAULT_SEED = [
    ("SPCX", "SpaceX", "us", 0),
    ("META", "Meta Platforms Inc", "us", 1),
]


def create_table():
    logger.info("Creating manual_symbols table (if not exists)...")
    Base.metadata.create_all(engine, tables=[ManualSymbol.__table__])
    logger.info("Done.")


def upsert(session, symbol, name=None, country_code=None, sort_order=None, enabled=1):
    row = session.query(ManualSymbol).filter(ManualSymbol.symbol == symbol).first()
    now = datetime.now()
    if row:
        if name is not None:
            row.name = name
        if country_code is not None:
            row.country_code = country_code
        row.enabled = enabled
        if sort_order is not None:
            row.sort_order = sort_order
        row.updated_at = now
        logger.info(f"  Updated manual symbol: {symbol}")
    else:
        session.add(ManualSymbol(
            symbol=symbol, name=name, country_code=country_code or "us",
            enabled=enabled, sort_order=sort_order or 0,
            created_at=now, updated_at=now,
        ))
        logger.info(f"  Added manual symbol: {symbol}")


def seed_defaults(session):
    logger.info("Seeding default manual symbols...")
    for symbol, name, country, order in DEFAULT_SEED:
        upsert(session, symbol, name=name, country_code=country, sort_order=order)
    session.commit()


def list_symbols(session):
    rows = session.query(ManualSymbol).order_by(ManualSymbol.country_code, ManualSymbol.sort_order).all()
    if not rows:
        logger.info("No manual symbols registered.")
        return
    logger.info(f"Manual symbols ({len(rows)}):")
    for r in rows:
        status = "enabled" if r.enabled else "DISABLED"
        logger.info(f"  [{r.country_code}] {r.symbol} - {r.name} ({status}, order={r.sort_order})")


def main():
    parser = argparse.ArgumentParser(description="Manage manual (curated) stock symbols")
    parser.add_argument("--add", metavar="SYMBOL", help="Add/upsert a ticker")
    parser.add_argument("--name", help="Display name for --add")
    parser.add_argument("--country", default="us", choices=["us", "kr"], help="Country code for --add")
    parser.add_argument("--order", type=int, default=0, help="Sort order for --add")
    parser.add_argument("--disable", metavar="SYMBOL", help="Disable a ticker")
    parser.add_argument("--enable", metavar="SYMBOL", help="Re-enable a ticker")
    parser.add_argument("--list", action="store_true", help="List manual symbols")
    args = parser.parse_args()

    create_table()
    session = SessionLocal()
    try:
        if args.add:
            upsert(session, args.add.upper(), name=args.name,
                   country_code=args.country, sort_order=args.order)
            session.commit()
        elif args.disable:
            upsert(session, args.disable.upper(), country_code=None, enabled=0)
            session.commit()
        elif args.enable:
            upsert(session, args.enable.upper(), country_code=None, enabled=1)
            session.commit()
        elif args.list:
            list_symbols(session)
        else:
            seed_defaults(session)
            list_symbols(session)
        logger.info("Complete.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
