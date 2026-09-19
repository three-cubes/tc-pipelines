# tc-pipelines current self-gate; migrated behind tc-sdlc in Tranche 2.

.PHONY: prepare check assurance assurance-hosted

prepare:
	uv lock
	uv sync --locked
	uv run --no-sync ruff check --force-exclude --select E,F,I,UP,B,S,RUF --target-version py312 --ignore E501,RUF022 --fix --no-unsafe-fixes --exit-zero .
	uv run --no-sync ruff format --force-exclude --line-length 110 --target-version py312 .
	uv run --no-sync python assurance/run.py prepare

check: prepare
	uv run --no-sync tc-fitness run

# Same local entrypoint is available to hosted consumers. Each invocation
# retains a new evidence directory; pass --output/--fitness-wheel in ASSURANCE_ARGS.
assurance:
	uv sync --locked
	uv run --no-sync python assurance/run.py all $(ASSURANCE_ARGS)

# Selection, collection and admission share the exact hosted implementation.
assurance-hosted:
	uv sync --locked
	uv run --no-sync python assurance/hosted.py $(ASSURANCE_HOSTED_ARGS)
