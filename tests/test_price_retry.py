import importlib.util
import sys
import time
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def stage13(monkeypatch, tmp_path):
    monkeypatch.setenv("CIRA_RUN_STATE", str(tmp_path / "run-exclusions.json"))
    monkeypatch.syspath_prepend(str(ROOT / "ingestion"))
    spec = importlib.util.spec_from_file_location("cira_stage13", ROOT / "scripts" / "13-Ingest-Market-Prices.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    waits = []
    monkeypatch.setattr(time, "sleep", waits.append)
    module.waits = waits
    return module


def refusing(times, result):
    calls = {"n": 0}

    def fetch(symbol):
        calls["n"] += 1
        if calls["n"] <= times:
            raise requests.HTTPError("400 Client Error: Bad Request")
        return result
    fetch.calls = calls
    return fetch


def test_success_after_two_refusals(stage13, monkeypatch):
    fetch = refusing(2, [{"date": "2026-11-12", "close": 1.0}])
    monkeypatch.setattr(stage13, "fetch_prices", fetch)
    assert stage13.fetch_with_retry("CDNS") == [{"date": "2026-11-12", "close": 1.0}]
    assert fetch.calls["n"] == 3
    assert stage13.waits == [3, 8]


def test_gives_up_after_three_attempts(stage13, monkeypatch):
    fetch = refusing(5, [])
    monkeypatch.setattr(stage13, "fetch_prices", fetch)
    with pytest.raises(requests.HTTPError):
        stage13.fetch_with_retry("TER")
    assert fetch.calls["n"] == 3


def test_no_retry_for_missing_data(stage13, monkeypatch):
    calls = {"n": 0}

    def fetch(symbol):
        calls["n"] += 1
        raise RuntimeError("No market data")
    monkeypatch.setattr(stage13, "fetch_prices", fetch)
    with pytest.raises(RuntimeError):
        stage13.fetch_with_retry("ZZZ")
    assert calls["n"] == 1 and stage13.waits == []


def test_existing_endpoint_requests_year_without_live_call(stage13, monkeypatch):
    captured = {}
    payload = {'chart': {'result': [{'meta': {'symbol': 'TEST', 'currency': 'USD'},
        'timestamp': [1767272400], 'indicators': {'quote': [{'open': [100], 'high': [101],
        'low': [99], 'close': [100], 'volume': [1]}]}}]}}
    class Response:
        def raise_for_status(self):
            pass
        def iter_content(self, chunk_size):
            yield __import__('json').dumps(payload).encode('utf-8')
        def close(self):
            pass
    def get(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()
    monkeypatch.setattr(stage13.requests, 'get', get)
    result = stage13.fetch_prices('TEST')
    assert captured['url'] == 'https://query1.finance.yahoo.com/v8/finance/chart/TEST'
    assert captured['params'] == {'range': '1y', 'interval': '1d'}
    assert result['currency'] == 'USD' and result['source_metadata']['requested_range'] == '1y'


class StreamedChartResponse:
    def __init__(self, body, error=None):
        self.body = body
        self.error = error
        self.closed = False
        self.chunks_read = 0

    def raise_for_status(self):
        if self.error:
            raise self.error

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.body), chunk_size):
            self.chunks_read += 1
            yield self.body[offset:offset + chunk_size]

    def close(self):
        self.closed = True

    def json(self):
        raise AssertionError('Unbounded response.json() must not be used')


@pytest.mark.parametrize('extra_bytes', [0, 1])
def test_streamed_body_limit_boundary_and_close(stage13, monkeypatch, extra_bytes):
    limit = stage13.MAX_CHART_RESPONSE_BYTES
    assert limit == 2 * 1024 * 1024
    response = StreamedChartResponse(b'{}' + b' ' * (limit - 2 + extra_bytes))
    def get(url, **kwargs):
        assert kwargs['stream'] is True and kwargs['timeout'] == 20
        return response
    monkeypatch.setattr(stage13.requests, 'get', get)
    parsed = []
    monkeypatch.setattr(stage13, 'normalize_yahoo_chart', lambda symbol, payload: parsed.append(payload) or {'symbol': symbol})
    if extra_bytes:
        with pytest.raises(ValueError, match='byte limit'):
            stage13.fetch_prices('TEST')
        assert not parsed
    if not extra_bytes:
        assert stage13.fetch_prices('TEST') == {'symbol': 'TEST'}
        assert parsed == [{}]
    assert response.closed
    assert response.chunks_read <= limit // (64 * 1024) + 1


