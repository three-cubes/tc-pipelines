#!/bin/bash
set -euo pipefail

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required: https://brew.sh" >&2
  exit 1
fi

brew install node@24 python@3.13 uv

"$(brew --prefix node@24)/bin/node" --version
"$(brew --prefix python@3.13)/libexec/bin/python3" --version
"$(brew --prefix uv)/bin/uv" --version
