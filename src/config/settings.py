import os
from dotenv import load_dotenv

load_dotenv()

# AWS
AWS_ACCESS_KEY_ID = os.environ["AWS_ACCESS_KEY_ID"]
AWS_SECRET_ACCESS_KEY = os.environ["AWS_SECRET_ACCESS_KEY"]
AWS_REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "myfinpl-data")

# Database
DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_NAME = os.environ.get("DB_NAME", "gov_data_analyst")
DB_USER = os.environ.get("DB_USER", "admin")
DB_PASSWORD = os.environ["DB_PASSWORD"]
DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"

# Slack
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

# CloudFront
CLOUDFRONT_DISTRIBUTION_ID = os.environ.get("CLOUDFRONT_DISTRIBUTION_ID", "EY236BLQMCM6")

# Collection
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "5"))
REQUEST_DELAY = float(os.environ.get("REQUEST_DELAY", "0.5"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
