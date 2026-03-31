import time
import logging
from typing import List, Optional
import boto3
from src.config.settings import (
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION,
    CLOUDFRONT_DISTRIBUTION_ID,
)

logger = logging.getLogger(__name__)


def create_invalidation(paths: Optional[List[str]] = None):
    if paths is None:
        paths = ["/*"]
    client = boto3.client(
        "cloudfront",
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION,
    )
    caller_ref = str(int(time.time()))
    response = client.create_invalidation(
        DistributionId=CLOUDFRONT_DISTRIBUTION_ID,
        InvalidationBatch={
            "Paths": {"Quantity": len(paths), "Items": paths},
            "CallerReference": caller_ref,
        },
    )
    inv_id = response["Invalidation"]["Id"]
    logger.info(f"CloudFront invalidation created: {inv_id}")
    return inv_id
