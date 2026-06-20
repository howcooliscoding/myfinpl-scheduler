"""
One-time migration: create etf_sectors, etf_themes, sector_etfs, theme_etfs
and seed them from current SECTOR_MAP / THEME_MAP data.

Usage: python -m scripts.migrate_etf_sector_theme
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from src.models.database import (
    engine, Base, SessionLocal, Etf,
    EtfSector, EtfTheme, SectorEtf, ThemeEtf,
)
from src.utils import s3_util

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


SECTOR_SEED = [
    ("technology", "테크놀로지", "Technology", "Technology Equities"),
    ("healthcare", "헬스케어", "Healthcare", "Health  Biotech Equities"),
    ("real-estate", "부동산", "Real Estate", "Real Estate"),
    ("financials", "금융", "Financials", "Financials Equities"),
    ("energy", "에너지", "Energy", "Energy Equities"),
]

THEME_SEED = [
    ("ai", "AI/인공지능", "/themes/artificial-intelligence-etfs/"),
    ("semiconductor", "반도체", "/themes/semiconductor-etfs/"),
    ("blockchain", "블록체인", "/themes/blockchain-etfs/"),
    ("esg", "ESG", "/esg-investing/environmental-issues/alternative-energy/"),
    ("leveraged-2x", "레버리지 2배", "/themes/leveraged-2x-etfs/"),
    ("leveraged-3x", "레버리지 3배", "/themes/leveraged-3x-etfs/"),
    ("leveraged-3x-inverse-short", "3X 인버스", "/themes/leveraged-3x-inverse-short-etfs/"),
]

# S3 크롤 데이터가 비어있을 때 사용할 기본 심볼 목록
THEME_FALLBACK_SYMBOLS = {
    "ai": [
        "AIQ", "BOTZ", "ROBO", "IRBO", "ARKQ",
        "QTUM", "CHAT", "BUZZ", "LRNZ", "IDNA",
    ],
    "semiconductor": [
        "SOXX", "SMH", "SOXQ", "XSD", "PSI",
        "FTXL", "CHPS",
    ],
    "esg": [
        "ICLN", "QCLN", "TAN", "PBW", "ACES",
        "FAN", "SMOG", "ERTH", "CNRG", "CTEC",
    ],
    "leveraged-3x-inverse-short": [
        "SQQQ", "SPXS", "TZA", "SPXU", "SRTY",
        "SDOW", "SOXS", "TECS", "LABD", "FAZ",
        "TMV", "TTT", "YANG", "ERY", "DRV",
    ],
}


def create_tables():
    logger.info("Creating tables...")
    Base.metadata.create_all(engine, tables=[
        EtfSector.__table__,
        EtfTheme.__table__,
        SectorEtf.__table__,
        ThemeEtf.__table__,
    ])
    logger.info("Tables created.")


def seed_sectors(session):
    logger.info("Seeding etf_sectors and sector_etfs...")
    existing_mappings = {
        (m.sector_slug, m.symbol)
        for m in session.query(SectorEtf).all()
    }

    for idx, (slug, name, name_en, category_match) in enumerate(SECTOR_SEED):
        sector = session.get(EtfSector, slug)
        if not sector:
            sector = EtfSector(
                slug=slug, name=name, name_en=name_en,
                category_match=category_match, sort_order=idx,
            )
            session.add(sector)
            logger.info(f"  Added sector: {slug}")

        etfs = (
            session.query(Etf)
            .filter(Etf.category == category_match, Etf.name.isnot(None))
            .order_by(Etf.aum.desc())
            .all()
        )
        count = 0
        for etf_idx, etf in enumerate(etfs):
            if (slug, etf.symbol) not in existing_mappings:
                session.add(SectorEtf(
                    sector_slug=slug, symbol=etf.symbol, sort_order=etf_idx,
                ))
                existing_mappings.add((slug, etf.symbol))
                count += 1
        logger.info(f"  {slug}: {count} ETFs mapped (total {len(etfs)} matched)")

    session.commit()


def seed_themes(session):
    logger.info("Seeding etf_themes and theme_etfs...")
    existing_mappings = {
        (m.theme_slug, m.symbol)
        for m in session.query(ThemeEtf).all()
    }

    for idx, (slug, name, s3_path) in enumerate(THEME_SEED):
        theme = session.get(EtfTheme, slug)
        if not theme:
            theme = EtfTheme(
                slug=slug, name=name, s3_crawl_path=s3_path, sort_order=idx,
            )
            session.add(theme)
            logger.info(f"  Added theme: {slug}")

        # Pull symbol list from existing S3 crawl-result + merge fallback symbols
        s3_key = f"crawl-result/v2/json/investment/etf-list/by-request-url{s3_path}"
        try:
            etf_list = s3_util.download_json(s3_key)
            symbols = [e["symbol"] for e in etf_list]
        except Exception as e:
            logger.warning(f"  Failed to download {s3_key}: {e}")
            symbols = []

        # Always merge fallback symbols (deduplicated, fallback first for priority)
        if slug in THEME_FALLBACK_SYMBOLS:
            fallback = THEME_FALLBACK_SYMBOLS[slug]
            seen = set()
            merged = []
            for sym in fallback + symbols:
                if sym not in seen:
                    seen.add(sym)
                    merged.append(sym)
            symbols = merged
            logger.info(f"  Merged fallback + S3 symbols for {slug}: {len(symbols)} total")

        # Only map symbols that exist in the etfs table
        existing_symbols = {
            row.symbol
            for row in session.query(Etf.symbol).filter(Etf.symbol.in_(symbols)).all()
        } if symbols else set()

        missing = [s for s in symbols if s not in existing_symbols]
        if missing:
            logger.warning(f"  {slug}: symbols NOT in etfs table: {missing}")

        count = 0
        for etf_idx, sym in enumerate(symbols):
            if sym in existing_symbols and (slug, sym) not in existing_mappings:
                session.add(ThemeEtf(
                    theme_slug=slug, symbol=sym, sort_order=etf_idx,
                ))
                existing_mappings.add((slug, sym))
                count += 1
        logger.info(f"  {slug}: {count} new ETFs mapped, {len(existing_symbols)} found in DB")

    session.commit()


def main():
    create_tables()
    session = SessionLocal()
    try:
        seed_sectors(session)
        seed_themes(session)
        logger.info("Migration complete.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
