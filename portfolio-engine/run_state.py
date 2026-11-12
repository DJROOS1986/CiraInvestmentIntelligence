"""Per-run company exclusions shared by all CIRA pipeline stages.

One container run = one state file (reports/run-exclusions.json, reset at pipeline start).
A stage that cannot process a company calls exclude(); later stages only see active_tickers().
The publisher calls check_threshold(): too many exclusions fail the whole run (fail-closed for
systemic problems), a few exclusions publish a partial batch that records what is missing.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = Path(__import__("os").environ.get("CIRA_RUN_STATE") or ROOT / "reports" / "run-exclusions.json")
MAX_EXCLUDED_FRACTION = 0.10


def universe_tickers():
    path = ROOT / "config" / "universe.json"
    return [c["ticker"] for c in json.loads(path.read_text(encoding="utf-8"))["companies"]]


def exclusions():
    if not STATE.is_file():
        return {}
    return json.loads(STATE.read_text(encoding="utf-8"))


def reset():
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text("{}", encoding="utf-8")


def exclude(ticker, stage, reason):
    reason = " ".join(str(reason).split())[:300] or type(reason).__name__
    current = exclusions()
    if ticker not in current:
        current[ticker] = {"stage": stage, "reason": reason}
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(current, indent=2), encoding="utf-8")
    print(f"CIRA COMPANY FAILED: {ticker} {stage}: {reason}", flush=True)


def active_tickers():
    excluded = exclusions()
    return tuple(t for t in universe_tickers() if t not in excluded)


def allowed_exclusions(total):
    return max(1, int(total * MAX_EXCLUDED_FRACTION))


def check_threshold():
    total = len(universe_tickers())
    excluded = exclusions()
    if not active_tickers():
        raise RuntimeError("All companies excluded - nothing to publish")
    limit = allowed_exclusions(total)
    if len(excluded) > limit:
        raise RuntimeError(f"Too many companies excluded ({len(excluded)} of {total}, limit {limit}): "
                           + ", ".join(sorted(excluded)))
    return excluded