def test_stream_stops_immediately_on_oversized_chunk(stage13, monkeypatch):
    response = StreamedChartResponse(b'')
    def chunks(chunk_size):
        yield b' ' * (stage13.MAX_CHART_RESPONSE_BYTES + 1)
        raise AssertionError('Must stop reading after the limit is exceeded')
    response.iter_content = chunks
    monkeypatch.setattr(stage13.requests, 'get', lambda *a, **k: response)
    with pytest.raises(ValueError, match='byte limit'):
        stage13.fetch_prices('TEST')
    assert response.closed


def test_stream_closes_on_http_and_json_errors(stage13, monkeypatch):
    response = StreamedChartResponse(b'', requests.HTTPError('synthetic 500'))
    monkeypatch.setattr(stage13.requests, 'get', lambda *a, **k: response)
    with pytest.raises(requests.HTTPError):
        stage13.fetch_prices('TEST')
    assert response.closed and response.chunks_read == 0
    response = StreamedChartResponse(b'invalid json')
    with pytest.raises(ValueError):
        stage13.fetch_prices('TEST')
    assert response.closed


@pytest.mark.parametrize('invalid_required', [False, True])
def test_malformed_company_response_does_not_abort_other_companies(stage13, monkeypatch, tmp_path, invalid_required):
    import json
    monkeypatch.setattr(stage13, 'SYMBOLS', ['BAD', 'GOOD'])
    monkeypatch.setattr(stage13, 'OUTPUT', tmp_path / 'prices')
    responses = []
    def get(url, **kwargs):
        symbol = url.rsplit('/', 1)[-1]
        quote = {'open': [100], 'high': [101], 'low': [99], 'close': [100], 'volume': [1]}
        entry = {'meta': {'symbol': symbol, 'currency': 'USD'}, 'timestamp': [1767272400],
                 'indicators': {'quote': [quote]}}
        if symbol == 'BAD':
            entry['indicators']['adjclose'] = [None]
            if invalid_required:
                entry['indicators']['quote'] = [None]
        response = StreamedChartResponse(json.dumps({'chart': {'result': [entry]}}).encode())
        responses.append(response)
        return response
    monkeypatch.setattr(stage13.requests, 'get', get)
    assert stage13.main() == 0
    assert (stage13.OUTPUT / 'GOOD-daily-prices.json').is_file()
    state = tmp_path / 'run-exclusions.json'
    if invalid_required:
        assert 'BAD' in json.loads(state.read_text())
        assert not (stage13.OUTPUT / 'BAD-daily-prices.json').exists()
    if not invalid_required:
        assert not state.exists()
        bad = json.loads((stage13.OUTPUT / 'BAD-daily-prices.json').read_text())
        assert any('Malformed optional' in w for w in bad['quality_warnings'])
    assert len(responses) == 2 and all(response.closed for response in responses)


@pytest.mark.parametrize('body', [b'[' * 2000 + b']' * 2000, b'\xff'])
def test_unsupported_json_depth_or_encoding_is_a_controlled_failure(stage13, monkeypatch, body):
    response = StreamedChartResponse(body)
    monkeypatch.setattr(stage13.requests, 'get', lambda *a, **k: response)
    if body.startswith(b'['):
        # Decoder recursion thresholds differ across Python builds/platforms.
        # Exercise this exception handler explicitly instead of assuming a limit.
        def reject_depth(payload):
            raise RecursionError('synthetic decoder depth limit')
        monkeypatch.setattr(stage13.json, 'loads', reject_depth)
    with pytest.raises(ValueError, match='JSON structure or encoding'):
        stage13.fetch_prices('TEST')
    assert response.closed


def test_real_nested_chart_response_is_rejected_on_every_platform(stage13, monkeypatch):
    response = StreamedChartResponse(b'[' * 2000 + b']' * 2000)
    monkeypatch.setattr(stage13.requests, 'get', lambda *a, **k: response)
    with pytest.raises(ValueError):
        stage13.fetch_prices('TEST')
    assert response.closed


def test_streamed_json_errors_preserve_bounded_request_retries(stage13, monkeypatch):
    responses = []
    def get(*args, **kwargs):
        response = StreamedChartResponse(b'invalid json')
        responses.append(response)
        return response
    monkeypatch.setattr(stage13.requests, 'get', get)
    with pytest.raises(requests.exceptions.JSONDecodeError):
        stage13.fetch_with_retry('TEST')
    assert len(responses) == 3 and all(response.closed for response in responses)
    assert stage13.waits == [3, 8]
