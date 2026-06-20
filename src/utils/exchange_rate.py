import logging
import yfinance as yf
from datetime import datetime
from src.models.database import SessionLocal, Currency

logger = logging.getLogger(__name__)

# yfinance ticker for USD/KRW spot rate
_USDKRW_TICKER = "KRW=X"


def _fetch_usdkrw() -> float:
    """Fetch the latest USD/KRW base price from yfinance."""
    logger.info(f"[FX] {_USDKRW_TICKER} FETCHING from yfinance...")
    data = yf.download(
        _USDKRW_TICKER,
        period="5d",
        interval="1d",
        auto_adjust=False,
        progress=False,
    )
    if data is None or data.empty:
        raise RuntimeError(f"{_USDKRW_TICKER} 환율 데이터를 가져오지 못했습니다.")

    close = data["Close"]
    # yfinance may return a MultiIndex / DataFrame for the Close column
    if hasattr(close, "columns"):
        close = close.iloc[:, 0]
    close = close.dropna()
    if close.empty:
        raise RuntimeError(f"{_USDKRW_TICKER} 환율 종가 데이터가 비어 있습니다.")

    rate = float(close.iloc[-1])
    logger.info(f"[FX] {_USDKRW_TICKER} fetched: {rate}")
    return rate


def update_exchange_rate():
    base_price = _fetch_usdkrw()
    now = datetime.now()
    session = SessionLocal()
    try:
        currency = Currency(
            code="USD",
            name="미국 달러",
            base_price=base_price,
            last_updated_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(currency)
        session.commit()
        logger.info(f"Exchange rate updated: {base_price}")
    finally:
        session.close()


def get_usd_conversion_rates(currencies) -> dict:
    """Return a map of {CURRENCY: units_per_usd} for converting a market cap
    denominated in that currency into USD via ``amount / rate``.

    Uses yfinance ``{CUR}=X`` tickers, which quote 1 USD = N CUR (e.g. KRW=X,
    JPY=X, CNY=X). USD itself maps to 1.0. Currencies whose rate cannot be
    fetched are simply omitted from the result so callers can skip them.
    """
    rates = {"USD": 1.0}
    targets = sorted({c.upper() for c in currencies if c and c.upper() != "USD"})
    if not targets:
        return rates

    tickers = [f"{c}=X" for c in targets]
    logger.info(f"[FX] fetching USD conversion rates for {targets}")
    try:
        data = yf.download(
            tickers, period="5d", interval="1d",
            auto_adjust=False, progress=False, group_by="column",
        )
    except Exception as e:
        logger.error(f"[FX] multi-currency fetch failed: {e}")
        return rates

    if data is None or data.empty:
        return rates

    close = data["Close"] if "Close" in data else data
    for c in targets:
        col = f"{c}=X"
        try:
            # Batch download -> DataFrame keyed by ticker; single -> Series.
            series = close[col] if hasattr(close, "columns") else close
            series = series.dropna()
            if not series.empty:
                val = float(series.iloc[-1])
                if val > 0:
                    rates[c] = val
        except Exception:
            logger.warning(f"[FX] no rate for {c}")
    return rates


def get_exchange_rate() -> float:
    session = SessionLocal()
    try:
        currency = (
            session.query(Currency)
            .filter(Currency.code == "USD")
            .order_by(Currency.id.desc())
            .first()
        )
        if currency:
            return currency.base_price
        raise RuntimeError("환율 데이터가 없습니다. update_exchange_rate()를 먼저 실행하세요.")
    finally:
        session.close()
