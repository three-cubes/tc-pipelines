# Local workspace cleanup

`governance/scripts/local_workspace_cleanup.py` is a report-first janitor for
local Git worktrees and explicitly registered disposable caches. It fetches
remote refs before inspecting each repository and compares against the fetched
`origin/main` (falling back to a local main/master only when no remote ref is
available). Run it without
`--apply` to review the report; only an explicit `--apply` can remove anything.

The registry is machine-specific and must live outside Git. Set
`TC_WORKSPACE_CLEANUP_REGISTRY` or use the default
`~/.config/tc-pipelines/workspace-cleanup.json`. Start from
`local-workspace-cleanup.example.json`, replacing every example path with an
exact absolute path you own. The registry must list at least one absolute
repository path. Cache entries must set `disposable: true`, and
their path must be below one of the dedicated `safe_cache_roots`; roots,
home, Git checkouts/worktrees, symlinks, and paths outside that allowlist are
always retained. A safe root itself may not be the filesystem root or the
user's home directory.

Automatic removal requires all of these conditions: the path is registered as
disposable and expired; the worktree is clean, attached to a non-default branch,
has no commits unique from the default branch, and has no open PR. GitHub or
open-file checks that cannot be proven are retained. Unregistered, detached,
dirty, orphaned, ambiguous, qualification, release, and evidence paths are
report-only. Missing worktree directories are reported individually; the janitor
never runs repository-wide `git worktree prune` automatically. Approved cache
and worktree removals first move the object to an owner-marked quarantine and
verify its filesystem identity before deleting it.

Caches use the same exact-path and evidence guards, plus expiry and an
open-file check. Duplicate canonical paths and malformed registry entries are
ambiguous and retained. The included macOS LaunchAgent template invokes report-only
mode daily. Install it with `make install-workspace-cleanup` after creating the
external registry; the installer validates absolute `python3`, `git`, `gh`, and
`lsof` executables, renders the plist with `plistlib`, and never enables
`--apply`.
