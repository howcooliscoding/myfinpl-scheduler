from typing import List, Optional
from datetime import datetime


def calc_cagr(start_value: float, end_value: float, period: int):
    if start_value <= 0 or end_value <= 0:
        return None
    return round(((end_value / start_value) ** (1 / period) - 1) * 100, 2)


def calc_increase_rate(start_value: float, end_value: float):
    if start_value <= 0 or end_value <= 0:
        return None
    return round((end_value - start_value) / start_value * 100, 2)


def mdd_histories(histories: List[dict]) -> List[dict]:
    max_price = 0
    result = []
    for record in histories:
        adj_close = record.get("adjClose")
        if adj_close is None or adj_close <= 0:
            continue
        if max_price < adj_close:
            max_price = adj_close
        mdd = (adj_close - max_price) / max_price * 100
        ts = int(datetime.strptime(record["date"], "%Y-%m-%d").timestamp() * 1000)
        result.append({"date": record["date"], "timestamp": ts, "mdd": mdd})
    return result


def year_increase_rate(histories: List[dict]) -> List[dict]:
    yearly = {}
    for record in histories:
        adj_close = record.get("adjClose")
        if adj_close is None or adj_close <= 0:
            continue
        year = record["date"][:4]
        if year not in yearly:
            yearly[year] = {"first": record, "max": record, "min": record}
        yearly[year]["last"] = record
        if yearly[year]["max"]["adjClose"] < adj_close:
            yearly[year]["max"] = record
        if yearly[year]["min"]["adjClose"] > adj_close:
            yearly[year]["min"] = record

    result = []
    for year, data in yearly.items():
        open_val = data["first"].get("open", data["first"]["adjClose"])
        if open_val <= 0:
            continue
        rate = (data["last"]["adjClose"] / open_val - 1) * 100
        ts = int(datetime.strptime(f"{year}-01-01", "%Y-%m-%d").timestamp() * 1000)
        result.append({"year": year, "timestamp": ts, "intrease_rate": rate})
    return result
