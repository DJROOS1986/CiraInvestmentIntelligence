import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "cira_dashboard_access", Path(__file__).resolve().parents[1] / "dashboard" / "access.py"
)
access = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(access)

ALLOWED = "11111111-2222-3333-4444-555555555555"


class EntraAccessTests(unittest.TestCase):
    def test_matching_principal_is_allowed(self):
        self.assertTrue(access.entra_allowed({"X-Ms-Client-Principal-Id": ALLOWED}, ALLOWED))

    def test_match_is_case_insensitive_on_value(self):
        self.assertTrue(access.entra_allowed({"X-Ms-Client-Principal-Id": ALLOWED.upper()}, ALLOWED))

    def test_lowercase_header_name_is_read(self):
        self.assertTrue(access.entra_allowed({"x-ms-client-principal-id": ALLOWED}, ALLOWED))

    def test_other_principal_is_rejected(self):
        self.assertFalse(access.entra_allowed({"X-Ms-Client-Principal-Id": "99999999-0000-0000-0000-000000000000"}, ALLOWED))

    def test_missing_header_is_rejected(self):
        self.assertFalse(access.entra_allowed({}, ALLOWED))

    def test_no_headers_object_is_rejected(self):
        self.assertFalse(access.entra_allowed(None, ALLOWED))

    def test_unconfigured_allowed_id_rejects_everyone(self):
        self.assertFalse(access.entra_allowed({"X-Ms-Client-Principal-Id": ALLOWED}, ""))
        self.assertFalse(access.entra_allowed({"X-Ms-Client-Principal-Id": ALLOWED}, None))

    def test_non_ascii_value_is_rejected_not_crashing(self):
        self.assertFalse(access.entra_allowed({"X-Ms-Client-Principal-Id": "1111\u00e9"}, ALLOWED))


if __name__ == "__main__":
    unittest.main()
