"""CIRA read-only investment research dashboard."""
import importlib.util
import hmac
import os
from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from data import TICKERS, freshness, load_azure, load_local
from access import entra_allowed

st.set_page_config(page_title='CIRA | Research workspace', page_icon='◈', layout='wide')
st.markdown('''<style>
.stApp {background:#0b1422;color:#e5eaf2}
[data-testid="stSidebar"] {background:#111f30}
[data-testid="stMetric"] {background:#152338;border:1px solid #26374d;border-radius:12px;padding:18px}
h1,h2,h3 {letter-spacing:-.025em} .stCaption {color:#9cacc2}
</style>''', unsafe_allow_html=True)


@st.cache_data(ttl=60)
def dataset():
    account = os.environ.get('CIRA_STORAGE_ACCOUNT')
    if account:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient
        with DefaultAzureCredential() as credential:
            with BlobServiceClient(f'https://{account}.blob.core.windows.net', credential=credential) as service:
                return load_azure(service.get_container_client(os.environ.get('CIRA_REPORTS_CONTAINER', 'reports')))
    return load_local(Path(os.environ.get('CIRA_PROJECT_ROOT', ROOT)))


st.sidebar.title('◈ CIRA')
st.sidebar.caption('INVESTMENT INTELLIGENCE')
view = st.sidebar.radio('Workspace', ['Company research', 'Portfolio lab', 'Data quality'])
st.sidebar.divider()
st.sidebar.caption('Research only. Orders and broker access are not available. Every investment decision requires your review.')
if st.sidebar.button('Refresh reports'):
    dataset.clear()
    st.rerun()

st.caption(f'RESEARCH WORKSPACE / {len(TICKERS)} COMPANIES')
st.title(view)
st.write('Financial fundamentals, historical market context, and transparent data quality.')
required_key = os.environ.get('CIRA_DASHBOARD_ACCESS_KEY')
try:
    request_headers = st.context.headers
except Exception:
    request_headers = {}
entra_ok = entra_allowed(request_headers, os.environ.get('CIRA_ALLOWED_PRINCIPAL_ID'))
if entra_ok:
    st.sidebar.caption('Signed in with Microsoft Entra ID')
if required_key and not entra_ok:
    supplied = st.sidebar.text_input('Access key', type='password')
    if not hmac.compare_digest(supplied, required_key):
        st.info('Enter your dashboard access key to open the research workspace.')
        st.stop()
if os.environ.get('CIRA_STORAGE_ACCOUNT') and not required_key and not entra_ok:
    st.error('Dashboard access protection is not configured.')
    st.stop()
try:
    data = dataset()
except Exception:
    st.error('A complete research batch is not available. Verify the pipeline output and storage access, then refresh.')
    st.stop()
st.caption(f"{data['source']} · Batch {data['batch_id']}")
if data.get('excluded'):
    st.warning('Not in this batch: ' + '; '.join(f"{t} ({v.get('stage')}: {v.get('reason')})" for t, v in data['excluded'].items()))

