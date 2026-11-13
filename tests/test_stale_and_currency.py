import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
stage07 = runpy.run_path(str(ROOT / "scripts" / "07-Generate-Financial-Reports.py"))


def test_stale_financials_rejected():
    with pytest.raises(ValueError, match="Stale financials"):
        stage07["_check_fresh"]({"period_end": "2020-12-31"})


def test_recent_financials_accepted():
    stage07["_check_fresh"]({"period_end": "2026-06-30"})


def test_known_non_usd_reporters_have_their_currency():
    currencies = {c["ticker"]: c.get("reporting_currency", "USD")
                  for c in json.loads((ROOT / "config" / "universe.json").read_text(encoding="utf-8"))["companies"]}
    expected = {"ASML": "EUR", "BABA": "CNY", "TCOM": "CNY", "HSAI": "CNY", "YMM": "CNY", "XPEV": "CNY"}
    assert {t: currencies.get(t) for t in expected} == expected


def test_verification_script_keeps_price_currency_separate():
    text = (ROOT / "scripts" / "52-Verify-Universe-Batch.py").read_text(encoding="utf-8")
    assert "price_currency = result_chart" in text and "currency = result_chart" not in text.replace("price_currency = result_chart", "")
