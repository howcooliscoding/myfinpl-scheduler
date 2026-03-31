# myfinpl-scheduler

미국/한국 주식 및 ETF 데이터를 수집, 가공하여 S3에 API 데이터로 업로드하는 Python 스케줄러.

기존 Ruby + Python 혼합 파이프라인(`prepare_stock_data.rb`, `prepare_etf_list_data.rb`, `crawl-*.py`)을 순수 Python으로 통합.

## 설치

```bash
cd myfinpl-scheduler
pip install -r requirements.txt
cp .env.example .env
```

`.env` 파일에 실제 값을 설정:

```
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
DB_HOST=...
DB_PASSWORD=...
SLACK_WEBHOOK_URL=...   # (선택)
```

## 실행

### 전체 실행 (주식 + ETF)

```bash
python run_all.py
```

### 개별 실행

```bash
# 주식 데이터만
python run_prepare_stock_data.py

# ETF 데이터만
python run_prepare_etf_list_data.py
```

## 파이프라인 흐름

### `run_prepare_stock_data.py`

1. US/KR 심볼 리스트 생성 -> S3 업로드
2. yfinance로 US 주식 히스토리 크롤링 -> S3 업로드
3. 주식별 상세 데이터 가공 (CAGR, MDD, 차트) -> S3 + DB 업데이트
4. yfinance로 KR 주식 히스토리 크롤링 -> S3 업로드
5. KR 주식별 상세 데이터 가공 -> S3 + DB 업데이트
6. 홈 컨텐츠, US/KR 랭킹, CAGR 랭킹, 섹터별 랭킹 생성 -> S3
7. CloudFront 캐시 무효화

### `run_prepare_etf_list_data.py`

1. yfinance + yahooquery로 ETF 히스토리 크롤링 -> S3 업로드
2. ETF별 상세 데이터 가공 (CAGR, MDD, 차트) -> S3 + DB 업데이트
3. ETF 홈, AUM 랭킹, CAGR 랭킹, 섹터/테마별, 비교 리스트 생성 -> S3

## 프로젝트 구조

```
myfinpl-scheduler/
├── run_all.py                    # 전체 실행
├── run_prepare_stock_data.py     # 주식 파이프라인
├── run_prepare_etf_list_data.py  # ETF 파이프라인
├── requirements.txt
├── .env.example
└── src/
    ├── config/settings.py        # 환경변수 설정
    ├── models/database.py        # SQLAlchemy 모델 (Stock, Etf, Currency 등)
    ├── crawlers/
    │   ├── stock_crawler.py      # US/KR 주식 크롤러
    │   └── etf_crawler.py        # ETF 크롤러
    ├── services/
    │   ├── stock_detail_service.py   # 주식 상세 처리
    │   ├── stock_list_service.py     # 주식 심볼/랭킹 리스트
    │   ├── stock_home_service.py     # 홈, CAGR, 섹터 랭킹
    │   ├── etf_detail_service.py     # ETF 상세 처리
    │   └── etf_list_service.py       # ETF 홈, AUM, CAGR, 비교
    └── utils/
        ├── s3_util.py            # S3 업/다운로드
        ├── slack_util.py         # Slack 알림
        ├── cloudfront_util.py    # CDN 캐시 무효화
        ├── exchange_rate.py      # 환율 조회
        └── fin_calculator.py     # CAGR, MDD 계산
```

## 환경변수

| 변수 | 필수 | 설명 |
|------|------|------|
| `AWS_ACCESS_KEY_ID` | O | AWS 액세스 키 |
| `AWS_SECRET_ACCESS_KEY` | O | AWS 시크릿 키 |
| `AWS_REGION` | - | 기본값: `ap-northeast-2` |
| `S3_BUCKET_NAME` | - | 기본값: `myfinpl-data` |
| `DB_HOST` | O | MySQL 호스트 |
| `DB_PORT` | - | 기본값: `3306` |
| `DB_NAME` | - | 기본값: `gov_data_analyst` |
| `DB_USER` | - | 기본값: `admin` |
| `DB_PASSWORD` | O | MySQL 비밀번호 |
| `SLACK_WEBHOOK_URL` | - | 설정 시 Slack 알림 발송 |
| `CLOUDFRONT_DISTRIBUTION_ID` | - | 기본값: `EY236BLQMCM6` |
