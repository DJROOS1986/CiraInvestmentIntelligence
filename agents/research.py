"""Grounded AI highlight selection: the model cannot supply facts or trading advice."""
import json
import math
from urllib.parse import urlparse, quote

import requests


def source_facts(report):
    facts = {}
    for section, fields in (
        ('financial', report['financial']['metrics_usd']),
        ('market', report['market']['indicators']),
    ):
        for key, value in fields.items():
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                continue
            facts[f'{section}.{key}'] = {'label': key.replace('_', ' ').title(), 'value': value,
                'source': 'SEC financial report' if section == 'financial' else 'Historical market prices',
                'date': report['financial']['period_end'] if section == 'financial' else report['market']['last_date']}
    return facts


def render_selection(content, facts):
    document = json.loads(content)
    if not isinstance(document, dict) or set(document) != {'highlights'}:
        raise ValueError('Unexpected AI response fields')
    selected = document['highlights']
    if not isinstance(selected, list) or not 1 <= len(selected) <= 5:
        raise ValueError('AI must select one to five source facts')
    if any(not isinstance(key, str) or key not in facts for key in selected) or len(set(selected)) != len(selected):
        raise ValueError('AI selected unknown or duplicate facts')
    return [{'field': key, **facts[key]} for key in selected]


def select_highlights(report, endpoint, deployment, credential, session=requests):
    parsed = urlparse(endpoint)
    if parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.openai.azure.com') or parsed.username or parsed.query:
        raise ValueError('Expected an Azure OpenAI HTTPS endpoint')
    facts = source_facts(report)
    if not facts:
        raise ValueError('No verified numerical facts available')
    token = credential.get_token('https://cognitiveservices.azure.com/.default').token
    url = endpoint.rstrip('/') + '/openai/deployments/' + quote(deployment, safe='') + '/chat/completions?api-version=2024-10-21'
    schema = {'type': 'object', 'properties': {'highlights': {'type': 'array',
        'items': {'type': 'string', 'enum': list(facts)}}}, 'required': ['highlights'], 'additionalProperties': False}
    response = session.post(url, headers={'Authorization': f'Bearer {token}'}, timeout=45, json={
        'messages': [
            {'role': 'system', 'content': 'Select up to five useful descriptive research fields from the provided source facts. Return JSON with highlights containing only field identifiers. Do not provide advice, forecasts, invented facts, or trade instructions.'},
            {'role': 'user', 'content': json.dumps({'ticker': report['ticker'], 'facts': facts}, allow_nan=False)},
        ],
        'max_completion_tokens': 1024,
        'response_format': {'type': 'json_schema', 'json_schema': {'name': 'research_highlights', 'strict': True, 'schema': schema}},
    })
    response.raise_for_status()
    choice = response.json()['choices'][0]
    if choice.get('finish_reason') != 'stop' or choice['message'].get('refusal'):
        raise ValueError('AI response refused or incomplete')
    return render_selection(choice['message']['content'], facts)
