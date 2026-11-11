"""One-off, idempotent patch for AI resilience (run after extracting CIRA-AIFix.zip).

1. dashboard/app.py: the AI except-block shows and logs the real (user-safe) reason.
2. infrastructure/terraform/ai.tf: deployment capacity 1 -> 10 (in-place update).
Aborts without writing a file if its expected text is not found exactly once.

Usage (repo root): python scripts/44-Apply-AI-Resilience.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dashboard" / "app.py"
AI_TF = ROOT / "infrastructure" / "terraform" / "ai.tf"


def read(path):
    raw = path.read_bytes().decode("utf-8")
    return raw, ("\r\n" if "\r\n" in raw else "\n")


def line_repr(line):
    """Show invisible characters: tabs as <TAB>, carriage returns as <CR>."""
    return line.replace("\t", "<TAB>").replace("\r", "<CR>")


def patch_app():
    text, nl = read(APP)
    if "describe_failure" in text:
        print("app.py: already patched.")
        return
    pattern = re.compile(
        r"(?m)^(?P<ind>[ \t]*)except Exception:[ \t\r]*\n"
        r"(?P<ind2>[ \t]*)st\.error\(['\"]AI highlights are unavailable\. The verified source reports remain available above\.['\"]\)[ \t\r]*$"
    )
    hits = list(pattern.finditer(text))
    if len(hits) != 1:
        print(f"app.py: AI except-block found {len(hits)} times (expected 1). Nothing written.")
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if "AI highlights are unavailable" in line:
                for j in range(max(0, i - 2), min(len(lines), i + 1)):
                    print(f"  line {j + 1}: {line_repr(lines[j])}")
        sys.exit(1)
    m = hits[0]
    ind, ind2 = m.group("ind"), m.group("ind2")
    new = nl.join([
        f"{ind}except Exception as exc:",
        f"{ind2}reason = agent.describe_failure(exc) if 'agent' in locals() else f'unexpected error ({{type(exc).__name__}})'",
        f"{ind2}print(f'CIRA AI highlights failed: {{reason}}', file=sys.stderr, flush=True)",
        f"{ind2}st.error(f'AI highlights are unavailable ({{reason}}). The verified source reports remain available above.')",
    ])
    text = text[:m.start()] + new + text[m.end():]
    if not re.search(r"(?m)^import sys\b|^import .*\bsys\b", text):
        sys.exit("app.py: 'import sys' not found - patch would break. Nothing written.")
    APP.write_bytes(text.encode("utf-8"))
    print("app.py: AI errors now show and log the real reason.")


def patch_tf():
    text, nl = read(AI_TF)
    if re.search(r"(?m)^\s*capacity\s*=\s*10\s*$", text):
        print("ai.tf: capacity already 10.")
        return
    hits = list(re.finditer(r"(?m)^([ \t]*capacity[ \t]*=[ \t]*)1([ \t\r]*)$", text))
    if len(hits) != 1:
        sys.exit("ai.tf: 'capacity = 1' not found exactly once. Nothing written.")
    m = hits[0]
    text = text[:m.start()] + m.group(1) + "10" + m.group(2) + text[m.end():]
    AI_TF.write_bytes(text.encode("utf-8"))
    print("ai.tf: deployment capacity 1 -> 10.")


if __name__ == "__main__":
    patch_app()
    patch_tf()