if view == 'Company research':
    ticker = st.selectbox('Company', list(data['companies']))
    report = data['companies'][ticker]
    status = freshness(report)
    if status != 'Within freshness window':
        st.warning(status)
    st.subheader(report.get('company') or ticker)
    st.caption(f"Financial period: {report['financial']['period_end']} · Market date: {report['market']['last_date']} · Generated: {report['generated_at_utc']}")
    metrics = report['financial']['metrics_usd']
    indicators = report['market']['indicators']
    columns = st.columns(4)
    for column, label, value, unit in zip(columns,
            ['Revenue', 'Net income', 'Free cash flow', 'Latest close'],
            [metrics.get('revenue'), metrics.get('net_income'), metrics.get('free_cash_flow'), indicators.get('latest_close')],
            ['B', 'B', 'B', '']):
        display = 'Unavailable'
        if value is not None:
            display = f'${value / 1e9:,.2f}B' if unit else f'${value:,.2f}'
        column.metric(label, display)
    history = pd.DataFrame(data['prices'][ticker]['records'])
    st.subheader('Historical closing prices')
    st.line_chart(history.set_index('date')['close'], color='#5eead4')
    st.caption('USD · Unadjusted historical prices; returns may exclude dividends and corporate-action adjustments.')
    st.subheader('Market context')
    st.dataframe(pd.DataFrame([{'Metric': key.replace('_', ' ').title(), 'Value': value} for key, value in indicators.items()]), hide_index=True)
    with st.expander('Sources and research limitations', expanded=True):
        st.write(f"Financial source: {report['financial']['source']}")
        st.write(f"Market source: {report['market']['provider']}")
        for warning in report['data_quality']['warnings']:
            st.write('• ' + warning)
    if os.environ.get('CIRA_AI_ENDPOINT'):
        st.subheader('AI-selected research highlights')
        st.caption('The model selects existing facts; values and source dates come directly from this report. No recommendation is generated.')
        if st.button('Select research highlights'):
            if status != 'Within freshness window':
                st.warning('Refresh stale or invalid source data before requesting AI highlights.')
            if status == 'Within freshness window':
                try:
                    from azure.identity import DefaultAzureCredential
                    spec = importlib.util.spec_from_file_location('research_agent', ROOT / 'agents/research.py')
                    agent = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(agent)
                    with DefaultAzureCredential() as credential:
                        selected = agent.select_highlights(report, os.environ['CIRA_AI_ENDPOINT'], os.environ['CIRA_AI_DEPLOYMENT'], credential)
                    st.dataframe(pd.DataFrame(selected), hide_index=True)
                except Exception as exc:
                    reason = agent.describe_failure(exc) if 'agent' in locals() else f'unexpected error ({type(exc).__name__})'
                    print(f'CIRA AI highlights failed: {reason}', file=sys.stderr, flush=True)
                    st.error(f'AI highlights are unavailable ({reason}). The verified source reports remain available above.')
    st.download_button('Download company report', __import__('json').dumps(report, indent=2), f'{ticker}-research.json', 'application/json')

if view == 'Portfolio lab':
    st.info('Enter a hypothetical portfolio. Holdings stay in this session and are never sent to a broker.')
    positions = {}
    for ticker, column in zip(list(data['companies']), [col for row in [st.columns(4) for _ in range((len(data['companies']) + 3) // 4)] for col in row]):
        positions[ticker] = column.number_input(f'{ticker} units', min_value=0.0, value=0.0, step=1.0)
    cash = st.number_input('Cash (USD)', min_value=0.0, value=0.0, step=100.0)
    if any(positions.values()):
        spec = importlib.util.spec_from_file_location('portfolio', ROOT / 'portfolio-engine/portfolio_analytics.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            result = module.analyze_portfolio(positions, data['prices'], cash)
            for column, label, value in zip(st.columns(3), ['Market value', 'Historical volatility', 'Maximum drawdown'],
                    [f"${result['market_value']:,.2f}", f"{result['annualized_volatility_pct']:.2f}%", f"{result['maximum_drawdown_pct']:.2f}%"]):
                column.metric(label, value)
            st.line_chart(pd.DataFrame(result['history']).set_index('date')['value'], color='#5eead4')
            st.dataframe(pd.DataFrame([{'Holding': s, 'Allocation %': v} for s, v in result['allocations_pct'].items()]), hide_index=True)
            st.caption(result['method'])
            st.caption(f"{result['observations']} observations through {result['latest_date']}. Historical volatility is not a forecast.")
        except (ValueError, KeyError) as exc:
            st.error(str(exc))

if view == 'Data quality':
    st.dataframe(pd.DataFrame([{'Ticker': t, 'Freshness': freshness(r), 'Market date': r['market']['last_date'],
        'Financial period': r['financial']['period_end'], 'Generated UTC': r['generated_at_utc'],
        'Warnings': len(r['data_quality']['warnings'])} for t, r in data['companies'].items()]), hide_index=True)
    st.write('BCG classifications are source-reported research and are not independently verified.')
    st.write('The market feed is a prototype provider. No buy/sell recommendation is generated.')
