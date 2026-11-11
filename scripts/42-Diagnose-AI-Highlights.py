"""Diagnose 'AI highlights are unavailable' (read-only; 3 small model calls, fractions of a cent).

Runs from the laptop (allowed through the AI firewall by the admin IP rule) with your Azure CLI
login, using a synthetic report shaped like the real one.

  A  the dashboard's own select_highlights() exactly as deployed -> real exception
  B  same request with a larger token budget (tests the reasoning-token hypothesis)
  C  same request on the /openai/v1 path without api-version (tests the API-version hypothesis)

Usage (repo root, .venv active):  python scripts/42-Diagnose-AI-Highlights.py
"""
import importlib.util
import json
import sys
from pathlib import Path

import requests
from azure.identity import AzureCliCredential

ENDPOINT = "https://ai-cira-dev-a2pjnb.openai.azure.com/"
DEPLOYMENT = "cira-research"

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cira_research", ROOT / "agents" / "research.py")
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)

REPORT = {
    "ticker": "AAPL",
    "financial": {"period_end": "2026-09-26", "metrics_usd": {
        "revenue": 478834000000, "net_income": 132175000000, "operating_cash_flow": 145097000000,
        "capital_expenditure": 9041000000, "free_cash_flow": 136056000000}},
    "market": {"last_date": "2026-11-11", "indicators": {
        "latest_close": 355.05, "daily_return_pct": 1.2, "sma_5": 350.1, "sma_20": 345.3,
        "annualized_volatility_pct": 26.9}},
}

credential = AzureCliCredential()


def raw_call(url, extra, label):
    facts = research.source_facts(REPORT)
    schema = {"type": "object", "properties": {"highlights": {"type": "array",
              "items": {"type": "string", "enum": list(facts)}}}, "required": ["highlights"],
              "additionalProperties": False}
    body = {
        "messages": [
            {"role": "system", "content": "Select up to five useful descriptive research fields from the provided source facts. Return JSON with highlights containing only field identifiers. Do not provide advice, forecasts, invented facts, or trade instructions."},
            {"role": "user", "content": json.dumps({"ticker": REPORT["ticker"], "facts": facts})},
        ],
        "response_format": {"type": "json_schema", "json_schema": {"name": "research_highlights", "strict": True, "schema": schema}},
    }
    body.update(extra)
    token = credential.get_token("https://cognitiveservices.azure.com/.default").token
    r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=60)
    print(f"\n--- {label} ---")
    print(f"HTTP {r.status_code}")
    if r.status_code != 200:
        print("Error:", r.text[:400])
        return
    data = r.json()
    choice = data["choices"][0]
    usage = data.get("usage", {})
    details = usage.get("completion_tokens_details") or {}
    print("finish_reason     :", choice.get("finish_reason"))
    print("completion_tokens :", usage.get("completion_tokens"), "| reasoning_tokens:", details.get("reasoning_tokens"))
    print("content           :", (choice["message"].get("content") or "")[:200])


print("--- A: dashboard code as deployed ---")
try:
    result = research.select_highlights(REPORT, ENDPOINT, DEPLOYMENT, credential)
    print("SUCCESS:", [h["field"] for h in result])
except requests.HTTPError as exc:
    print(f"HTTPError {exc.response.status_code}: {exc.response.text[:400]}")
except Exception as exc:  # noqa: BLE001 - diagnostic output
    print(f"{type(exc).__name__}: {exc}")

base = ENDPOINT.rstrip("/")
raw_call(f"{base}/openai/deployments/{DEPLOYMENT}/chat/completions?api-version=2024-10-21",
         {"max_completion_tokens": 4096}, "B: same request, max_completion_tokens 4096")
raw_call(f"{base}/openai/v1/chat/completions",
         {"model": DEPLOYMENT, "max_completion_tokens": 1024}, "C: /openai/v1 path, 1024 tokens")
sys.exit(0)
