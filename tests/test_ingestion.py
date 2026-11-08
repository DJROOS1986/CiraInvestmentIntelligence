import pathlib
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'ingestion'))
import ingest_sec

class IngestionTests(unittest.TestCase):
    def test_bad_cik(self):
        with self.assertRaises(ValueError):
            ingest_sec.fetch_companyfacts('bad', 'Cira user@domain.com')
    def test_placeholder_contact_rejected(self):
        with self.assertRaises(ValueError):
            ingest_sec.load_config(pathlib.Path(__file__).resolve().parents[1] / 'ingestion' / 'config.example.json')

if __name__ == '__main__':
    unittest.main()
