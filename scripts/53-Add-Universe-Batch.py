"""Add a reviewed batch proposal to config/universe.json and mark it in config/identifiers.csv.

Reads research/universe-batch-<n>.json (from scripts/52), checks each proposed company against the
identifier master (category SEC_10K, same CIK), skips companies already in the universe, then writes:
  - config/universe.json      one line per company (same style as before), appended in batch order
  - config/identifiers.csv    in_universe = yes for the added tickers
All-or-nothing: any mismatch stops before writing. Safe to rerun.

Usage (repo root):  python scripts/53-Add-Universe-Batch.py research/universe-batch-1.json [--exclude CPRT ...]
"""
import csv
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = ROOT / "config" / "universe.json"
IDENTIFIERS = ROOT / "config" / "identifiers.csv"


def render_universe(doc):
    lines = ["{",
             f'  "schema_version": {json.dumps(doc["schema_version"])},',
             f'  "description": {json.dumps(doc["description"], ensure_ascii=False)},',
             '  "companies": [']
    rows = [f"    {json.dumps(c, ensure_ascii=False)}" for c in doc["companies"]]
    lines.append(",\n".join(rows))
    lines += ["  ]", "}"]
    return "\n".join(lines) + "\n"


def main():
    args = sys.argv[1:]
    exclude = set()
    if "--exclude" in args:
        i = args.index("--exclude")
        exclude = {t.upper() for t in args[i + 1:]}
        args = args[:i]
    if len(args) != 1:
        sys.exit("Usage: python scripts/53-Add-Universe-Batch.py research/universe-batch-<n>.json [--exclude T1 T2 ...]")
    proposal = [c for c in json.loads(Path(args[0]).read_text(encoding="utf-8"))["proposed_companies"] if c["ticker"] not in exclude]
    if exclude:
        print("Excluded on request:", " ".join(sorted(exclude)))
    universe = json.loads(UNIVERSE.read_text(encoding="utf-8"))
    have = {c["ticker"] for c in universe["companies"]}
    raw = IDENTIFIERS.read_bytes().decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(raw)))
    fields = list(rows[0])
    by_ticker = {r["primary_ticker"]: r for r in rows if r["category"] == "SEC_10K"}

    added, problems = [], []
    for c in proposal:
        t = c["ticker"]
        if t in have:
            continue
        r = by_ticker.get(t)
        if r is None:
            problems.append(f"{t}: not an SEC_10K row in identifiers.csv")
        elif r["sec_cik"] != c["cik"]:
            problems.append(f"{t}: CIK {c['cik']} differs from identifier master {r['sec_cik']}")
        elif r["bcg_name"] != c["bcg_name"]:
            problems.append(f"{t}: BCG name differs from identifier master")
        else:
            added.append(c)
    if problems:
        print("NOTHING WRITTEN:")
        for p in problems:
            print("  ", p)
        sys.exit(1)
    if not added:
        print("All proposed companies are already in the universe. Nothing to do.")
        return

    universe["companies"].extend(added)
    UNIVERSE.write_bytes(render_universe(universe).encode("utf-8"))
    tickers = {c["ticker"] for c in added}
    for r in rows:
        if r["category"] == "SEC_10K" and r["primary_ticker"] in tickers:
            r["in_universe"] = "yes"
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    IDENTIFIERS.write_bytes(out.getvalue().encode("utf-8"))
    print(f"Added {len(added)} companies; universe now {len(universe['companies'])}: " + " ".join(c["ticker"] for c in added))


if __name__ == "__main__":
    main()
