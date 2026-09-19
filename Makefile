# tc-pipelines current self-gate; migrated behind tc-sdlc in Tranche 2.

.PHONY: check

check:
	uv sync --locked
	uv run --no-sync tc-fitness run
