import logging
import requests
from src.config.settings import SLACK_WEBHOOK_URL

logger = logging.getLogger(__name__)


def send_message(content: str):
    if not SLACK_WEBHOOK_URL:
        logger.info(f"[Slack] {content}")
        return
    try:
        requests.post(SLACK_WEBHOOK_URL, json={"text": content}, timeout=10)
    except Exception as e:
        logger.error(f"Slack send failed: {e}")
