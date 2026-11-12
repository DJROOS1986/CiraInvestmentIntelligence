"""Stage 13: retry a refused Yahoo price request before excluding the company (one-off, idempotent).

Yahoo's chart endpoint occasionally answers HTTP 400/429/5xx for a valid symbol (seen for TER and CDNS on
12 Nov 2026). Network/HTTP errors are retried after 3 s and 8 s; "no data" errors are not retried.
Usage (repo root): python scripts/58-Add-Price-Retry.py
"""
import re
import sys
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "scripts" / "13-Ingest-Market-Prices.py"
text = path.read_bytes().decode("utf-8")
if "def fetch_with_retry" in text:
    print("Already applied.")
    sys.exit(0)
nl = "\r\n" if "\r\n" in text else "\n"
helper = '''RETRY_WAITS_SECONDS = (3, 8)


def fetch_with_retry(symbol):
    """Yahoo occasionally refuses a valid symbol (HTTP 400/429/5xx); retry before excluding it."""
    last_error = None
    for attempt, wait in enumerate((0,) + RETRY_WAITS_SECONDS, start=1):
        if wait:
            print(f"Retrying {symbol} in {wait}s (attempt {attempt}): {last_error}")
            __import__("time").sleep(wait)
        try:
            return fetch_prices(symbol)
        except requests.RequestException as exc:
            last_error = exc
    raise last_error


'''.replace("\n", nl)
main_def = list(re.finditer(r"(?m)^def main\(\):", text))
call = list(re.finditer(r"(?m)^(?P<ind>[ \t]*)prices = fetch_prices\(symbol\)[ \t]*(?=\r?\n)", text))
if len(main_def) != 1 or len(call) != 1:
    sys.exit(f"Patterns matched {len(main_def)}/{len(call)} times (expected 1/1). Nothing written.")
c = call[0]
text = text[:c.start()] + f"{c['ind']}prices = fetch_with_retry(symbol)" + text[c.end():]
m = re.search(r"(?m)^def main\(\):", text)
text = text[:m.start()] + helper + text[m.start():]
path.write_bytes(text.encode("utf-8"))
print("Stage 13 now retries refused price requests (after 3 s and 8 s) before excluding a company.")
