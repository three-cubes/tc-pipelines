# tc-pipelines current self-gate; migrated behind tc-sdlc in Tranche 2.

TC_SCANNER_BIN_DIR ?= $(if $(XDG_CACHE_HOME),$(XDG_CACHE_HOME),$(HOME)/.cache)/tc-pipelines/scanners/bin
TC_SCANNER_BIN_DIR := $(abspath $(TC_SCANNER_BIN_DIR))
export TC_SCANNER_BIN_DIR
export PATH := $(TC_SCANNER_BIN_DIR):$(PATH)

.PHONY: prepare assert-clean check assurance assurance-hosted scanner-versions workspace-cleanup-report workspace-cleanup-apply install-workspace-cleanup

WORKSPACE_CLEANUP_REGISTRY ?= $(HOME)/.config/tc-pipelines/workspace-cleanup.json
WORKSPACE_CLEANUP_REPOS ?= $(CURDIR)

workspace-cleanup-report:
	TC_WORKSPACE_CLEANUP_REGISTRY="$(WORKSPACE_CLEANUP_REGISTRY)" uv run --no-sync python governance/scripts/local_workspace_cleanup.py --registry "$(WORKSPACE_CLEANUP_REGISTRY)" --repo "$(WORKSPACE_CLEANUP_REPOS)"

workspace-cleanup-apply:
	TC_WORKSPACE_CLEANUP_REGISTRY="$(WORKSPACE_CLEANUP_REGISTRY)" uv run --no-sync python governance/scripts/local_workspace_cleanup.py --registry "$(WORKSPACE_CLEANUP_REGISTRY)" --repo "$(WORKSPACE_CLEANUP_REPOS)" --apply

install-workspace-cleanup:
	TC_WORKSPACE_CLEANUP_REGISTRY="$(WORKSPACE_CLEANUP_REGISTRY)" bash governance/scripts/install-local-workspace-cleanup.sh

prepare:
	uvx --from uv==0.12.5 uv lock
	uv sync --locked
	pnpm install --frozen-lockfile
	INSTALL_OSV_SCANNER=true INSTALL_CHECKOV_SCANNER=true bash actions/python-gate-body/provision-scanners.sh
	uv run --no-sync ruff check --force-exclude --select E,F,I,UP,B,S,RUF --target-version py312 --ignore E501,RUF022 --fix --no-unsafe-fixes --exit-zero .
	uv run --no-sync ruff format --force-exclude --line-length 110 --target-version py312 .
	uv run --no-sync python assurance/run.py prepare

check: prepare
	@$(MAKE) --no-print-directory assert-clean
	uv run --no-sync tc-fitness run

scanner-versions:
	@command -v osv-scanner && osv-scanner --version && command -v checkov && checkov --version

assert-clean:
	@test -z "$$(git status --porcelain --untracked-files=all)" || { git status --short; echo "preparation changed committed state; commit the prepared files before evaluation" >&2; exit 1; }

# Same local entrypoint is available to hosted consumers. Each invocation
# retains a new evidence directory; pass --output/--fitness-wheel in ASSURANCE_ARGS.
assurance:
	uv sync --locked
	uv run --no-sync python assurance/run.py all $(ASSURANCE_ARGS)

# Selection, collection and admission share the exact hosted implementation.
assurance-hosted:
	uv sync --locked
	uv run --no-sync python assurance/hosted.py $(ASSURANCE_HOSTED_ARGS)
