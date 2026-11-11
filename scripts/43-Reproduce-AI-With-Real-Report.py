"""Reproduce 'AI highlights are unavailable' with the REAL latest report (read-only; at most 1 model call).

1. Finds the newest batch under financial-intelligence/batches/ and lists its AAPL JSON files.
2. Loads the company-intelligence report (the one the dashboard passes to select_highlights).
3. Shows the top-level structure the AI function depends on.
4. Runs agents/research.py select_highlights() exactly like the dashboard and prints the full traceback.

Usage (repo root, .venv active):  python scripts/43-Reproduce-AI-With-Real-Report.py [TICKER]
"""
import importlib.util
import json
import sys
import traceback
from pathlib import Path

from azure.identity import AzureCliCredential
from azure.storage.blob import ContainerClient

ACCOUNT, CONTAINER = "stciradeva2pjnb", "reports"
ENDPOINT, DEPLOYMENT = "https://ai-cira-dev-a2pjnb.openai.azure.com/", "cira-research"
PREFIX = "financial-intelligence/batches/"
TICKER = (sys.argv[1] if len(sys.argv) > 1 else "AAPL").upper()

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cira_research", ROOT / "agents" / "research.py")
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)

credential = AzureCliCredential()
container = ContainerClient(f"https://{ACCOUNT}.blob.core.windows.net", CONTAINER, credential=credential)

batches = sorted({b.name[len(PREFIX):].split("/")[0] for b in container.list_blobs(name_starts_with=PREFIX)})
latest = batches[-1]
names = [b.name for b in container.list_blobs(name_starts_with=f"{PREFIX}{latest}/") if TICKER in b.name and b.name.endswith(".json")]
print(f"Latest batch: {latest}")
print(f"{TICKER} JSON files:")
for n in names:
    print("   ", n)

candidates = [n for n in names if "intelligence" in n.lower()]
if not candidates:
    sys.exit("No company-intelligence file found for this ticker - paste the list above.")
report = json.loads(container.download_blob(candidates[0]).readall())
print(f"\nUsing: {candidates[0]}")


def shape(obj, depth=0, max_depth=2):
    if not isinstance(obj, dict) or depth > max_depth:
        return
    for key, value in obj.items():
        kind = type(value).__name__
        print("   " + "  " * depth + f"{key}: {kind}")
        if isinstance(value, dict):
            shape(value, depth + 1, max_depth)


print("\nReport structure (keys and types only, no values):")
shape(report)

print("\n--- source_facts() on the real report ---")
try:
    facts = research.source_facts(report)
    print(f"{len(facts)} numeric facts: {', '.join(facts)}")
except Exception:  # noqa: BLE001 - diagnostic
    traceback.print_exc(limit=3)

print("\n--- select_highlights() exactly like the dashboard ---")
try:
    result = research.select_highlights(report, ENDPOINT, DEPLOYMENT, credential)
    print("SUCCESS:", [h["field"] for h in result])
except Exception as exc:  # noqa: BLE001 - diagnostic
    response = getattr(exc, "response", None)
    if response is not None:
        print(f"HTTP {response.status_code}: {response.text[:400]}")
    traceback.print_exc(limit=3)
