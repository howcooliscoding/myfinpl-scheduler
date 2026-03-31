import json
import logging
import boto3
from src.config.settings import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, S3_BUCKET_NAME

logger = logging.getLogger(__name__)

_s3_client = None

# Global flag: log upload payload. Default OFF.
LOG_UPLOAD_PAYLOAD = False


def set_log_upload_payload(enabled: bool):
    global LOG_UPLOAD_PAYLOAD
    LOG_UPLOAD_PAYLOAD = enabled


def _get_client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION,
        )
    return _s3_client


def upload_json(object_key: str, data, bucket: str = S3_BUCKET_NAME):
    body = json.dumps(data, ensure_ascii=False, default=str)
    _get_client().put_object(
        Bucket=bucket,
        Key=object_key,
        Body=body.encode("utf-8"),
        ContentType="application/json",
    )
    logger.info(f"Uploaded: s3://{bucket}/{object_key} ({len(body)} bytes)")
    if LOG_UPLOAD_PAYLOAD:
        _log_payload(object_key, data)


_HISTORY_KEYS = {"histories", "yearIncreaseHistories", "year_increase_histories",
                  "mdd_histories", "mddHistories"}


def _log_payload(object_key, data):
    """Log payload with history arrays replaced by count summary."""
    def _strip_histories(obj):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if k in _HISTORY_KEYS and isinstance(v, list):
                    out[k] = f"[...{len(v)} items]"
                else:
                    out[k] = _strip_histories(v)
            return out
        if isinstance(obj, list):
            return [_strip_histories(i) for i in obj]
        return obj

    cleaned = _strip_histories(data)
    logger.info(f"[S3 PAYLOAD] {object_key}:\n{json.dumps(cleaned, ensure_ascii=False, default=str, indent=2)}")


def download_json(object_key: str, bucket: str = S3_BUCKET_NAME):
    response = _get_client().get_object(Bucket=bucket, Key=object_key)
    body = response["Body"].read().decode("utf-8")
    return json.loads(body)


def upload_file(local_path: str, object_key: str, bucket: str = S3_BUCKET_NAME):
    _get_client().upload_file(Filename=local_path, Bucket=bucket, Key=object_key)
    logger.info(f"Uploaded file: {local_path} -> s3://{bucket}/{object_key}")


def download_file(object_key: str, local_path: str, bucket: str = S3_BUCKET_NAME):
    _get_client().download_file(Bucket=bucket, Key=object_key, Filename=local_path)
    logger.info(f"Downloaded: s3://{bucket}/{object_key} -> {local_path}")
