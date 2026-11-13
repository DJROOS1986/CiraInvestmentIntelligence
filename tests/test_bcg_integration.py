import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "portfolio-engine" / "bcg_integration.py"

spec = importlib.util.spec_from_file_location(
    "bcg_integration", MODULE
)
bcg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bcg)


class TestBCGIntegration(unittest.TestCase):

    def setUp(self):
        self.data = {
            "companies": [
                {
                    "company": "Microsoft",
                    "html_class": "Unclassified",
                    "rule_based_class": "Unclassified",
                    "evidence_status": "Unclassified",
                    "star_score": 74,
                    "market_growth_pct": 43,
                    "relative_share_x": None,
                }
            ]
        }

    def test_microsoft_match(self):
        result = bcg.integrate_bcg("MSFT", self.data)
        self.assertEqual(result["company"], "Microsoft")

    def test_apple_missing(self):
        result = bcg.integrate_bcg("AAPL", self.data)
        self.assertFalse(result["research_available"])

    def test_unclassified_not_verified(self):
        result = bcg.integrate_bcg("MSFT", self.data)
        self.assertIsNone(result["verified_bcg_class"])

    def test_no_investment_recommendation(self):
        result = bcg.integrate_bcg("MSFT", self.data)
        self.assertIsNone(result["investment_recommendation"])

    def test_verified_source_class(self):
        data = {
            "companies": [{
                "company": "Microsoft",
                "html_class": "Star",
                "rule_based_class": "Star",
                "evidence_status": "Classified",
                "relative_share_x": 1.5,
            }]
        }
        result = bcg.integrate_bcg("MSFT", data)
        self.assertEqual(result["verified_bcg_class"], "Star")
        self.assertEqual(
            result["status"],
            "Evidence-classified (source-reported)"
        )

    def test_invalid_database(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(
                json.dumps({"companies": "invalid"}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                bcg.load_bcg_database(path)


if __name__ == "__main__":
    unittest.main()

def test_workbook_provenance_is_not_official_bcg_verification():
    doc = {'dataset': 'CIRA BCG research import', 'source_file': 'user-workbook.xlsx',
        'source_summary_date': '2026-10-28', 'imported_on': '2026-11-08',
        'companies': [{'company': 'Microsoft', 'html_class': 'Star', 'rule_based_class': 'Star',
                       'evidence_status': 'Classified', 'relative_share_x': 2}]}
    result = bcg.integrate_bcg('MSFT', doc)
    assert result['provenance']['source_summary_date'] == '2026-10-28'
    assert result['classification_origin'] == 'user-supplied research'
    assert result['independently_verified'] is False
    assert 'No independent evidence' in result['verification_note']
    missing = bcg.integrate_bcg('AAPL', doc)
    assert missing['classification_origin'] == 'unavailable'
