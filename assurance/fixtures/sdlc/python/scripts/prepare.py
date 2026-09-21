from pathlib import Path

import idna


root = Path(__file__).resolve().parents[1]
source = (root / "src/input.txt").read_text().strip()
output = root / "generated/value.txt"
output.parent.mkdir(parents=True, exist_ok=True)
expected = f"{idna.__version__}:{idna.encode(source).decode()}\n"
if not output.is_file() or output.read_text() != expected:
    output.write_text(expected)
