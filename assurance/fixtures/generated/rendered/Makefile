# three-cubes/assurance-generated compatibility Makefile. The executable-foundation migration replaces
# these internals with tc-sdlc while retaining the stable command names.

.PHONY: check prepare fix setup

# Current compatibility verifier. tc-fitness is a core evaluation component;
# tc-sdlc will schedule it with the repository's other language and build tasks.
check: prepare
	uv run tc-fitness run

# Deterministic preparation runs before every local evaluation.
prepare:
	uv run ruff check --fix .
	uv run ruff format .
	uv lock

# Compatibility alias for existing consumers.
fix: prepare

# One-time dev setup: install the commit-msg strip hook + the pre-push gate replay
# so the fitness gate fires locally before the CI round-trip.
setup:
	uv run pre-commit install --hook-type commit-msg --hook-type pre-push
	uv run pre-commit install
