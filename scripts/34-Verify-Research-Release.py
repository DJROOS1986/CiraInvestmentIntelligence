"""Read-only live release verification, with optional paid AI smoke test.

Secrets are read into process memory from Terraform and never printed or saved.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import requests

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--with-ai', action='store_true')
    args = parser.parse_args()
    executable = ROOT / '.tools/terraform-1.13.5/terraform.exe'
    terraform = str(executable) if executable.exists() else 'terraform'
    output = subprocess.run([terraform, 'output', '-json'], cwd=ROOT / 'infrastructure/terraform',
                            capture_output=True, text=True, check=True)
    values = {key: entry['value'] for key, entry in json.loads(output.stdout).items()}
    response = requests.get(values['dashboard_url'] + '/_stcore/health', timeout=90)
    response.raise_for_status()
    if response.text.strip() != 'ok':
        raise ValueError('Unexpected dashboard health response')
    from streamlit.testing.v1 import AppTest
    environment = {'CIRA_STORAGE_ACCOUNT': values['storage_account_name'],
        'CIRA_DASHBOARD_ACCESS_KEY': values['dashboard_access_key'],
        'CIRA_PROJECT_ROOT': str(ROOT)}
    if args.with_ai:
        environment['CIRA_AI_ENDPOINT'] = values['research_ai_endpoint']
        environment['CIRA_AI_DEPLOYMENT'] = 'cira-research'
    original = {key: os.environ.get(key) for key in environment}
    try:
        os.environ.update(environment)
        app = AppTest.from_file(str(ROOT / 'dashboard/app.py')).run(timeout=90)
        if app.exception or app.metric:
            raise RuntimeError('Unauthenticated dashboard gate failed')
        app.sidebar.text_input[0].set_value(values['dashboard_access_key']).run(timeout=90)
        if app.exception or app.error or len(app.metric) != 4:
            raise RuntimeError('Authenticated company research view failed')
        result = {'dashboard_https_health': 'PASS', 'access_gate': 'PASS', 'cloud_research_view': 'PASS'}
        if args.with_ai:
            next(button for button in app.button if button.label == 'Select research highlights').click().run(timeout=90)
            if app.exception or app.error or len(app.dataframe) < 2:
                raise RuntimeError('Grounded AI highlight smoke test failed')
            result['grounded_ai'] = 'PASS'
        app.sidebar.radio[0].set_value('Portfolio lab').run(timeout=30)
        app.number_input[0].set_value(1.0).run(timeout=30)
        if app.exception or app.error or len(app.metric) != 3:
            raise RuntimeError('Portfolio view failed')
        result['portfolio_view'] = 'PASS'
        app.sidebar.radio[0].set_value('Data quality').run(timeout=30)
        if app.exception or app.error or len(app.dataframe) != 1:
            raise RuntimeError('Data quality view failed')
        result['quality_view'] = 'PASS'
        print(json.dumps(result, indent=2))
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Release verification failed ({type(exc).__name__}). No secrets logged.', file=sys.stderr)
        raise SystemExit(1)
