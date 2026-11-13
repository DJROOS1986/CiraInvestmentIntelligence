import csv
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALID = {"SEC_10K", "SEC_20F", "PROVIDER", "PARKED"}


class IdentifierMasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = list(csv.DictReader((ROOT / "config" / "identifiers.csv").open(encoding="utf-8")))
        cls.universe = json.loads((ROOT / "config" / "universe.json").read_text(encoding="utf-8"))["companies"]
        bcg = json.loads((ROOT / "ingestion" / "bcg-research" / "bcg_research.json").read_text(encoding="utf-8"))
        cls.bcg_names = [c["company"] for c in bcg["companies"]]

    def test_every_bcg_company_has_exactly_one_row(self):
        self.assertEqual(sorted(r["bcg_name"] for r in self.rows), sorted(self.bcg_names))

    def test_categories_valid(self):
        for r in self.rows:
            self.assertIn(r["category"], VALID, r["bcg_name"])

    def test_sec_rows_have_ticker_and_ten_digit_cik(self):
        for r in self.rows:
            if r["category"] in ("SEC_10K", "SEC_20F"):
                self.assertTrue(r["primary_ticker"], r["bcg_name"])
                self.assertRegex(r["sec_cik"], r"^\d{10}$", r["bcg_name"])

    def test_one_cik_per_entity(self):
        seen = {}
        for r in self.rows:
            if r["sec_cik"]:
                self.assertEqual(seen.setdefault(r["sec_cik"], r["entity"]), r["entity"], r["bcg_name"])

    def test_universe_companies_agree_with_identifier_master(self):
        by_ticker = {r["primary_ticker"]: r for r in self.rows if r["category"] in ("SEC_10K", "SEC_20F")}
        for c in self.universe:
            if c["bcg_required"]:
                self.assertIn(c["ticker"], by_ticker, c["ticker"])
                self.assertEqual(by_ticker[c["ticker"]]["sec_cik"], c["cik"], c["ticker"])
                self.assertEqual(by_ticker[c["ticker"]]["in_universe"], "yes", c["ticker"])


if __name__ == "__main__":
    unittest.main()
