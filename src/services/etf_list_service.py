"""
ETF list preparation service.
Replaces:
  - PrepareEtfListData#prepare_home_and_list_by_aum_and_sector_and_theme
  - PrepareEtfListData#prepare_list_by_cagr
  - PrepareEtfListData#prepare_compare_list
"""
import logging
from datetime import datetime
from sqlalchemy import desc

from src.models.database import SessionLocal, Etf, EtfSector, EtfTheme, SectorEtf, ThemeEtf
from src.utils import s3_util
from src.utils.exchange_rate import get_exchange_rate

logger = logging.getLogger(__name__)


def _deep_camel_keys(obj):
    def _to_camel(s):
        parts = s.split("_")
        return parts[0] + "".join(w.capitalize() for w in parts[1:])
    if isinstance(obj, dict):
        return {_to_camel(k): _deep_camel_keys(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_camel_keys(i) for i in obj]
    return obj


def _etf_attrs(etf: Etf) -> dict:
    return {
        "symbol": etf.symbol,
        "name": etf.name,
        "aum": etf.aum,
        "volume": etf.volume,
        "segment": etf.segment,
        "category": etf.category,
        "cagr_recent_3year": etf.cagr_recent_3year,
        "cagr_recent_5year": etf.cagr_recent_5year,
        "cagr_recent_10year": etf.cagr_recent_10year,
        "increase_rate_6month": etf.increase_rate_6month,
        "increase_rate_1year": etf.increase_rate_1year,
        "increase_rate_3year": etf.increase_rate_3year,
        "increase_rate_5year": etf.increase_rate_5year,
        "increase_rate_ytd": etf.increase_rate_ytd,
    }


def prepare_home_and_list():
    """Prepare ETF home page data: AUM ranking, sector, theme lists."""
    exchange_rate = get_exchange_rate()
    session = SessionLocal()
    try:
        # AUM ranking
        aum_etfs = (
            session.query(Etf)
            .filter(Etf.name.isnot(None))
            .order_by(desc(Etf.aum))
            .limit(100)
            .all()
        )
        aum_result = [_deep_camel_keys(_etf_attrs(e)) for e in aum_etfs]

        # Sector lists: mapping table + category_match fallback from DB
        sector_result = []
        sectors = session.query(EtfSector).order_by(EtfSector.sort_order).all()
        for sector in sectors:
            # 매핑 테이블 심볼 + category_match로 DB 자동 보충
            mapped_symbols = [
                m.symbol for m in
                session.query(SectorEtf)
                .filter(SectorEtf.sector_slug == sector.slug)
                .order_by(SectorEtf.sort_order)
                .all()
            ]
            if sector.category_match:
                category_etfs = (
                    session.query(Etf)
                    .filter(Etf.category == sector.category_match, Etf.name.isnot(None))
                    .all()
                )
                seen = set(mapped_symbols)
                for e in category_etfs:
                    if e.symbol not in seen:
                        mapped_symbols.append(e.symbol)
                        seen.add(e.symbol)
            if not mapped_symbols:
                continue
            etfs_by_symbol = {
                e.symbol: e
                for e in session.query(Etf).filter(
                    Etf.symbol.in_(mapped_symbols), Etf.name.isnot(None)
                ).all()
            }
            enriched = [_etf_attrs(etfs_by_symbol[s]) for s in mapped_symbols if s in etfs_by_symbol]
            enriched.sort(key=lambda x: x.get("aum") or 0, reverse=True)
            if not enriched:
                continue
            desc_text = ", ".join(e["symbol"] for e in enriched[:5]) + " 등"
            sector_result.append({
                "slug": sector.slug,
                "display_name": sector.name,
                "description": desc_text,
                "etf_list": enriched,
            })

        # Theme lists from DB mapping tables
        theme_result = []
        themes = session.query(EtfTheme).order_by(EtfTheme.sort_order).all()
        for theme in themes:
            mappings = (
                session.query(ThemeEtf)
                .filter(ThemeEtf.theme_slug == theme.slug)
                .order_by(ThemeEtf.sort_order)
                .all()
            )
            symbols = [m.symbol for m in mappings]
            if not symbols:
                continue
            etfs_by_symbol = {
                e.symbol: e
                for e in session.query(Etf).filter(
                    Etf.symbol.in_(symbols), Etf.name.isnot(None)
                ).all()
            }
            enriched = [_etf_attrs(etfs_by_symbol[s]) for s in symbols if s in etfs_by_symbol]
            enriched.sort(key=lambda x: x.get("aum") or 0, reverse=True)
            if not enriched:
                continue
            desc_text = ", ".join(e["symbol"] for e in enriched[:5]) + " 등"
            theme_result.append({
                "slug": theme.slug,
                "display_name": theme.name,
                "description": desc_text,
                "etf_list": enriched,
            })

        # Home response
        home = _deep_camel_keys({
            "title": "미국 ETF- 수익률 순위, AUM 순위, 섹터별, 테마별 주요 ETF",
            "description": "연평균수익률(CAGR)순위, AUM순위, 섹터별, 테마별 주요 ETF를 소개 합니다.",
            "aum": aum_result,
            "sector": sector_result,
            "theme": theme_result,
            "exchange_rate": exchange_rate,
            "last_updated_at": datetime.now().strftime("%Y-%m-%d"),
        })
        s3_util.upload_json("api-data/v2/json/investment/etf/home.json", home)

        # AUM ranking
        aum_ranking = _deep_camel_keys({
            "title": "미국 ETF 운용자산 규모별(AUM)순위",
            "description": "미국 ETF 운용자산 규모별(AUM)순위 입니다.",
            "list": aum_result,
            "exchange_rate": exchange_rate,
            "last_updated_at": datetime.now().strftime("%Y-%m-%d"),
        })
        s3_util.upload_json("api-data/v2/json/investment/etf/aum-ranking.json", aum_ranking)

        # Sector list
        sector_resp = _deep_camel_keys({
            "title": "미국 ETF - 섹터별",
            "description": "섹터별 주요 ETF 입니다. " + ", ".join(s["display_name"] for s in sector_result) + " 등",
            "list": sector_result,
            "exchange_rate": exchange_rate,
            "last_updated_at": datetime.now().strftime("%Y-%m-%d"),
        })
        s3_util.upload_json("api-data/v2/json/investment/etf/sector/list.json", sector_resp)

        # Theme list
        theme_resp = _deep_camel_keys({
            "title": "미국 ETF - 테마별",
            "description": "테마별 주요 ETF 입니다. " + ", ".join(t["display_name"] for t in theme_result) + " 등",
            "list": theme_result,
            "exchange_rate": exchange_rate,
            "last_updated_at": datetime.now().strftime("%Y-%m-%d"),
        })
        s3_util.upload_json("api-data/v2/json/investment/etf/theme/list.json", theme_resp)

        logger.info("Uploaded ETF home, AUM ranking, sector, theme lists")
    finally:
        session.close()


def prepare_list_by_cagr():
    """Prepare ETF CAGR ranking (5yr, 10yr)."""
    exchange_rate = get_exchange_rate()
    excluded = ["Leveraged Equities", "Energy Equities"]
    session = SessionLocal()
    try:
        ten_year_etfs = (
            session.query(Etf)
            .filter(~Etf.category.in_(excluded), Etf.cagr_recent_10year.isnot(None))
            .order_by(desc(Etf.cagr_recent_10year))
            .limit(50)
            .all()
        )
        five_year_etfs = (
            session.query(Etf)
            .filter(~Etf.category.in_(excluded), Etf.cagr_recent_5year.isnot(None))
            .order_by(desc(Etf.cagr_recent_5year))
            .limit(50)
            .all()
        )

        def _slim(etf):
            return {
                "symbol": etf.symbol, "name": etf.name,
                "cagr_recent_3year": etf.cagr_recent_3year,
                "cagr_recent_5year": etf.cagr_recent_5year,
                "cagr_recent_10year": etf.cagr_recent_10year,
                "increase_rate_6month": etf.increase_rate_6month,
                "increase_rate_1year": etf.increase_rate_1year,
                "increase_rate_3year": etf.increase_rate_3year,
                "increase_rate_5year": etf.increase_rate_5year,
                "increase_rate_ytd": etf.increase_rate_ytd,
                "aum": etf.aum, "volume": etf.volume,
            }

        ten_yr = [_slim(e) for e in ten_year_etfs]
        five_yr = [_slim(e) for e in five_year_etfs]

        ten_yr_ranking = {
            "title": "미국 ETF 최근 10년 연평균 수익률 순위",
            "description": f"미국 ETF 최근 10년 연평균 수익률 순위 입니다. {', '.join(e['symbol'] for e in ten_yr[:10])} 등",
            "linkUrl": "/investment/etf/ranking/cagr/ten-year",
            "list": ten_yr,
            "exchange_rate": exchange_rate,
            "last_updated_at": datetime.now().strftime("%Y-%m-%d"),
        }
        five_yr_ranking = {
            "title": "미국 ETF 최근 5년 연평균 수익률 순위",
            "description": f"미국 ETF 최근 5년 연평균 수익률 순위 입니다. {', '.join(e['symbol'] for e in five_yr[:10])} 등",
            "linkUrl": "/investment/etf/ranking/cagr/five-year",
            "list": five_yr,
            "exchange_rate": exchange_rate,
            "last_updated_at": datetime.now().strftime("%Y-%m-%d"),
        }

        result = _deep_camel_keys({
            "title": "미국 ETF 연평균 수익률 순위",
            "description": "최근 5년 및 10년 간 미국 ETF 연평균 수익률 순위 입니다.",
            "exchange_rate": exchange_rate,
            "last_updated_at": datetime.now().strftime("%Y-%m-%d"),
            "ten_year_cagr_etf_ranking": ten_yr_ranking,
            "five_year_cagr_etf_ranking": five_yr_ranking,
            "groups": [ten_yr_ranking, five_yr_ranking],
        })

        s3_util.upload_json("api-data/v2/json/investment/etf/cagr-ranking-home.json", result)
        logger.info("Uploaded ETF CAGR ranking")
    finally:
        session.close()


def prepare_compare_list():
    """Prepare ETF comparison list."""
    exchange_rate = get_exchange_rate()
    session = SessionLocal()
    try:
        representative = [
            {"title": "S&P500 추종", "symbol": "SPY"},
            {"title": "NASDAQ 100기업 투자", "symbol": "QQQ"},
            {"title": "기술기업 투자", "symbol": "VGT"},
            {"title": "반도체기업 투자", "symbol": "SOXX"},
        ]
        for item in representative:
            etf = session.query(Etf).filter(Etf.symbol == item["symbol"]).first()
            if etf:
                item.update(_etf_attrs(etf))

        compare_pairs = [["SPY", "QQQ"], ["SPY", "VGT"], ["QQQ", "VGT"]]
        snp500_pairs = [["SPY", "VOO"], ["SPY", "IVV"], ["VOO", "IVV"]]

        def _build_compare(pairs):
            result = []
            for s1, s2 in pairs:
                e1 = session.query(Etf).filter(Etf.symbol == s1).first()
                e2 = session.query(Etf).filter(Etf.symbol == s2).first()
                if not e1 or not e2:
                    continue
                slug = f"{s1}-vs-{s2}"
                result.append({
                    "slug": slug,
                    "pageUrl": f"/investment/etf/compare/{slug}",
                    "title": f"{s1} vs {s2} 비교 - 수익률, 보유종목 등",
                    "symbol1": s1,
                    "symbol2": s2,
                    "data1": _etf_attrs(e1),
                    "data2": _etf_attrs(e2),
                })
            return result

        popular = {
            "title": "인기 미국 ETF 비교 - 연평균 수익률, TOP10 보유주식 현황 등",
            "description": "인기 ETF 종목별 비교 SPY, QQQ, VGT 등 주요 ETF의 수익률, 주요 보유 주식 현황을 비교 해볼수 있습니다.",
            "list": _build_compare(compare_pairs),
        }
        snp500 = {
            "title": "S&P500 추종 ETF 비교",
            "description": "S&P500를 추종하는 ETF 종목별 비교",
            "list": _build_compare(snp500_pairs),
        }

        all_pairs = compare_pairs + snp500_pairs
        all_compare_list = [f"{s1}-vs-{s2}" for s1, s2 in all_pairs]

        result = _deep_camel_keys({
            "title": "미국 주요 ETF 비교 - 연평균 수익률, TOP10 보유주식 현황 등",
            "description": "미국 주요 ETF 종목별 비교",
            "popular": popular,
            "snp500": snp500,
            "representative": representative,
            "all_compare_list": all_compare_list,
        })

        s3_util.upload_json("api-data/v2/json/investment/etf/compare-list-home.json", result)
        logger.info("Uploaded ETF compare list")
    finally:
        session.close()
