"""Small fixes (one-off, idempotent, all-or-nothing).

1. dashboard/app.py: price and portfolio charts drawn with Altair, y-axis fitted to the data
   (scale zero=False) instead of starting at zero; width="stretch" (use_container_width is deprecated).
2. .github/workflows/ci.yml: actions on Node.js 24 - checkout v6, setup-python v6, setup-terraform v4.
Usage (repo root): python scripts/54-Apply-Small-Fixes.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def chart(data_expr, field):
    return (f"st.altair_chart(alt.Chart({data_expr}).mark_line(color='#5eead4').encode("
            f"x=alt.X('date:T', title=None), y=alt.Y('{field}:Q', title=None, scale=alt.Scale(zero=False))), width='stretch')")


EDITS = [
    ("dashboard/app.py", "import altair as alt",
     r"(?m)^import pandas as pd[ \t]*(?=\r?\n)", lambda m, nl: m.group(0) + nl + "import altair as alt"),
    ("dashboard/app.py", "y=alt.Y('close:Q'",
     r"st\.line_chart\(history\.set_index\('date'\)\['close'\], color='#5eead4'\)",
     lambda m, nl: chart("history", "close")),
    ("dashboard/app.py", "y=alt.Y('value:Q'",
     r"st\.line_chart\(pd\.DataFrame\(result\['history'\]\)\.set_index\('date'\)\['value'\], color='#5eead4'\)",
     lambda m, nl: chart("pd.DataFrame(result['history'])", "value")),
    (".github/workflows/ci.yml", "actions/setup-python@v6",
     r"actions/setup-python@v5", lambda m, nl: "actions/setup-python@v6"),
    (".github/workflows/ci.yml", "hashicorp/setup-terraform@v4",
     r"hashicorp/setup-terraform@v3", lambda m, nl: "hashicorp/setup-terraform@v4"),
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
    # checkout appears twice in ci.yml: replace all v4 occurrences
    ci = texts.get(".github/workflows/ci.yml", "")
    count = ci.count("actions/checkout@v4")
    if count:
        texts[".github/workflows/ci.yml"] = ci.replace("actions/checkout@v4", "actions/checkout@v6")
        applied.append(f".github/workflows/ci.yml: actions/checkout@v6 ({count}x)")
    elif "actions/checkout@v6" not in ci:
        problems.append(".github/workflows/ci.yml: actions/checkout not found")
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
