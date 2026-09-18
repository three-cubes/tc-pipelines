# Single-PR Release Design

## Goal

A reviewed feature PR carries its release metadata and becomes an immutable release automatically after merge. A second version-only PR, a second quality run, and a second human release approval are removed.

## Release contract

The feature branch is the only mutable release surface:

1. The author dispatches `Prepare release` on the feature branch with either an exact version or a semantic bump.
2. The canonical `prepare-release-metadata` action updates the version source, lockfile when uv owns it, CHANGELOG section, and preparation receipt in one commit made and pushed by `three-cubes-agent`.
3. The feature PR runs its normal required checks and receives its normal review after that commit.
4. A merged-PR caller runs only when `.release-prepared.json` changed. It passes the exact merge commit SHA to the canonical release workflow.
5. The release workflow validates the receipt and its bound files from that SHA, creates or confirms the annotated tag, and creates or confirms the GitHub Release.

The preparation receipt is the explicit release signal. Repos do not need a second release label or another mutable version coordinate.

## Components

### Preparation action

`actions/prepare-release-metadata/prepare_release.py` accepts exactly one of:

- `--version vX.Y.Z` for an explicit release coordinate; or
- `--bump major|minor|patch`, which runs the installed `uv version --bump` command and prefixes the resulting project version with the configured tag prefix.

An explicit version retains support for CalVer repositories and plain `VERSION` files. A bump targets a static PEP 621 project version and lets uv update both `pyproject.toml` and `uv.lock`; the action then prepares CHANGELOG and the receipt. The action never hand-edits TOML or the lockfile.

### Same-branch preparation workflow

The governance bootstrap renders `prepare-release.yml`. It mints a `three-cubes-agent` installation token, checks out the selected non-main branch with that token, invokes the pinned preparation action, commits every generated output, and pushes to the same branch. The normal PR checks then evaluate the final candidate once.

### Merge-triggered release workflow

The governance bootstrap also renders `release-on-merge.yml`. Its `pull_request.closed` path filter limits it to merged PRs that changed `.release-prepared.json`. It calls a reusable tc-pipelines workflow with the exact `merge_commit_sha` and never checks out or executes a pull-request workflow definition.

The reusable resolves the version from the receipt at the exact merge SHA, then calls the existing release spine. The tag helper has three outcomes:

- absent tag: create an annotated tag at the exact merge SHA;
- existing tag at the same SHA: report success without mutation;
- existing tag at another SHA: fail without mutation.

GitHub Release creation follows the same idempotent rule. This makes workflow replay safe.

## Security and governance

- Preparation and release writes use the canonical GitHub App token.
- The only executable code used by privileged workflows comes from an immutable tc-pipelines SHA or the default-branch workflow definition.
- The feature PR remains the human review boundary. No unreviewed post-merge source commit is created.
- The tag always targets the reviewed merge commit.
- Production deployment approvals remain unchanged; package release is not a production deployment.

## Testing

Tests execute the Python entry points against real temporary Git repositories. They prove semantic bump preparation, explicit-version preparation, receipt/file binding, exact-SHA tag creation, replay idempotency, and rejection of a conflicting tag. Workflow tests render bootstrap output and parse the resulting YAML, while the behavioural tests exercise the commands used by those workflows.

## Migration

The existing tc-fitness `v0.16.1` PR becomes the migration PR. It adds the preparation receipt and thin caller workflows, removes the manually maintained `__version__` fallback value, and pins the released tc-pipelines SHA. When it merges, the merge-triggered workflow creates `v0.16.1`. Future tc-fitness releases prepare the original feature PR and do not open a release-only PR.
