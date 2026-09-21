from pathlib import Path

import os

import idna


root = Path(__file__).resolve().parents[1]
if idna.__version__ != "3.10":
    raise SystemExit(f"expected locked idna 3.10, got {idna.__version__}")
environment = Path(os.environ["VIRTUAL_ENV"]).resolve()
if not Path(idna.__file__).resolve().is_relative_to(environment):
    raise SystemExit("idna was not imported from the locked task environment")
expected = "3.10:xn--fa-hia.de\n"
actual = (root / "generated/value.txt").read_text()
if actual != expected:
    raise SystemExit("prepared Python consumer output does not match its input")
