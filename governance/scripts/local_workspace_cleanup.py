"""Report-first cleanup for explicitly registered local workspaces and caches.

The registry is deliberately external to the repository.  A checked-in example
documents the shape, while a user's registry names only paths they own and have
classified as disposable.  Unknown state is always retained.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    output: str


@dataclass(frozen=True)
class Guard:
    allowed: bool | None
    reason: str


def run(args: Sequence[str], *, cwd: Path | None = None, timeout: float | None = None) -> CommandResult:
    try:
        completed = subprocess.run(
            list(args),
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(False, str(exc))
    return CommandResult(completed.returncode == 0, completed.stdout.strip())


def parse_registry(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read registry {path}: {exc}") from exc
    if not isinstance(data, dict) or type(data.get("version")) is not int or data.get("version") != 1:
        raise SystemExit(f"registry {path} must be a JSON object with version 1")
    invalid: list[str] = []
    for key in ("worktrees", "caches"):
        entries = data.get(key, [])
        if not isinstance(entries, list):
            invalid.append(f"{key} is not a list")
            data[key] = []
            continue
        valid_entries: list[dict[str, Any]] = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                invalid.append(f"{key}[{index}] is not an object")
                continue
            if (
                not isinstance(entry.get("path"), str)
                or not entry["path"]
                or not Path(entry["path"]).expanduser().is_absolute()
            ):
                invalid.append(f"{key}[{index}] has no string path")
                continue
            bad_flags = [
                name
                for name in ("disposable", "evidence", "qualification", "release")
                if name in entry and type(entry[name]) is not bool
            ]
            if bad_flags:
                invalid.append(f"{key}[{index}] has non-boolean flags: {', '.join(bad_flags)}")
                continue
            valid_entries.append(entry)
        data[key] = valid_entries
    data["_invalid_entries"] = invalid
    roots = data.get("safe_cache_roots", [])
    if not isinstance(roots, list) or any(
        not isinstance(root, str)
        or not Path(root).expanduser().is_absolute()
        or Path(root).expanduser().resolve() in {Path(Path(root).expanduser().anchor), Path.home()}
        for root in roots
    ):
        data["safe_cache_roots"] = []
        data["_invalid_entries"].append("safe_cache_roots must be a list of strings")
    repositories = data.get("repositories", [])
    if not isinstance(repositories, list) or any(
        not isinstance(repo, str) or not Path(repo).expanduser().is_absolute() for repo in repositories
    ):
        data["repositories"] = []
        data["_invalid_entries"].append("repositories must be a list of absolute strings")
    return data


def expired(entry: dict[str, Any]) -> Guard:
    value = entry.get("expires_at")
    if not isinstance(value, str) or not value:
        return Guard(None, "missing or invalid expiry")
    try:
        expiry = datetime.fromisoformat(value)
    except ValueError:
        return Guard(None, "invalid expiry")
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return Guard(expiry <= datetime.now(UTC), f"expires_at={value}")


def fetch_repository(repo: Path) -> CommandResult:
    return run(("git", "fetch", "--prune", "--quiet", "--all"), cwd=repo)


def worktrees(repo: Path) -> list[dict[str, str]]:
    result = run(("git", "worktree", "list", "--porcelain"), cwd=repo)
    if not result.ok:
        return []
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in result.output.splitlines() + [""]:
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current["path"] = value
        elif key == "branch":
            current["branch"] = value.removeprefix("refs/heads/")
        elif key == "detached":
            current["detached"] = "true"
        elif key == "prunable":
            current["prunable"] = value
    return entries


def default_branch(repo: Path) -> str | None:
    remote_head = run(("git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"), cwd=repo)
    if remote_head.ok and remote_head.output:
        return remote_head.output
    for candidate in ("origin/main", "origin/master"):
        if run(("git", "show-ref", "--verify", f"refs/remotes/{candidate}"), cwd=repo).ok:
            return candidate
    for candidate in ("main", "master"):
        if run(("git", "show-ref", "--verify", f"refs/heads/{candidate}"), cwd=repo).ok:
            return candidate
    return None


def clean_worktree(path: Path) -> Guard:
    result = run(
        ("git", "status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching"),
        cwd=path,
    )
    if not result.ok:
        return Guard(None, "cannot inspect worktree status")
    return Guard(not result.output, "clean" if not result.output else "dirty or untracked files")


def unique_commits(repo: Path, path: Path, base: str | None) -> Guard:
    if not base:
        return Guard(None, "default branch unavailable")
    result = run(("git", "rev-list", "--count", f"{base}..HEAD"), cwd=path)
    if not result.ok:
        return Guard(None, "cannot compare worktree with default branch")
    try:
        count = int(result.output)
    except ValueError:
        return Guard(None, "invalid commit comparison")
    return Guard(count == 0, "no unique commits" if count == 0 else f"{count} unique commits")


def open_pr_state(branch: str, repo: Path) -> Guard:
    if not branch:
        return Guard(None, "detached worktree")
    result = run(
        (
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--head",
            branch,
            "--json",
            "number",
            "--limit",
            "1",
        ),
        cwd=repo,
    )
    if not result.ok:
        return Guard(None, f"GitHub unavailable: {result.output or 'gh failed'}")
    try:
        prs = json.loads(result.output or "[]")
    except json.JSONDecodeError:
        return Guard(None, "invalid GitHub response")
    return Guard(not prs, "no open PR" if not prs else "open PR exists")


def path_has_open_files(path: Path) -> Guard:
    result = run(("lsof", "-t", "+D", str(path)), timeout=30)
    if not result.ok and "No such file" not in result.output:
        if result.output and "not found" in result.output.lower():
            return Guard(None, "lsof unavailable")
        return Guard(True, "no open files") if not result.output else Guard(None, "cannot inspect open files")
    return Guard(False, "open files present") if result.output else Guard(True, "no open files")


def registered_by_path(
    entries: list[dict[str, Any]],
) -> dict[Path, dict[str, Any] | None]:
    result: dict[Path, dict[str, Any] | None] = {}
    for entry in entries:
        raw = entry.get("path")
        if isinstance(raw, str) and raw:
            path = Path(raw).expanduser().resolve()
            if path in result:
                result[path] = None
            else:
                result[path] = entry
    return result


def inspect_worktree(
    repo: Path,
    actual: dict[str, str],
    registry: dict[Path, dict[str, Any] | None],
    base: str | None,
) -> tuple[bool, str]:
    path = Path(actual["path"]).expanduser().resolve()
    entry = registry.get(path)
    if path not in registry:
        return False, "unregistered worktree"
    entry = registry[path]
    if entry is None:
        return False, "ambiguous duplicate registry path"
    if not entry.get("disposable", False):
        return False, "not registered as disposable"
    if entry.get("evidence", False) or entry.get("qualification", False) or entry.get("release", False):
        return False, "evidence/qualification/release worktree"
    expiry = expired(entry)
    if expiry.allowed is not True:
        return False, expiry.reason
    default_name = base.removeprefix("origin/") if base else None
    if actual.get("detached") == "true" or actual.get("branch") in {None, "", default_name}:
        return False, "detached or default worktree"
    clean = clean_worktree(path)
    if clean.allowed is not True:
        return False, clean.reason
    commits = unique_commits(repo, path, base)
    if commits.allowed is not True:
        return False, commits.reason
    pr = open_pr_state(actual.get("branch", ""), repo)
    if pr.allowed is not True:
        return False, pr.reason
    return True, "expired, clean, no unique commits, no open PR"


def _git_admin_identity(path: Path) -> Path | None:
    result = run(("git", "rev-parse", "--git-dir"), cwd=path)
    if not result.ok or not result.output:
        return None
    return Path(result.output).expanduser().resolve()


def remove_worktree(repo: Path, path: Path) -> CommandResult:
    """Move a worktree to a verified quarantine before removing it."""
    quarantine = path.parent / (
        f".tc-worktree-quarantine-{os.getuid()}-{path.name}-{os.getpid()}-{uuid.uuid4().hex}"
    )
    try:
        before = os.lstat(path)
        admin_before = _git_admin_identity(path)
        if before.st_uid != os.getuid() or admin_before is None:
            return CommandResult(False, "worktree identity or ownership unavailable")
        moved = run(("git", "worktree", "move", str(path), str(quarantine)), cwd=repo)
        if not moved.ok:
            return moved
        after = os.lstat(quarantine)
        admin_after = _git_admin_identity(quarantine)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino) or admin_after != admin_before:
            return CommandResult(False, "worktree identity changed; quarantine retained")
    except OSError as exc:
        return CommandResult(False, str(exc))
    removed = run(("git", "worktree", "remove", str(quarantine)), cwd=repo)
    if not removed.ok:
        return removed
    return CommandResult(True, "verified worktree removed")


def is_git_checkout(path: Path) -> bool:
    result = run(("git", "rev-parse", "--show-toplevel"), cwd=path, timeout=5)
    return result.ok and bool(result.output)


def inspect_cache(
    entry: dict[str, Any], safe_cache_roots: Sequence[Path] | None = None
) -> tuple[Path | None, bool, str]:
    raw = entry.get("path")
    if not isinstance(raw, str) or not raw:
        return None, False, "missing cache path"
    configured = Path(raw).expanduser()
    if not configured.is_absolute():
        return configured, False, "cache path must be absolute"
    if configured.is_symlink():
        return configured, False, "cache path is a symlink"
    path = configured.resolve()
    if path in {Path(path.anchor), Path.home()}:
        return path, False, "cache path is home or filesystem root"
    if is_git_checkout(path):
        return path, False, "cache path is a Git checkout/worktree"
    roots = [Path(root).expanduser().resolve() for root in (safe_cache_roots or [])]
    if any(root in {Path(root.anchor), Path.home()} for root in roots):
        return path, False, "safe cache root is home or filesystem root"
    if not roots or not any(path != root and path.is_relative_to(root) for root in roots):
        return path, False, "cache path is outside safe cache roots"
    if type(entry.get("disposable")) is not bool or entry.get("disposable") is not True:
        return path, False, "cache is not explicitly disposable"
    if entry.get("evidence", False) or entry.get("qualification", False) or entry.get("release", False):
        return path, False, "evidence/qualification/release cache"
    expiry = expired(entry)
    if expiry.allowed is not True:
        return path, False, expiry.reason
    if not path.exists():
        return path, False, "already absent"
    if not path.is_dir() or path.is_symlink():
        return path, False, "not a real directory"
    open_files = path_has_open_files(path)
    if open_files.allowed is not True:
        return path, False, open_files.reason
    return path, True, "expired and no open files"


def _retry_owned_removal(function: Any, raw_path: str, candidate_root: Path, failure: BaseException) -> bool:
    """Retry one rmtree operation after adding owner-only write permission."""
    path = Path(raw_path)
    try:
        if candidate_root.is_symlink():
            return False
        root = candidate_root.resolve(strict=False)
        if path.is_symlink():
            lexical = Path(os.path.abspath(path))
            if not lexical.is_relative_to(root):
                return False
            link_info = os.lstat(path)
            if link_info.st_uid != os.getuid():
                return False
            parent = path.parent
            if parent != path and Path(os.path.abspath(parent)).is_relative_to(root):
                parent_info = os.lstat(parent)
                if parent_info.st_uid != os.getuid():
                    return False
                parent_mode = stat.S_IMODE(parent_info.st_mode)
                os.chmod(
                    parent,
                    parent_mode | stat.S_IWUSR | stat.S_IXUSR,
                    follow_symlinks=False,
                )
            function(path)
            return True
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(root):
            return False
        targets = [path]
        parent = path.parent
        if parent != path and parent.resolve(strict=False).is_relative_to(root):
            targets.append(parent)
        for target in targets:
            target_info = os.lstat(target)
            if target_info.st_uid != os.getuid():
                return False
            mode = stat.S_IMODE(target_info.st_mode)
            owner_bits = stat.S_IWUSR
            if stat.S_ISDIR(target_info.st_mode):
                owner_bits |= stat.S_IXUSR
            os.chmod(target, mode | owner_bits, follow_symlinks=False)
        function(path)
        return True
    except (OSError, ValueError):
        return False


def preflight_cache_tree(path: Path) -> Guard:
    """Verify ownership and structure without following symlinks."""
    pending = [path]
    try:
        while pending:
            current = pending.pop()
            info = os.lstat(current)
            if info.st_uid != os.getuid():
                return Guard(False, "cache tree contains a foreign-owned path")
            if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
                with os.scandir(current) as entries:
                    pending.extend(Path(entry.path) for entry in entries)
    except OSError as exc:
        return Guard(None, f"cannot preflight cache tree: {exc}")
    return Guard(True, "cache tree is owned and symlink-safe")


def _remove_verified_cache(path: Path) -> bool:
    """Remove a quarantined cache, repairing only owned readonly paths."""
    candidate_root = path.resolve(strict=False)
    if path.is_symlink() or candidate_root.is_symlink():
        return False
    if preflight_cache_tree(path).allowed is not True:
        return False

    def onexc(function: Any, raw_path: str, failure: BaseException) -> None:
        if not _retry_owned_removal(function, raw_path, candidate_root, failure):
            raise failure

    def onerror(function: Any, raw_path: str, exc_info: Any) -> None:
        failure = exc_info[1]
        if not _retry_owned_removal(function, raw_path, candidate_root, failure):
            raise failure.with_traceback(exc_info[2])

    try:
        shutil.rmtree(path, onexc=onexc)
    except TypeError:
        try:
            shutil.rmtree(path, onerror=onerror)
        except OSError:
            return False
    except OSError:
        return False
    return not path.exists()


def remove_cache(path: Path) -> bool:
    """Quarantine and remove an approved cache only after an identity check."""
    candidate_root = path.resolve(strict=False)
    if path.is_symlink() or candidate_root.is_symlink():
        return False
    if preflight_cache_tree(path).allowed is not True:
        return False
    try:
        before = os.lstat(path)
        if before.st_uid != os.getuid() or not stat.S_ISDIR(before.st_mode):
            return False
        quarantine = path.parent / (
            f".tc-cleanup-quarantine-{os.getuid()}-{path.name}-{os.getpid()}-{uuid.uuid4().hex}"
        )
        os.rename(path, quarantine)
        after = os.lstat(quarantine)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            return False
    except OSError:
        return False
    return _remove_verified_cache(quarantine)


def process_repo(repo: Path, registry: dict[str, Any], apply: bool) -> int:
    print(f"repository: {repo}")
    fetched = fetch_repository(repo)
    if not fetched.ok:
        print(f"  protect: fetch failed ({fetched.output or 'unknown error'})")
        print("  retain all worktrees: remote state could not be refreshed")
        return 0
    base = default_branch(repo)
    registered = registered_by_path(registry.get("worktrees", []))
    for actual in worktrees(repo):
        path = Path(actual["path"]).expanduser().resolve()
        if not path.exists():
            print(f"  retain stale metadata for missing worktree directory {path} (report-only)")
            continue
        allowed, reason = inspect_worktree(repo, actual, registered, base)
        if allowed:
            if apply:
                result = remove_worktree(repo, path)
                print(
                    f"  {'removed' if result.ok else 'protect'} worktree {path}: {reason if result.ok else result.output}"
                )
            else:
                print(f"  candidate worktree {path}: {reason} (report-only)")
        else:
            print(f"  retain worktree {path}: {reason}")
    return 0


def process_caches(registry: dict[str, Any], apply: bool) -> None:
    safe_roots = [Path(root) for root in registry.get("safe_cache_roots", [])]
    seen: dict[Path, int] = {}
    for index, entry in enumerate(registry.get("caches", [])):
        raw = entry.get("path")
        if isinstance(raw, str) and raw:
            path = Path(raw).expanduser().resolve()
            seen[path] = seen.get(path, 0) + 1
    for entry in registry.get("caches", []):
        if not isinstance(entry, dict):
            print("  retain cache: invalid registry entry")
            continue
        raw = entry.get("path")
        canonical = Path(raw).expanduser().resolve() if isinstance(raw, str) and raw else None
        if canonical is not None and seen.get(canonical, 0) > 1:
            print(f"  retain cache {canonical}: ambiguous duplicate registry path")
            continue
        path, allowed, reason = inspect_cache(entry, safe_roots)
        if path is None:
            print(f"  retain cache: {reason}")
            continue
        if allowed and apply:
            if remove_cache(path):
                print(f"  removed cache {path}: {reason}")
            else:
                print(f"  retain cache {path}: removal failed or safety boundary rejected")
        elif allowed:
            print(f"  candidate cache {path}: {reason} (report-only)")
        else:
            print(f"  retain cache {path}: {reason}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path(
            os.environ.get(
                "TC_WORKSPACE_CLEANUP_REGISTRY",
                "~/.config/tc-pipelines/workspace-cleanup.json",
            )
        ),
    )
    parser.add_argument(
        "--repo",
        action="append",
        type=Path,
        dest="repos",
        help="repository root (repeatable)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="remove only candidates that pass every guard",
    )
    args = parser.parse_args(argv)
    registry = parse_registry(args.registry.expanduser())
    for reason in registry.get("_invalid_entries", []):
        print(f"  retain: invalid registry entry ({reason})")
    repos = args.repos or [Path(value) for value in registry.get("repositories", [])]
    if not repos:
        repos = [Path.cwd()]
    print("workspace cleanup: apply mode" if args.apply else "workspace cleanup: report-only mode")
    for repo in repos:
        process_repo(repo.expanduser().resolve(), registry, args.apply)
    process_caches(registry, args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
