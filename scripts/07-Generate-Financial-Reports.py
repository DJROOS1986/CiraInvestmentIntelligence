import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSOR = ROOT / "portfolio-engine" / "financial_processor.py"
SOURCE = ROOT / "ingestion" / "output" / "sec" / "companyfacts"
OUTPUT = ROOT / "reports" / "financial"

spec = importlib.util.spec_from_file_location(
    "financial_processor", PROCESSOR
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def main():
    sources = {}

    for ticker in __import__("runpy").run_path(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "portfolio-engine" / "run_state.py"))["active_tickers"]():
        files = list((SOURCE / ticker).rglob("*.json"))
        if not files:
            __import__("runpy").run_path(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "portfolio-engine" / "run_state.py"))["exclude"](ticker, "financial-report", "No SEC Company Facts found")
            continue
        sources[ticker] = max(
            files, key=lambda path: path.stat().st_mtime
        )

    reports = {}

    for ticker, source in sources.items():
        try:
            result = module.extract_annual_metrics(source)
        except Exception as exc:  # per-company: exclude and continue
            __import__("runpy").run_path(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "portfolio-engine" / "run_state.py"))["exclude"](ticker, "financial-report", exc)
            continue
        reports[ticker] = {
            "ticker": ticker,
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "source_file": str(source.relative_to(ROOT)),
            **result,
        }

    OUTPUT.mkdir(parents=True, exist_ok=True)

    for ticker, report in reports.items():
        destination = OUTPUT / f"{ticker}-financial-report.json"
        if destination.exists():
            existing = json.loads(
                destination.read_text(encoding="utf-8-sig")
            )

            old_data = {
                k: v for k, v in existing.items()
                if k != "generated_at_utc"
            }
            new_data = {
                k: v for k, v in report.items()
                if k != "generated_at_utc"
            }

            if old_data == new_data:
                print(f"{ticker}: UNCHANGED -> {destination}")
                continue

        destination.write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )
        print(
            f"{ticker}: UPDATED -> {destination}"
        )

if __name__ == "__main__":
    main()

