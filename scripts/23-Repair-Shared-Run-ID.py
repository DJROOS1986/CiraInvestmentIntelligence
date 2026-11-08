import ast
import pathlib
import shutil
import subprocess
import sys
import uuid
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]

CHANGES = {
    "portfolio-engine/company_intelligence.py": [
        (
            ", None: {'run_id': run_id} if run_id is not None else {}",
            ", **({'run_id': run_id} if run_id is not None else {})",
        ),
    ],
    "scripts/15-Build-Company-Intelligence.py": [
        (
            "def main():",
            "def main():\n    from uuid import uuid4\n    run_id = uuid4().hex",
        ),
        (
            "ticker, financial, prices, market, assessment",
            "ticker, financial, prices, market, assessment, run_id=run_id",
        ),
    ],
    "scripts/16-Refresh-Company-Intelligence.py": [
        (
            "def build_reports():",
            "def build_reports():\n    from uuid import uuid4\n    run_id = uuid4().hex",
        ),
        (
            "ticker, financial, prices, market, assessment",
            "ticker, financial, prices, market, assessment, run_id=run_id",
        ),
    ],
}

def main():
    prepared = {}

    for relative, replacements in CHANGES.items():
        path = ROOT / relative
        original = path.read_text(encoding="utf-8")
        updated = original

        for old, new in replacements:
            count = updated.count(old)
            if count != 1:
                raise RuntimeError(
                    f"{relative}: expected one match, found {count}"
                )
            updated = updated.replace(old, new, 1)

        ast.parse(updated, filename=str(path))
        prepared[relative] = updated

    backup = (
        ROOT / ".phase55-backups"
        / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    )
    backup.mkdir(parents=True, exist_ok=False)

    for relative in prepared:
        destination = backup / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)

    modified = []

    try:
        for relative, updated in prepared.items():
            (ROOT / relative).write_text(updated, encoding="utf-8")
            modified.append(relative)

        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "tests"],
            cwd=ROOT,
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError("Unit tests failed")

        print("PHASE 5.5 SOURCE REPAIR: PASS")
        print("Modified files:", len(modified))
        print("Backup:", backup)
        print("Azure: UNCHANGED")
        print("Reports: NOT REGENERATED")

    except Exception:
        for relative in modified:
            shutil.copy2(backup / relative, ROOT / relative)
        print("ROLLBACK: Original source files restored")
        raise

if __name__ == "__main__":
    main()