"""Stage 2, step B: how good is EODHD's data for non-US companies? (read-only)

Reads the key ONLY from the environment variable EODHD_API_KEY and never prints it (it is also removed from
any error message). Uses about 16 API calls, so it fits even the free plan's 20 calls/day.
  1. Plan check (user endpoint): subscription type and daily limit
  2. Per company: symbol search (code, exchange, currency, ISIN)
  3. Fundamentals: reporting currency, yearly fiscal dates, years of history, the 6 CIRA fields
     (if the plan does not include fundamentals, it says so instead of failing)
  4. End-of-day prices: last date and number of trading days in the past month
Nothing is written.

Usage (repo root, .venv active, EODHD_API_KEY set):  python scripts/63-Test-EODHD-NonUS.py
"""
import os
import sys
from datetime import date, timedelta

import requests

KEY = os.environ.get("EODHD_API_KEY", "").strip()
BASE = "https://eodhd.com/api"
COMPANIES = ["Tokyo Electron", "SK hynix", "ASML Holding", "Taiwan Semiconductor Manufacturing", "Samsung Electronics"]
FIELDS = {
    "revenue": ("Income_Statement", "totalRevenue"),
    "net_income": ("Income_Statement", "netIncome"),
    "total_assets": ("Balance_Sheet", "totalAssets"),
    "total_liabilities": ("Balance_Sheet", "totalLiab"),
    "operating_cash_flow": ("Cash_Flow", "totalCashFromOperatingActivities"),
    "capital_expenditure": ("Cash_Flow", "capitalExpenditures"),
}


def safe(text):
    return str(text).replace(KEY, "***") if KEY else str(text)


def get(path, **params):
    try:
        response = requests.get(f"{BASE}/{path}", params={"api_token": KEY, "fmt": "json", **params}, timeout=60)
    except requests.RequestException as exc:
        return None, safe(exc)
    if response.status_code != 200:
        return None, f"HTTP {response.status_code}: {safe(response.text[:150])}"
    try:
        return response.json(), None
    except ValueError:
        return None, "response was not JSON"


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main():
    if not KEY:
        sys.exit("EODHD_API_KEY is not set in this PowerShell window. Set it with the hidden Read-Host command first.")

    user, error = get("user")
    print("=== Plan")
    if error:
        print(f"   user endpoint: {error}")
    else:
        print(f"   subscription: {user.get('subscriptionType')}  | daily limit: {user.get('dailyRateLimit')}  | used today: {user.get('apiRequests')}")

    since = (date.today() - timedelta(days=35)).isoformat()
    fundamentals_blocked = False
    for name in COMPANIES:
        print(f"\n=== {name}")
        found, error = get(f"search/{name}", limit=5)
        if error or not found:
            print(f"   search: {error or 'no result'}")
            continue
        stocks = [f for f in found if str(f.get("Type", "")).lower().startswith("common") and f.get("Country") != "USA"] or found
        pick = stocks[0]
        symbol = f"{pick.get('Code')}.{pick.get('Exchange')}"
        others = ", ".join(f"{f.get('Code')}.{f.get('Exchange')}" for f in found[1:4])
        print(f"   symbol {symbol}  ({pick.get('Name')}, {pick.get('Country')}, {pick.get('Currency')}, ISIN {pick.get('ISIN')})  other hits: {others or '-'}")

        if not fundamentals_blocked:
            data, error = get(f"fundamentals/{symbol}")
            if error:
                print(f"   fundamentals: {error}")
                if error.startswith(("HTTP 402", "HTTP 403")):
                    fundamentals_blocked = True
                    print("   -> fundamentals are not included in this plan; skipping them for the other companies")
            else:
                general = data.get("General") or {}
                financials = data.get("Financials") or {}
                yearly = ((financials.get("Income_Statement") or {}).get("yearly")) or {}
                dates = sorted(yearly)
                print(f"   reporting currency: {general.get('CurrencyCode')}  | fiscal year end: {general.get('FiscalYearEnd')}"
                      f"  | yearly statements: {len(dates)} ({dates[0] if dates else '-'} .. {dates[-1] if dates else '-'})")
                if dates:
                    latest = dates[-1]
                    for metric, (statement, field) in FIELDS.items():
                        row = (((financials.get(statement) or {}).get("yearly")) or {}).get(latest) or {}
                        value = number(row.get(field))
                        currency = row.get("currency_symbol") or general.get("CurrencyCode") or ""
                        shown = f"{value / 1e6:,.1f} m {currency}" if value is not None else "MISSING"
                        print(f"      {latest} {metric:<20} {shown}")

        prices, error = get(f"eod/{symbol}", **{"from": since})
        if error:
            print(f"   prices: {error}")
        elif prices:
            print(f"   prices: {len(prices)} trading days since {since}, last {prices[-1].get('date')} close {prices[-1].get('close')}"
                  f" (adjusted {prices[-1].get('adjusted_close')})")
        else:
            print("   prices: none returned")


if __name__ == "__main__":
    main()
