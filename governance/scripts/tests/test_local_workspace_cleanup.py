from __future__ import annotations

import json
import os
import plistlib
import shutil
import stat
import subprocess
from pathlib import Path

from governance.scripts import local_workspace_cleanup as cleanup


def run_git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def make_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    worktree = tmp_path / "disposable"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.invalid")
    run_git(repo, "config", "user.name", "Test")
    (repo / "README").write_text("base\n", encoding="utf-8")
    run_git(repo, "add", "README")
    run_git(repo, "commit", "-m", "base")
    run_git(repo, "worktree", "add", "-b", "disposable", str(worktree), "HEAD")
    return repo, worktree


def write_registry(path: Path, worktree: Path, cache: Path | None = None) -> None:
    payload = {
        "version": 1,
        "worktrees": [
            {
                "path": str(worktree),
                "disposable": True,
                "expires_at": "2020-01-01T00:00:00Z",
                "evidence": False,
            }
        ],
        "caches": (
            [
                {
                    "path": str(cache),
                    "disposable": True,
                    "expires_at": "2020-01-01T00:00:00Z",
                    "evidence": False,
                }
            ]
            if cache
            else []
        ),
        "safe_cache_roots": [str(cache.parent)] if cache else [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_report_is_default_and_fetches_before_classifying(tmp_path: Path, monkeypatch, capsys) -> None:
    repo, worktree = make_repo(tmp_path)
    registry = tmp_path / "registry.json"
    write_registry(registry, worktree)
    calls: list[tuple[str, ...]] = []

    def fake_run(args, **kwargs):
        calls.append(tuple(args))
        return cleanup.CommandResult(True, "")

    monkeypatch.setattr(cleanup, "run", fake_run)
    result = cleanup.main(["--registry", str(registry), "--repo", str(repo)])

    assert result == 0
    assert any(call[:3] == ("git", "fetch", "--prune") for call in calls)
    assert not worktree.exists() or (worktree / "README").exists()
    assert "report-only" in capsys.readouterr().out


def test_apply_removes_only_expired_registered_clean_worktree(tmp_path: Path, monkeypatch) -> None:
    repo, worktree = make_repo(tmp_path)
    registry = tmp_path / "registry.json"
    write_registry(registry, worktree)
    monkeypatch.setattr(cleanup, "fetch_repository", lambda *_: cleanup.CommandResult(True, ""))
    monkeypatch.setattr(cleanup, "open_pr_state", lambda *_: cleanup.Guard(True, "no open PR"))

    assert cleanup.main(["--registry", str(registry), "--repo", str(repo), "--apply"]) == 0
    assert not worktree.exists()


def test_worktree_identity_replacement_is_quarantined_and_not_deleted(tmp_path: Path, monkeypatch) -> None:
    repo, worktree = make_repo(tmp_path)
    actual_lstat = cleanup.os.lstat

    def replaced_lstat(path, *args, **kwargs):
        info = actual_lstat(path, *args, **kwargs)
        if Path(path).name.startswith(".tc-worktree-quarantine-"):
            values = list(info)
            values[1] += 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(cleanup.os, "lstat", replaced_lstat)
    result = cleanup.remove_worktree(repo, worktree)
    assert result.ok is False
    quarantines = list(tmp_path.glob(".tc-worktree-quarantine-*"))
    assert len(quarantines) == 1
    assert (quarantines[0] / "README").exists()


def test_dirty_worktree_is_report_only_even_when_registered(tmp_path: Path, monkeypatch, capsys) -> None:
    repo, worktree = make_repo(tmp_path)
    (worktree / "dirty.txt").write_text("keep\n", encoding="utf-8")
    registry = tmp_path / "registry.json"
    write_registry(registry, worktree)
    monkeypatch.setattr(cleanup, "fetch_repository", lambda *_: cleanup.CommandResult(True, ""))

    assert cleanup.main(["--registry", str(registry), "--repo", str(repo), "--apply"]) == 0
    assert worktree.exists()
    assert "dirty" in capsys.readouterr().out


def test_open_pr_or_unpushed_commits_protect_worktree(tmp_path: Path, monkeypatch, capsys) -> None:
    repo, worktree = make_repo(tmp_path)
    registry = tmp_path / "registry.json"
    write_registry(registry, worktree)
    monkeypatch.setattr(cleanup, "fetch_repository", lambda *_: cleanup.CommandResult(True, ""))
    monkeypatch.setattr(cleanup, "open_pr_state", lambda *_: cleanup.Guard(None, "GitHub unavailable"))

    assert cleanup.main(["--registry", str(registry), "--repo", str(repo), "--apply"]) == 0
    assert worktree.exists()
    assert "GitHub unavailable" in capsys.readouterr().out


def test_fetch_failure_protects_worktrees(tmp_path: Path, monkeypatch, capsys) -> None:
    repo, worktree = make_repo(tmp_path)
    registry = tmp_path / "registry.json"
    write_registry(registry, worktree)
    monkeypatch.setattr(cleanup, "fetch_repository", lambda *_: cleanup.CommandResult(False, "offline"))

    assert cleanup.main(["--registry", str(registry), "--repo", str(repo), "--apply"]) == 0
    assert worktree.exists()
    assert "remote state could not be refreshed" in capsys.readouterr().out


def test_missing_worktree_metadata_is_report_only_and_never_pruned(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    repo, _ = make_repo(tmp_path)
    missing = tmp_path / "missing"
    registry = tmp_path / "registry.json"
    write_registry(registry, missing)
    calls: list[tuple[str, ...]] = []

    def fake_run(args, **kwargs):
        calls.append(tuple(args))
        return cleanup.CommandResult(True, "")

    monkeypatch.setattr(cleanup, "run", fake_run)
    monkeypatch.setattr(cleanup, "worktrees", lambda *_: [{"path": str(missing)}])
    assert cleanup.main(["--registry", str(registry), "--repo", str(repo), "--apply"]) == 0
    assert ("git", "worktree", "prune") not in calls
    assert "retain stale metadata" in capsys.readouterr().out


def test_ignored_file_protects_worktree(tmp_path: Path, monkeypatch, capsys) -> None:
    repo, worktree = make_repo(tmp_path)
    (repo / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    run_git(repo, "add", ".gitignore")
    run_git(repo, "commit", "-m", "ignore")
    (worktree / "ignored.txt").write_text("keep\n", encoding="utf-8")
    registry = tmp_path / "registry.json"
    write_registry(registry, worktree)
    monkeypatch.setattr(cleanup, "fetch_repository", lambda *_: cleanup.CommandResult(True, ""))

    assert cleanup.main(["--registry", str(registry), "--repo", str(repo), "--apply"]) == 0
    assert worktree.exists()
    assert "ignored" in capsys.readouterr().out


def test_default_branch_prefers_fetched_origin_main_and_preserves_prefix(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(args, **kwargs):
        calls.append(tuple(args))
        if args[1:3] == ("symbolic-ref", "--short"):
            return cleanup.CommandResult(False, "")
        if args[-1] == "refs/remotes/origin/main":
            return cleanup.CommandResult(True, "")
        return cleanup.CommandResult(False, "")

    monkeypatch.setattr(cleanup, "run", fake_run)
    assert cleanup.default_branch(tmp_path) == "origin/main"
    assert cleanup.unique_commits(tmp_path, tmp_path, "origin/main").allowed is None
    assert ("git", "rev-list", "--count", "origin/main..HEAD") in calls


def test_cache_requires_expiry_and_no_open_file_before_apply(tmp_path: Path, monkeypatch) -> None:
    repo, worktree = make_repo(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "payload").write_text("cache\n", encoding="utf-8")
    registry = tmp_path / "registry.json"
    write_registry(registry, worktree, cache)
    monkeypatch.setattr(cleanup, "fetch_repository", lambda *_: cleanup.CommandResult(True, ""))
    monkeypatch.setattr(cleanup, "open_pr_state", lambda *_: cleanup.Guard(True, "no open PR"))
    monkeypatch.setattr(
        cleanup,
        "path_has_open_files",
        lambda *_: cleanup.Guard(None, "lsof unavailable"),
    )

    assert cleanup.main(["--registry", str(registry), "--repo", str(repo), "--apply"]) == 0
    assert cache.exists()


def test_cache_symlink_is_report_only(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "cache-link"
    link.symlink_to(target, target_is_directory=True)
    entry = {"path": str(link), "expires_at": "2020-01-01T00:00:00Z"}

    path, allowed, reason = cleanup.inspect_cache(entry)

    assert path == link
    assert allowed is False
    assert reason == "cache path is a symlink"


def test_cache_rejects_home_root_and_git_checkout(tmp_path: Path, monkeypatch) -> None:
    repo, _ = make_repo(tmp_path)
    monkeypatch.setattr(cleanup, "path_has_open_files", lambda *_: cleanup.Guard(True, "none"))
    for path in (Path.home(), Path("/"), repo):
        _, allowed, reason = cleanup.inspect_cache(
            {
                "path": str(path),
                "disposable": True,
                "expires_at": "2020-01-01T00:00:00Z",
            },
            [path.parent],
        )
        assert allowed is False
        assert reason in {
            "cache path is home or filesystem root",
            "cache path is a Git checkout/worktree",
        }


def test_cache_requires_disposable_and_safe_root(tmp_path: Path, monkeypatch) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(cleanup, "path_has_open_files", lambda *_: cleanup.Guard(True, "none"))
    base = {"path": str(cache), "expires_at": "2020-01-01T00:00:00Z"}
    _, allowed, reason = cleanup.inspect_cache(base, [tmp_path])
    assert not allowed and reason == "cache is not explicitly disposable"
    base["disposable"] = True
    _, allowed, reason = cleanup.inspect_cache(base, [tmp_path / "other"])
    assert not allowed and reason == "cache path is outside safe cache roots"


def test_safe_cache_roots_reject_home_and_filesystem_root(tmp_path: Path, monkeypatch) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(cleanup, "path_has_open_files", lambda *_: cleanup.Guard(True, "none"))
    entry = {
        "path": str(cache),
        "disposable": True,
        "expires_at": "2020-01-01T00:00:00Z",
    }
    for root in (Path.home(), Path("/")):
        _, allowed, reason = cleanup.inspect_cache(entry, [root])
        assert allowed is False
        assert reason == "safe cache root is home or filesystem root"

    registry = tmp_path / "invalid-roots.json"
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "safe_cache_roots": [str(Path.home()), "/"],
                "worktrees": [],
                "caches": [],
            }
        ),
        encoding="utf-8",
    )
    parsed = cleanup.parse_registry(registry)
    assert parsed["safe_cache_roots"] == []
    assert parsed["_invalid_entries"]


def test_lsof_recursion_has_bounded_thirty_second_timeout(tmp_path: Path, monkeypatch) -> None:
    calls: list[float | None] = []

    def fake_run(args, **kwargs):
        calls.append(kwargs.get("timeout"))
        return cleanup.CommandResult(True, "")

    monkeypatch.setattr(cleanup, "run", fake_run)

    assert cleanup.path_has_open_files(tmp_path).allowed is True
    assert calls == [30]


def test_owned_readonly_cache_is_repaired_and_removed(tmp_path: Path) -> None:
    cache = tmp_path / "readonly-cache"
    cache.mkdir()
    (cache / "payload").write_text("cache\n", encoding="utf-8")
    cache.chmod(stat.S_IRUSR | stat.S_IXUSR)

    assert cleanup.remove_cache(cache) is True
    assert not cache.exists()


def test_cache_identity_replacement_is_quarantined_and_not_deleted(tmp_path: Path, monkeypatch) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "payload").write_text("keep\n", encoding="utf-8")
    actual_lstat = cleanup.os.lstat

    def replaced_lstat(path, *args, **kwargs):
        info = actual_lstat(path, *args, **kwargs)
        if Path(path).name.startswith(".tc-cleanup-quarantine-"):
            values = list(info)
            values[1] += 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(cleanup.os, "lstat", replaced_lstat)
    assert cleanup.remove_cache(cache) is False
    quarantines = list(tmp_path.glob(".tc-cleanup-quarantine-*"))
    assert len(quarantines) == 1
    assert (quarantines[0] / "payload").exists()


def test_cache_preflight_removes_owned_symlink_without_touching_target(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("keep\n", encoding="utf-8")
    (cache / "link").symlink_to(outside)

    assert cleanup.remove_cache(cache) is True
    assert not cache.exists()
    assert outside.exists()


def test_owned_symlink_in_readonly_parent_is_removed_without_touching_target(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "cache"
    runtime = cache / "runtime"
    runtime.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_text("keep\n", encoding="utf-8")
    (runtime / "run-current").symlink_to(outside)
    runtime.chmod(stat.S_IRUSR | stat.S_IXUSR)

    assert cleanup.remove_cache(cache) is True
    assert not cache.exists()
    assert outside.exists()


def test_cache_preflight_rejects_foreign_owned_descendant(tmp_path: Path, monkeypatch) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    foreign = cache / "foreign"
    foreign.write_text("keep\n", encoding="utf-8")
    actual_lstat = cleanup.os.lstat
    actual_uid = os.getuid()

    def foreign_lstat(path, *args, **kwargs):
        info = actual_lstat(path, *args, **kwargs)
        if Path(path).name == foreign.name and Path(path).parent == cache:
            values = list(info)
            values[4] = actual_uid + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(cleanup.os, "lstat", foreign_lstat)
    assert cleanup.remove_cache(cache) is False
    assert cache.exists()
    assert foreign.exists()


def test_removal_retry_refuses_wrong_owner_and_boundaries(tmp_path: Path, monkeypatch) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    owned = candidate / "owned"
    owned.mkdir()
    link = candidate / "link"
    link.symlink_to(outside, target_is_directory=True)
    calls: list[Path] = []
    actual_uid = os.getuid()
    monkeypatch.setattr(cleanup.os, "getuid", lambda: actual_uid + 1)
    assert (
        cleanup._retry_owned_removal(lambda path: calls.append(path), str(owned), candidate, OSError())
        is False
    )
    assert (
        cleanup._retry_owned_removal(lambda path: calls.append(path), str(outside), candidate, OSError())
        is False
    )
    assert (
        cleanup._retry_owned_removal(lambda path: calls.append(path), str(link), candidate, OSError())
        is False
    )
    assert calls == []


def test_duplicate_registry_paths_are_ambiguous() -> None:
    entries = [
        {"path": "/tmp/cache", "disposable": True},
        {"path": "/tmp/./cache", "disposable": True},
    ]
    registered = cleanup.registered_by_path(entries)
    assert registered[Path("/tmp/cache").resolve()] is None


def test_malformed_registry_entries_are_reported_not_used(tmp_path: Path, capsys) -> None:
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "worktrees": [
                    "not an object",
                    {"path": str(tmp_path), "disposable": "yes"},
                ],
                "caches": [{"path": str(tmp_path), "disposable": "yes"}],
                "safe_cache_roots": [str(tmp_path)],
            }
        ),
        encoding="utf-8",
    )
    assert cleanup.main(["--registry", str(registry), "--repo", str(tmp_path)]) == 0
    assert "invalid registry entry" in capsys.readouterr().out


def test_registry_omitted_lists_default_to_empty(tmp_path: Path) -> None:
    registry = tmp_path / "minimal.json"
    registry.write_text(json.dumps({"version": 1}), encoding="utf-8")

    parsed = cleanup.parse_registry(registry)

    assert parsed["worktrees"] == []
    assert parsed["caches"] == []
    assert parsed["_invalid_entries"] == []


def test_launch_agent_template_has_report_only_default_and_apply_opt_in() -> None:
    template_path = Path("governance/workspace/com.three-cubes.tc-pipelines.workspace-cleanup.plist")
    template = template_path.read_text()
    document = plistlib.loads(template_path.read_bytes())
    assert "--apply" not in template
    assert "local_workspace_cleanup.py" in template
    assert document["ProgramArguments"][0] == "__PYTHON3__"
    assert "__GIT_DIR__" in document["EnvironmentVariables"]["PATH"]


def test_launch_agent_installer_renders_escaped_paths_and_absolute_tools(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    python = shutil.which("python3")
    assert python
    (fake_bin / "python3").symlink_to(python)
    for tool in ("git", "gh", "lsof", "launchctl"):
        executable = fake_bin / tool
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps({"version": 1, "repositories": [str(tmp_path)], "safe_cache_roots": []}),
        encoding="utf-8",
    )
    home = tmp_path / "home&xml"
    env = os.environ | {
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "TC_WORKSPACE_CLEANUP_REGISTRY": str(registry),
    }
    script = Path("governance/scripts/install-local-workspace-cleanup.sh")
    subprocess.run(["bash", str(script)], check=True, env=env, capture_output=True, text=True)
    target = home / "Library/LaunchAgents/com.three-cubes.tc-pipelines.workspace-cleanup.plist"
    document = plistlib.loads(target.read_bytes())
    assert document["ProgramArguments"][0].startswith("/")
    assert "&xml" in document["StandardOutPath"]
    assert "--apply" not in document["ProgramArguments"]
