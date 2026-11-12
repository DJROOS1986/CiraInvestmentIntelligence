import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('research_agent_test', ROOT / 'agents/research.py')
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


@pytest.fixture
def report():
    return {'ticker': 'AAPL', 'financial': {'period_end': '2026-06-30', 'metrics_usd': {'revenue': 123, 'net_income': None}},
            'market': {'last_date': '2026-11-09', 'indicators': {'latest_close': 10}}}


def test_rendered_facts_are_original_values(report):
    result = agent.render_selection('{"highlights":["financial.revenue"]}', agent.source_facts(report))
    assert result[0]['value'] == 123
    assert result[0]['date'] == '2026-06-30'


@pytest.mark.parametrize('response', [
    '{"highlights":["BUY"]}', '{"highlights":[]}',
    '{"highlights":["financial.revenue"],"advice":"buy now"}',
    '{"highlights":["financial.revenue","financial.revenue"]}',
    '{"highlights":[123]}', 'not json',
])
def test_untrusted_model_fields_rejected(report, response):
    with pytest.raises(ValueError):
        agent.render_selection(response, agent.source_facts(report))


def test_managed_identity_request_and_bounded_output(report):
    class Session:
        def post(self, url, headers, timeout, json):
            assert url.startswith('https://cira.openai.azure.com/openai/deployments/research/')
            assert headers['Authorization'] == 'Bearer test-token'
            assert timeout == 45
            assert json['max_completion_tokens'] == 1024
            assert json['response_format']['json_schema']['strict'] is True
            return SimpleNamespace(raise_for_status=lambda: None,
                json=lambda: {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"highlights":["market.latest_close"]}'}}]})
    credential = SimpleNamespace(get_token=lambda scope: SimpleNamespace(token='test-token'))
    selected = agent.select_highlights(report, 'https://cira.openai.azure.com', 'research', credential, Session())
    assert selected[0]['value'] == 10


def test_ai_endpoint_rejected_before_credentials(report):
    with pytest.raises(ValueError, match='HTTPS'):
        agent.select_highlights(report, 'http://attacker.example', 'research', None)


def test_hosted_dashboard_denies_without_entra(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('CIRA_STORAGE_ACCOUNT', 'account')
    monkeypatch.setenv('CIRA_ALLOWED_PRINCIPAL_ID', '00000000-0000-0000-0000-000000000001')
    monkeypatch.setenv('CIRA_DASHBOARD_ACCESS_KEY', 'test-key')  # a leftover key must not open anything
    app = AppTest.from_file(str(ROOT / 'dashboard/app.py')).run(timeout=20)
    assert not app.exception
    assert not app.metric
    assert not app.sidebar.text_input
    assert 'Access denied' in app.error[0].value
