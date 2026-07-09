# Validation and backpressure standard

Backpressure prevents bad changes from moving forward. The goal is fast, cheap failure before slow, expensive validation.

## Default validation order

```text
1. Syntax / parse checks
2. Type checks
3. Lint / static analysis
4. Unit tests
5. Contract tests
6. Integration tests
7. Security/secret checks
8. Build/package
9. End-to-end or smoke tests
10. Commit / PR
```

Use the earliest applicable gate for the change. Documentation-only changes do not need runtime tests, but they still need scope validation: changed files should match the claimed docs-only scope.

## Change-type gates

| Change type | Minimum validation |
|---|---|
| Markdown/docs only | `git diff --name-only`; inspect changed files; links/paths checked when relevant. |
| Bash scripts | `bash -n`; `shellcheck --severity=warning` where available. |
| Sudoers | `/usr/sbin/visudo -c -f <file>`. |
| JSON config/templates | JSON parse after render/dry-run; unresolved placeholder check. |
| Skills | Happy-path and error-path tests; `SKILL.md` description quality review. |
| Gateway/live runtime config | Dry-run/apply-script validation first; explicit approval before apply/restart. |

## Stop conditions

Stop and diagnose rather than retrying when:

- the error message changes the suspected root cause;
- a command fails because of permission or auth boundaries;
- validation failure affects live config or runtime services;
- the proposed fix expands beyond the current branch's stated scope.

## Evidence standard

A task is not done until the validation evidence is named in the PR, handoff or final response.
