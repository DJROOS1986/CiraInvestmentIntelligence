"""Probe the European Central Bank's official euro reference rates (free, no key, read-only).

Fetches daily EUR/USD and EUR/CNY for a year, then prints: number of observations, the yearly average,
the last rate of the year, and the derived USD-per-CNY cross rate (via EUR). These are the rates a currency
conversion in CIRA would use: average rate for flows (revenue, income, cash flows), closing rate for balances.
Nothing is written.

Usage (repo root, .venv active):  python scripts/67-Probe-ECB-Rates.py [--year 2025]
"""
import argparse
import csv
import io

import requests

URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.{ccy}.EUR.SP00.A"


def fetch(ccy, year):
    response = requests.get(URL.format(ccy=ccy), timeout=60,
                            params={"startPeriod": f"{year}-01-01", "endPeriod": f"{year}-12-31", "format": "csvdata"})
    print(f"   {ccy}: HTTP {response.status_code}, {len(response.content)} bytes")
    response.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(response.text)))
    series = {r["TIME_PERIOD"]: float(r["OBS_VALUE"]) for r in rows if r.get("OBS_VALUE")}
    if not series:
        raise SystemExit(f"No observations for {ccy}; columns seen: {list(rows[0]) if rows else 'none'}")
    return series


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2025)
    year = parser.parse_args().year
    print(f"ECB euro reference rates, {year}")
    usd, cny = fetch("USD", year), fetch("CNY", year)
    for name, series in (("USD per EUR", usd), ("CNY per EUR", cny)):
        days = sorted(series)
        print(f"   {name:<12} {len(days)} days  {days[0]} .. {days[-1]}  average {sum(series.values()) / len(series):.4f}  last {series[days[-1]]:.4f}")
    common = sorted(set(usd) & set(cny))
    cross = {d: usd[d] / cny[d] for d in common}
    print(f"   USD per CNY  (via EUR, {len(common)} common days)  average {sum(cross.values()) / len(cross):.5f}  last {cross[common[-1]]:.5f}")


if __name__ == "__main__":
    main()
