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

_FX = None


def _fx_args(ticker):
    """Reporting currency from config/universe.json (default USD) and a shared ECB rate provider."""
    global _FX
    companies = json.loads((ROOT / "config" / "universe.json").read_text(encoding="utf-8"))["companies"]
    currency = next((c.get("reporting_currency", "USD") for c in companies if c["ticker"] == ticker), "USD")
    if currency == "USD":
        return {}
    if _FX is None:
        fx_spec = importlib.util.spec_from_file_location("cira_fx", ROOT / "portfolio-engine" / "fx.py")
        fx_module = importlib.util.module_from_spec(fx_spec)
        fx_spec.loader.exec_module(fx_module)
        _FX = fx_module.EcbRates()
    return {"currency": currency, "fx": _FX}


MAX_FINANCIAL_AGE_DAYS = 550  # newest fiscal year older than ~18 months = stale (wrong label or currency)


def _check_fresh(result):
    from datetime import date
    age = (date.today() - date.fromisoformat(result["period_end"])).days
    if age > MAX_FINANCIAL_AGE_DAYS:
        raise ValueError(f"Stale financials: newest fiscal year ends {result['period_end']} ({age} days ago)")


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
            result = module.extract_annual_metrics(source, **_fx_args(ticker))
            _check_fresh(result)  # stale guard
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

