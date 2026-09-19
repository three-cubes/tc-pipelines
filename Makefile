# tc-pipelines current self-gate; migrated behind tc-sdlc in Tranche 2.

.PHONY: check assurance assurance-hosted

check:
	uv sync --locked
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
