import logging
import requests
from datetime import datetime
from src.models.database import SessionLocal, Currency

logger = logging.getLogger(__name__)


def update_exchange_rate():
    url = "https://quotation-api-cdn.dunamu.com/v1/forex/recent?codes=FRX.KRWUSD"
    res = requests.get(url, timeout=10)
    data = res.json()
    if not data:
        return
    item = data[0]
    session = SessionLocal()
    try:
        currency = Currency(
            code=item["currencyCode"],
            name=item["name"],
            base_price=item["basePrice"],
            cash_buying_price=item["cashBuyingPrice"],
            cash_selling_price=item["cashSellingPrice"],
            tt_buying_price=item["ttBuyingPrice"],
            tt_selling_price=item["ttSellingPrice"],
            last_updated_at=datetime.now(),
        )
        session.add(currency)
        session.commit()
        logger.info(f"Exchange rate updated: {item['basePrice']}")
    finally:
        session.close()


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
        return 1300.0  # fallback
    finally:
        session.close()
