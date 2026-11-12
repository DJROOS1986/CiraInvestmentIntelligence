"""Portfolio lab: choose holdings in a multi-select; input fields only for the chosen companies.

With 66 companies the lab showed 66 input fields. Analysis, chart and allocation table are unchanged
(they only use companies with positions). The dashboard test now selects AAPL before entering units.
One-off, idempotent, all-or-nothing. Usage (repo root): python scripts/59-Portfolio-Multiselect.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S = r"[ \t]*\r?\n"

APP_NEW = (
    "{ind}held = st.multiselect('Holdings - choose the companies you hold', list(data['companies']))\n"
    "{ind}columns = [col for row in [st.columns(4) for _ in range((len(held) + 3) // 4)] for col in row]\n"
    "{ind}for ticker, column in zip(held, columns):\n"
    "{ind}    positions[ticker] = column.number_input(f'{{ticker}} units', min_value=0.0, value=0.0, step=1.0)"
)

EDITS = [
    ("dashboard/app.py", "held = st.multiselect(",
     r"(?m)^(?P<ind>[ \t]*)for ticker, column in zip\(list\(data\['companies'\]\), \[col for row in \[st\.columns\(4\)[^\r\n]*\):" + S +
     r"[ \t]*positions\[ticker\] = column\.number_input\(f'\{ticker\} units', min_value=0\.0, value=0\.0, step=1\.0\)",
     lambda m, nl: APP_NEW.format(ind=m["ind"]).replace("\n", nl)),
    ("tests/test_research_platform.py", "app.multiselect[0].set_value(['AAPL'])",
     r"(?m)^(?P<ind>[ \t]*)app\.number_input\[0\]\.set_value\(2\.0\)\.run\(\)",
     lambda m, nl: f"{m['ind']}app.multiselect[0].set_value(['AAPL']).run(){nl}{m.group(0)}"),
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
        texts[rel] = text[:hits[0].start()] + build(hits[0], nl) + text[hits[0].end():]
        applied.append(f"{rel}: {marker}")
    if problems:
        print("NOTHING WRITTEN:")
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
