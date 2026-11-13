"""USD conversion for financial statements reported in other currencies (EUR, CNY, ...).

Source: European Central Bank euro foreign exchange reference rates (official, free, daily on working days).
USD per EUR comes directly from the ECB; other currencies are crossed via EUR (USD/EUR divided by CCY/EUR).
Flows (revenue, income, cash flows) use the average rate over the fiscal period; balances (assets,
liabilities) use the last rate on or before the balance-sheet date. Rates are cached per run.
"""
import csv
import io
from datetime import date, timedelta

import requests

SOURCE = "ECB euro foreign exchange reference rates"
URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.{ccy}.EUR.SP00.A"


def _download(ccy, start, end):
    response = requests.get(URL.format(ccy=ccy), timeout=60,
                            params={"startPeriod": start, "endPeriod": end, "format": "csvdata"})
    response.raise_for_status()
    rows = csv.DictReader(io.StringIO(response.text))
    return {r["TIME_PERIOD"]: float(r["OBS_VALUE"]) for r in rows if r.get("OBS_VALUE")}


class EcbRates:
    source = SOURCE

    def __init__(self, fetch=None):
        self._fetch = fetch or _download
        self._cache = {}

    def _series(self, ccy, start, end):
        key = (ccy, start, end)
        if key not in self._cache:
            self._cache[key] = self._fetch(ccy, start, end)
        return self._cache[key]

    def _usd_per(self, ccy, start, end):
        usd = self._series("USD", start, end)
        if ccy == "EUR":
            return dict(usd)
        other = self._series(ccy, start, end)
        return {d: usd[d] / other[d] for d in usd if d in other and other[d]}

    def average(self, ccy, start, end):
        series = self._usd_per(ccy, start, end)
        if not series:
            raise ValueError(f"ECB rates unavailable for {ccy} {start}..{end}")
        return sum(series.values()) / len(series)

    def closing(self, ccy, on):
        start = (date.fromisoformat(on) - timedelta(days=10)).isoformat()
        series = self._usd_per(ccy, start, on)
        if not series:
            raise ValueError(f"ECB closing rate unavailable for {ccy} on {on}")
        return series[max(series)]
