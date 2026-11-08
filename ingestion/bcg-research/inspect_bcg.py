"""Read-only inspection of imported CIRA BCG research."""
import json
from collections import Counter
from pathlib import Path

path = Path(__file__).resolve().parent / "bcg_research.json"
data = json.loads(path.read_text(encoding="utf-8"))
companies = data["companies"]
assert len(companies) == data["company_count"] == 143
assert len({row["company"] for row in companies}) == 143
print("BCG companies:", len(companies))
print("Research classes:", dict(Counter(row["html_class"] for row in companies)))
print("Evidence statuses:", dict(Counter(row["evidence_status"] for row in companies)))
print("Rubric-scored:", sum(isinstance(row["star_score"], (int,float)) for row in companies))
print("Example AAPL/MSFT matches:")
for name in ("Apple", "Microsoft"):
    for row in companies:
        if name.lower() in row["company"].lower():
            print(" -", row["company"], "|", row["html_class"], "|", row["evidence_status"])
print("No Azure resources or existing CIRA files modified.")
