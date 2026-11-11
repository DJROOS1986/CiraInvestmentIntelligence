import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UniverseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.universe = json.loads((ROOT / "config" / "universe.json").read_text(encoding="utf-8"))
        cls.companies = cls.universe["companies"]
        bcg = json.loads((ROOT / "ingestion" / "bcg-research" / "bcg_research.json").read_text(encoding="utf-8"))
        cls.bcg_names = {c.get("company") for c in bcg["companies"]}

    def test_schema_version(self):
        self.assertEqual(self.universe["schema_version"], "1.0")

    def test_tickers_unique_and_wellformed(self):
        tickers = [c["ticker"] for c in self.companies]
        self.assertEqual(len(tickers), len(set(tickers)))
        for t in tickers:
            self.assertRegex(t, r"^[A-Z]{1,5}$")

    def test_ciks_are_ten_digits_and_unique(self):
        ciks = [c["cik"] for c in self.companies]
        self.assertEqual(len(ciks), len(set(ciks)))
        for cik in ciks:
            self.assertRegex(cik, r"^\d{10}$")

    def test_only_10k_filers_in_stage_one(self):
        for c in self.companies:
            self.assertEqual(c["annual_form"], "10-K", c["ticker"])

    def test_required_bcg_names_exist(self):
        for c in self.companies:
            if c["bcg_required"]:
                self.assertIn(c["bcg_name"], self.bcg_names, c["ticker"])

    def test_notes_are_lists_of_text(self):
        for c in self.companies:
            self.assertIsInstance(c["notes"], list)
            self.assertTrue(all(isinstance(n, str) and n for n in c["notes"]))

    def test_no_hardcoded_ticker_lists_remain(self):
        pattern = re.compile(r"""[\(\[\{]\s*['"]AAPL['"]\s*,\s*['"]MSFT['"]""")
        files = [ROOT / "dashboard" / "data.py", ROOT / "portfolio-engine" / "company_intelligence.py",
                 *[ROOT / "scripts" / n for n in ("07-Generate-Financial-Reports.py", "10-Analyze-Financial-Reports.py",
                   "13-Ingest-Market-Prices.py", "14-Analyze-Market-Prices.py", "15-Build-Company-Intelligence.py",
                   "16-Refresh-Company-Intelligence.py", "20-Publish-Versioned-Reports.py")]]
        for f in files:
            self.assertIsNone(pattern.search(f.read_text(encoding="utf-8")), f.name)


if __name__ == "__main__":
    unittest.main()
