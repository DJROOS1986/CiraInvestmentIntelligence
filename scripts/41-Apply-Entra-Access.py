"""One-off, idempotent patch: dashboard accepts the Entra ID identity; access key becomes fallback.

1. dashboard/app.py: import entra_allowed; replace the access-key block (lines ~48-56) with
   Entra-first logic. Aborts without writing if the original block is not found exactly once.
2. infrastructure/terraform/dashboard.tf: append env CIRA_ALLOWED_PRINCIPAL_ID (your object ID via
   data.azurerm_client_config) after the CIRA_AI_DEPLOYMENT env block, so the plan shows one added env.

Usage (repo root): python scripts/41-Apply-Entra-Access.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dashboard" / "app.py"
TF = ROOT / "infrastructure" / "terraform" / "dashboard.tf"

OLD_BLOCK = [
    "required_key = os.environ.get('CIRA_DASHBOARD_ACCESS_KEY')",
    "if required_key:",
    "    supplied = st.sidebar.text_input('Access key', type='password')",
    "    if not hmac.compare_digest(supplied, required_key):",
    "        st.info('Enter your dashboard access key to open the research workspace.')",
    "        st.stop()",
    "if os.environ.get('CIRA_STORAGE_ACCOUNT') and not required_key:",
    "    st.error('Dashboard access protection is not configured.')",
    "    st.stop()",
]
NEW_BLOCK = [
    "required_key = os.environ.get('CIRA_DASHBOARD_ACCESS_KEY')",
    "try:",
    "    request_headers = st.context.headers",
    "except Exception:",
    "    request_headers = {}",
    "entra_ok = entra_allowed(request_headers, os.environ.get('CIRA_ALLOWED_PRINCIPAL_ID'))",
    "if entra_ok:",
    "    st.sidebar.caption('Signed in with Microsoft Entra ID')",
    "if required_key and not entra_ok:",
    "    supplied = st.sidebar.text_input('Access key', type='password')",
    "    if not hmac.compare_digest(supplied, required_key):",
    "        st.info('Enter your dashboard access key to open the research workspace.')",
    "        st.stop()",
    "if os.environ.get('CIRA_STORAGE_ACCOUNT') and not required_key and not entra_ok:",
    "    st.error('Dashboard access protection is not configured.')",
    "    st.stop()",
]
TF_ENV = [
    "      env {",
    '        name  = "CIRA_ALLOWED_PRINCIPAL_ID"',
    "        value = data.azurerm_client_config.current.object_id",
    "      }",
]


def read(path):
    raw = path.read_bytes().decode("utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"
    return raw, nl


def patch_app():
    text, nl = read(APP)
    if "entra_allowed" in text:
        print("app.py: already patched.")
        return
    old, new = nl.join(OLD_BLOCK), nl.join(NEW_BLOCK)
    if text.count(old) != 1:
        sys.exit("app.py: original access-key block not found exactly once. Nothing written.")
    imports = [m for m in re.finditer(r"(?m)^from data import .*$", text)]
    if len(imports) != 1:
        sys.exit("app.py: 'from data import ...' line not found exactly once. Nothing written.")
    text = text.replace(old, new)
    line = imports[0].group(0)
    text = text.replace(line, line + nl + "from access import entra_allowed", 1)
    APP.write_bytes(text.encode("utf-8"))
    print("app.py: Entra-first access check installed (access key is fallback).")


def patch_tf():
    text, nl = read(TF)
    if "CIRA_ALLOWED_PRINCIPAL_ID" in text:
        print("dashboard.tf: already patched.")
        return
    pattern = re.compile(
        r'(?m)^[ \t]*env \{[ \t]*\r?\n[ \t]*name[ \t]*=[ \t]*"CIRA_AI_DEPLOYMENT"[ \t]*\r?\n[^\n]*\r?\n[ \t]*\}[ \t]*$'
    )
    hits = list(pattern.finditer(text))
    if len(hits) != 1:
        sys.exit("dashboard.tf: CIRA_AI_DEPLOYMENT env block not found exactly once. Nothing written.")
    end = hits[0].end()
    text = text[:end] + nl + nl.join(TF_ENV) + text[end:]
    TF.write_bytes(text.encode("utf-8"))
    print("dashboard.tf: env CIRA_ALLOWED_PRINCIPAL_ID appended after CIRA_AI_DEPLOYMENT.")


if __name__ == "__main__":
    patch_app()
    patch_tf()
