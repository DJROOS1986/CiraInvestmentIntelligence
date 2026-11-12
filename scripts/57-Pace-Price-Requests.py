"""Stage 13: pause 0.5 s between Yahoo price requests (one-off, idempotent).

With 60+ companies, back-to-back requests risk throttling (each throttled company would be excluded).
Usage (repo root): python scripts/57-Pace-Price-Requests.py
"""
import re
import sys
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "scripts" / "13-Ingest-Market-Prices.py"
text = path.read_bytes().decode("utf-8")
if "PRICE_REQUEST_PAUSE_SECONDS" in text:
    print("Already applied.")
    sys.exit(0)
nl = "\r\n" if "\r\n" in text else "\n"
hits = list(re.finditer(r'(?m)^(?P<ind>[ \t]*)print\(f"\\nFetching \{symbol\}\.\.\."\)', text))
if len(hits) != 1:
    sys.exit(f"Pattern matched {len(hits)} times. Nothing written.")
m = hits[0]
text = (text[:m.start()] + f'{m["ind"]}__import__("time").sleep(PRICE_REQUEST_PAUSE_SECONDS){nl}' + text[m.start():])
anchor = re.search(r'(?m)^OUTPUT = ROOT / "reports" / "market-data"[ \t]*(?=\r?\n)', text)
if not anchor:
    sys.exit("OUTPUT line not found. Nothing written.")
text = text[:anchor.end()] + nl + "PRICE_REQUEST_PAUSE_SECONDS = 0.5  # gentle pacing for the Yahoo chart endpoint" + text[anchor.end():]
path.write_bytes(text.encode("utf-8"))
print("Stage 13 now pauses 0.5 s between price requests.")
