"""
Test crawling a single stock or ETF ticker.

Usage:
  python test_crawl_ticker.py stock AAPL
  python test_crawl_ticker.py stock 005930.KS
  python test_crawl_ticker.py etf SPY
  python test_crawl_ticker.py etf TTT
  python test_crawl_ticker.py stock CONE
  python test_crawl_ticker.py etf SPY --debug-s3   # also log S3 upload payload
"""
import sys
import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]

    if len(args) < 2:
        print("Usage: python test_crawl_ticker.py <stock|etf> <SYMBOL> [--debug-s3]")
        print()
        print("Examples:")
        print("  python test_crawl_ticker.py stock AAPL")
        print("  python test_crawl_ticker.py etf SPY")
        print("  python test_crawl_ticker.py etf SPY --debug-s3")
        sys.exit(1)

    if "--debug-s3" in flags:
        from src.utils.s3_util import set_log_upload_payload
        set_log_upload_payload(True)

    ticker_type = args[0].lower()
    symbol = args[1]

    if ticker_type == "stock":
        from src.crawlers.stock_crawler import _crawl_single_stock
        print(f"Crawling stock: {symbol}")
        result = _crawl_single_stock(symbol)
    elif ticker_type == "etf":
        from src.crawlers.etf_crawler import _crawl_single_etf
        print(f"Crawling ETF: {symbol}")
        result = _crawl_single_etf(symbol)
    else:
        print(f"Unknown type: {ticker_type}. Use 'stock' or 'etf'.")
        sys.exit(1)

    if result is None:
        print(f"\nFAILED: No data returned for {symbol}")
        sys.exit(1)

    # Summary
    histories = result.get("histories", [])
    print(f"\nSUCCESS: {symbol}")
    print(f"  History rows: {len(histories)}")
    if histories:
        print(f"  Date range: {histories[0]['date']} ~ {histories[-1]['date']}")
        print(f"  Last close: {histories[-1]['close']}")
    print(f"  Dividends: {len(result.get('dividends', []))}")
    print(f"  Splits: {len(result.get('splits', []))}")

    if ticker_type == "stock":
        info = result.get("info", {})
        print(f"  Market cap: {result.get('market_cap')}")
        print(f"  Name: {info.get('shortName') or info.get('longName', 'N/A')}")
        print(f"  Exchange: {info.get('exchange', 'N/A')}")
        print(f"  Currency: {info.get('currency', 'N/A')}")
    elif ticker_type == "etf":
        summary = result.get("summary", {})
        last_close = histories[-1]["close"] if histories else None
        print(f"  AUM (totalAssets): {summary.get('totalAssets', 'N/A')}")
        print(f"  Price (last close): {last_close}")
        print(f"  Volume: {summary.get('volume') or summary.get('regularMarketVolume', 'N/A')}")
        print(f"  Yield: {summary.get('yield', 'N/A')}")
        print(f"  Summary keys: {list(summary.keys())}")

    # Null check
    print(f"\n  --- Null/Zero check ---")
    _check_nulls(result, ticker_type)

    # Save to file for inspection
    out_file = f"test_result_{symbol.replace('.', '_')}.json"
    with open(out_file, "w") as f:
        json.dump(result, f, indent=2, default=str, ensure_ascii=False)
    print(f"\n  Full result saved to: {out_file}")


def _check_nulls(data, ticker_type):
    """Report null/zero/empty fields at top level."""
    skip_keys = {"histories", "dividends", "splits", "fund_holding_info",
                 "increase_stat", "year_increase_histories", "compare_to_max_in_period"}
    issues = []
    for key, val in data.items():
        if key in skip_keys:
            continue
        if val is None:
            issues.append(f"  {key}: null")
        elif val == 0 or val == 0.0:
            issues.append(f"  {key}: 0")
        elif val == "" or val == {}:
            issues.append(f"  {key}: empty")
    if issues:
        print("  [WARN] Null/zero/empty fields:")
        for issue in issues:
            print(f"    {issue}")
    else:
        print("  All top-level fields have values.")


if __name__ == "__main__":
    main()
