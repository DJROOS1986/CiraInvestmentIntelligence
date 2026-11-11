import importlib.util
import json
import unittest
from pathlib import Path

import requests

_SPEC = importlib.util.spec_from_file_location(
    "cira_research_agent", Path(__file__).resolve().parents[1] / "agents" / "research.py"
)
research = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(research)

REPORT = {
    "ticker": "TEST",
    "financial": {"period_end": "2026-09-26", "metrics_usd": {"revenue": 100, "net_income": 10}},
    "market": {"last_date": "2026-11-11", "indicators": {"latest_close": 12.5}},
}
OK_BODY = {"choices": [{"finish_reason": "stop", "message": {
    "content": json.dumps({"highlights": ["financial.revenue", "market.latest_close"]})}}]}


class FakeResponse:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def post(self, *args, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


class FakeToken:
    token = "not-a-real-token"


class FakeCredential:
    def get_token(self, scope):
        return FakeToken()


ENDPOINT = "https://example.openai.azure.com/"


class ResilienceTests(unittest.TestCase):
    def run_select(self, responses):
        waits = []
        session = FakeSession(responses)
        result = research.select_highlights(REPORT, ENDPOINT, "dep", FakeCredential(), session=session, sleep=waits.append)
        return result, session, waits

    def test_success_without_retry(self):
        result, session, waits = self.run_select([FakeResponse(200, OK_BODY)])
        self.assertEqual([r["field"] for r in result], ["financial.revenue", "market.latest_close"])
        self.assertEqual((session.calls, waits), (1, []))

    def test_single_retry_after_429_uses_retry_after_ms(self):
        result, session, waits = self.run_select([FakeResponse(429, headers={"retry-after-ms": "3000"}), FakeResponse(200, OK_BODY)])
        self.assertEqual(session.calls, 2)
        self.assertEqual(waits, [3.0])
        self.assertEqual(len(result), 2)

    def test_second_429_raises_rate_limit_error(self):
        with self.assertRaises(requests.HTTPError) as ctx:
            self.run_select([FakeResponse(429), FakeResponse(429)])
        self.assertEqual(research.describe_failure(ctx.exception), "AI rate limit reached - try again in a minute")

    def test_wait_is_clamped(self):
        self.assertEqual(research.retry_wait_seconds(FakeResponse(429, headers={"retry-after": "600"})), 20.0)
        self.assertEqual(research.retry_wait_seconds(FakeResponse(429, headers={"retry-after": "0"})), 1.0)
        self.assertEqual(research.retry_wait_seconds(FakeResponse(429, headers={"retry-after": "junk"})), 10.0)
        self.assertEqual(research.retry_wait_seconds(FakeResponse(429)), 10.0)

    def test_describe_failure_messages(self):
        self.assertEqual(research.describe_failure(requests.HTTPError("x", response=FakeResponse(403))),
                         "AI access denied for the dashboard identity")
        self.assertEqual(research.describe_failure(requests.HTTPError("x", response=FakeResponse(500))),
                         "AI service returned HTTP 500")
        self.assertEqual(research.describe_failure(requests.ConnectTimeout()), "AI service timed out")
        self.assertEqual(research.describe_failure(requests.ConnectionError()), "AI service unreachable")
        self.assertEqual(research.describe_failure(ValueError("AI must select one to five source facts")),
                         "AI response rejected: AI must select one to five source facts")
        self.assertEqual(research.describe_failure(KeyError("x")), "unexpected error (KeyError)")


if __name__ == "__main__":
    unittest.main()
