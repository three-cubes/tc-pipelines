# tc-pipelines — local/CI parity gate.

.PHONY: check

check:
	uv sync --locked
	uv run --no-sync tc-fitness run
