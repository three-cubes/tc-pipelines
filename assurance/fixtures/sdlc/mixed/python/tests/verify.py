from pathlib import Path

import idna

root = Path(__file__).resolve().parents[1]
if idna.__version__ != "3.10" or (root / "generated/value.txt").read_text() != "3.10:xn--fa-hia.de\n":
    raise SystemExit("prepared mixed Python service output does not match its input")
