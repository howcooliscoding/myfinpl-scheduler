from sqlalchemy import create_engine, Column, Integer, Float, String, Text, DateTime, Enum, BigInteger
from sqlalchemy.orm import declarative_base, sessionmaker
from src.config.settings import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_size=10, pool_recycle=3600, echo=False)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Stock(Base):
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    country = Column(String(255))
    country_code = Column(String(10))
    market = Column(String(255))
    symbol = Column(String(50), unique=True, index=True)
    alternative_symbol = Column(String(50))
    slug = Column(String(255))
    name = Column(String(255))
    name_ko = Column(String(255))
    market_cap = Column(Float)
    currency = Column(String(10))
    exchange = Column(String(50))
    sector = Column(String(255))
    sector_ko = Column(String(255))
    industry = Column(String(255))
    industry_ko = Column(String(255))
    dividend = Column(Float)
    # yield is a reserved word in Python
    dividend_yield = Column("yield", Float)
    cagr_3year = Column(Float)
    cagr_5year = Column(Float)
    cagr_7year = Column(Float)
    cagr_10year = Column(Float)
    cagr_20year = Column(Float)
    cagr_30year = Column(Float)
    increase_rate_ytd = Column(Float)
    increase_rate_week = Column(Float)
    increase_rate_month = Column(Float)
    increase_rate_year = Column(Float)
    increase_rate_year3 = Column(Float)
    additional_info = Column(Text)
    ipoyear = Column(String(10))
    detail_link = Column(String(255))
    last_updated_at = Column(DateTime)
    enabled = Column(Integer)
    stock_class = Column(Integer)
    employees = Column(Integer)
    current_drawdown = Column(Float)
    mdd = Column(Float)
    best_year = Column(Float)
    worst_year = Column(Float)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    def to_list_item(self, exchange_rate: float) -> dict:
        return {
            "name": self.name,
            "nameKo": self.name_ko or self.name,
            "sector": self.sector,
            "sectorKo": self.sector_ko or self.sector,
            "industry": self.industry,
            "industryKo": self.industry_ko or self.industry,
            "symbol": self.symbol,
            "marketCapDollor": self.market_cap,
            "marketCapBiDollor": (self.market_cap or 0) / 1_000_000_000,
            "marketCapBiWon": int(((self.market_cap or 0) * exchange_rate) / 1_000_000_000_000),
            "country": self.country,
            "exchange": self.exchange,
            "increaseRateYtd": self.increase_rate_ytd,
            "increaseRateYear": self.increase_rate_year,
            "increaseRateYear3": self.increase_rate_year3,
            "cagr3year": self.cagr_3year,
            "cagr5year": self.cagr_5year,
            "cagr7year": self.cagr_7year,
            "cagr10year": self.cagr_10year,
            "cagr20year": self.cagr_20year,
            "cagr30year": self.cagr_30year,
            "currentDrawdown": self.current_drawdown,
            "mdd": self.mdd,
            "bestYear": self.best_year,
            "worstYear": self.worst_year,
        }


class StockDetail(Base):
    __tablename__ = "stock_details"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(50), unique=True, index=True)
    detail = Column(Text)
    chart_data = Column(Text)
    extra = Column(Text)
    last_updated_at = Column(DateTime)


class StockName(Base):
    __tablename__ = "stock_names"

    symbol = Column(String(10), primary_key=True)
    locale = Column(String(5), primary_key=True)
    name = Column(String(1024))
    original_name = Column(String(1024))
    short_name = Column(String(100))
    long_name = Column(String(1024))
    alternative_name = Column(String(100))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class StockTag(Base):
    __tablename__ = "stock_tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(50), index=True)
    tag_type = Column(String(50))
    value = Column(String(255))
    display_text = Column(String(255))


class StockSector(Base):
    __tablename__ = "stock_sectors"

    slug = Column(String(100), primary_key=True)
    name = Column(String(100))
    name_ko = Column(String(100))
    total_market_cap = Column(Float)
    description = Column(String(100))


class Etf(Base):
    __tablename__ = "etfs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    country = Column(String(255))
    market = Column(String(255))
    symbol = Column(String(50), unique=True, index=True)
    name = Column(String(255))
    aum = Column(Float)
    price = Column(Float)
    volume = Column(BigInteger)
    segment = Column(String(255))
    category = Column(String(255))
    cagr_recent_3year = Column(Float)
    cagr_recent_5year = Column(Float)
    cagr_recent_7year = Column(Float)
    cagr_recent_10year = Column(Float)
    cagr_recent_20year = Column(Float)
    increase_rate_6month = Column(Float)
    increase_rate_1year = Column(Float)
    increase_rate_3year = Column(Float)
    increase_rate_5year = Column(Float)
    increase_rate_ytd = Column(Float)
    additional_info = Column(Text)
    detail_link = Column(String(255))
    enabled = Column(Integer)
    current_drawdown = Column(Float)
    mdd = Column(Float)
    best_year = Column(Float)
    worst_year = Column(Float)
    last_updated_at = Column(DateTime)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    def to_list_item(self, exchange_rate: float = 1.0) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "aum": self.aum,
            "volume": self.volume,
            "increaseRateYtd": self.increase_rate_ytd,
            "increaseRate6Month": self.increase_rate_6month,
            "increaseRate1Year": self.increase_rate_1year,
            "increaseRate3Year": self.increase_rate_3year,
            "increaseRate5Year": self.increase_rate_5year,
            "cagr3year": self.cagr_recent_3year,
            "cagr5year": self.cagr_recent_5year,
            "cagr7year": self.cagr_recent_7year,
            "cagr10year": self.cagr_recent_10year,
            "currentDrawdown": self.current_drawdown,
            "mdd": self.mdd,
            "bestYear": self.best_year,
            "worstYear": self.worst_year,
        }


class EtfTag(Base):
    __tablename__ = "etf_tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(50), index=True)
    tag_type = Column(String(50))
    value = Column(String(255))
    display_text = Column(String(255))


class Currency(Base):
    __tablename__ = "currencies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10))
    name = Column(String(50))
    base_price = Column(Float)
    cash_buying_price = Column(Float)
    cash_selling_price = Column(Float)
    tt_buying_price = Column(Float)
    tt_selling_price = Column(Float)
    last_updated_at = Column(DateTime)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
