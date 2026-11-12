"""Remove the dashboard access-key fallback: Entra ID becomes the only way in (one-off, all-or-nothing).

dashboard/app.py      hosted dashboard without the allowed Entra identity -> "Access denied" (no key field);
                      local development (no CIRA_STORAGE_ACCOUNT) unchanged
dashboard/access.py   docstring: no fallback
tests/test_research_agent.py  test proves denial without Entra, even with a leftover key set
infrastructure/terraform/dashboard.tf  remove random_password, the secret, the env var and the output
Usage (repo root): python scripts/55-Remove-Access-Key.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NEW_ACCESS = """if entra_ok:
    st.sidebar.caption('Signed in with Microsoft Entra ID')
elif os.environ.get('CIRA_STORAGE_ACCOUNT'):
    st.error('Access denied. Sign in with the authorised Microsoft Entra ID account.')
    st.stop()"""

NEW_TEST = """def test_hosted_dashboard_denies_without_entra(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('CIRA_STORAGE_ACCOUNT', 'account')
    monkeypatch.setenv('CIRA_ALLOWED_PRINCIPAL_ID', '00000000-0000-0000-0000-000000000001')
    monkeypatch.setenv('CIRA_DASHBOARD_ACCESS_KEY', 'test-key')  # a leftover key must not open anything
    app = AppTest.from_file(str(ROOT / 'dashboard/app.py')).run(timeout=20)
    assert not app.exception
    assert not app.metric
    assert not app.sidebar.text_input
    assert 'Access denied' in app.error[0].value"""

S = r"[ \t]*\r?\n"  # end of line
EDITS = [
    ("dashboard/app.py", "Access denied. Sign in",
     r"(?m)^required_key = os\.environ\.get\('CIRA_DASHBOARD_ACCESS_KEY'\)" + S, lambda m, nl: ""),
    ("dashboard/app.py", "Access denied. Sign in",
     r"(?ms)^if entra_ok:" + S + r".*?Dashboard access protection is not configured\.'\)" + S + r"[ \t]*st\.stop\(\)",
     lambda m, nl: NEW_ACCESS.replace("\n", nl)),
    ("dashboard/access.py", "Anything else is denied",
     r"Anything else falls back to the access key\.", lambda m, nl: "Anything else is denied (no access-key fallback)."),
    ("tests/test_research_agent.py", "test_hosted_dashboard_denies_without_entra",
     r"(?ms)^def test_hosted_dashboard_requires_access_key\(monkeypatch\):.*?set_value\('wrong-key'\)\.run\(timeout=20\)" + S +
     r"[ \t]*assert not app\.exception" + S + r"[ \t]*assert not app\.metric",
     lambda m, nl: NEW_TEST.replace("\n", nl)),
    ("infrastructure/terraform/dashboard.tf", None,
     r'(?m)^resource "random_password" "dashboard_access" \{' + S + r'[^}]*\}' + S + r'(?:[ \t]*\r?\n)?', lambda m, nl: ""),
    ("infrastructure/terraform/dashboard.tf", None,
     r'(?m)^[ \t]*secret \{' + S + r'[ \t]*name\s*=\s*"dashboard-access-key"' + S + r'[^}]*\}' + S + r'(?:[ \t]*\r?\n)?', lambda m, nl: ""),
    ("infrastructure/terraform/dashboard.tf", None,
     r'(?m)^[ \t]*env \{' + S + r'[ \t]*name\s*=\s*"CIRA_DASHBOARD_ACCESS_KEY"' + S + r'[^}]*\}' + S, lambda m, nl: ""),
    ("infrastructure/terraform/dashboard.tf", None,
     r'(?m)(?:[ \t]*\r?\n)?^output "dashboard_access_key" \{' + S + r'[^}]*\}' + r'[ \t]*(?:\r?\n)?', lambda m, nl: ""),
]


def main():
    texts, problems, applied = {}, [], []
    for rel, marker, pattern, build in EDITS:
        if rel not in texts:
            texts[rel] = (ROOT / rel).read_bytes().decode("utf-8")
        text = texts[rel]
        nl = "\r\n" if "\r\n" in text else "\n"
        hits = list(re.finditer(pattern, text))
        if not hits and (marker is None or marker in text):
            continue  # already applied
        if len(hits) != 1:
            problems.append(f"{rel}: pattern matched {len(hits)} times: {pattern[:60]}...")
            continue
        texts[rel] = text[:hits[0].start()] + build(hits[0], nl) + text[hits[0].end():]
        applied.append(f"{rel}: {pattern[:50]}...")
    leftovers = [rel for rel, t in texts.items() if re.search(r"dashboard_access|dashboard-access-key|CIRA_DASHBOARD_ACCESS_KEY", t)
                 and not rel.startswith("tests/")]
    if leftovers:
        problems.append("access-key references would remain in: " + ", ".join(leftovers))
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
