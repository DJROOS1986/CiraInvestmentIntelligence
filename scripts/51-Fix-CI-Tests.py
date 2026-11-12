"""Make CI green again (one-off, idempotent, all-or-nothing).

1. agents/research.py: read the HTTP status safely (test doubles may not have status_code).
2. portfolio-engine/run_state.py: CIRA_RUN_STATE environment variable can point the state file elsewhere
   (tests use a temporary file, so a leftover local run cannot influence them). Production unchanged.
3. tests/test_research_platform.py: sample data for every universe company (not only AAPL/MSFT),
   isolated run state, and the read-back assertion follows the universe.
Usage (repo root): python scripts/51-Fix-CI-Tests.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDITS = [
    ("agents/research.py", "getattr(response, 'status_code', None) == 429",
     r"if response\.status_code == 429:", lambda m, nl: "if getattr(response, 'status_code', None) == 429:"),
    ("portfolio-engine/run_state.py", "CIRA_RUN_STATE",
     r'STATE = ROOT / "reports" / "run-exclusions\.json"',
     lambda m, nl: 'STATE = Path(__import__("os").environ.get("CIRA_RUN_STATE") or ROOT / "reports" / "run-exclusions.json")'),
    ("tests/test_research_platform.py", "def research_root(tmp_path, monkeypatch):",
     r"(?m)^def research_root\(tmp_path\):[ \t]*\r?\n(?P<ind>[ \t]+)now = datetime\.now\(timezone\.utc\)",
     lambda m, nl: (f"def research_root(tmp_path, monkeypatch):{nl}"
                    f"{m['ind']}monkeypatch.setenv('CIRA_RUN_STATE', str(tmp_path / 'run-exclusions.json')){nl}"
                    f"{m['ind']}now = datetime.now(timezone.utc)")),
    ("tests/test_research_platform.py", "for ticker in data_reader.TICKERS:",
     r"for ticker in \('AAPL', 'MSFT'\):", lambda m, nl: "for ticker in data_reader.TICKERS:"),
    ("tests/test_research_platform.py", "== set(data_reader.TICKERS)",
     r"assert set\(loaded\['companies'\]\) == \{'AAPL', 'MSFT'\}",
     lambda m, nl: "assert set(loaded['companies']) == set(data_reader.TICKERS)"),
]


def main():
    texts, problems, applied = {}, [], []
    for rel, marker, pattern, build in EDITS:
        if rel not in texts:
            texts[rel] = (ROOT / rel).read_bytes().decode("utf-8")
        text = texts[rel]
        nl = "\r\n" if "\r\n" in text else "\n"
        if marker in text:
            continue
        hits = list(re.finditer(pattern, text))
        if len(hits) != 1:
            problems.append(f"{rel}: pattern for '{marker}' matched {len(hits)} times")
            continue
        m = hits[0]
        texts[rel] = text[:m.start()] + build(m, nl) + text[m.end():]
        applied.append(f"{rel}: {marker}")
    if problems:
        print("NOTHING WRITTEN. Unmatched edits:")
        for p in problems:
            print("  ", p)
        sys.exit(1)
    for rel, text in texts.items():
        if text != (ROOT / rel).read_bytes().decode("utf-8"):
            (ROOT / rel).write_bytes(text.encode("utf-8"))
    print(f"Applied {len(applied)} edit(s):" if applied else "All edits already applied.")
    for a in applied:
        print("  ", a)


if __name__ == "__main__":
    main()
