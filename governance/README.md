# governance/ — Golden Path repo-governance templates

> 🛑 **Start at [`STANDARDS.md`](STANDARDS.md)** — the canonical index of the org's build/release/governance
> intent (the Build & Release Health OKRs, the kairix#499 fitness spec, the canonical homes, the merge model).
> **Do not re-derive any of it; converge up and promote improvements into the canonical homes.**


The canonical baseline a new Three Cubes repo adopts so its branch protection,
review routing, dependency policy, and local gate all match the Golden Path —
without hand-copying drift. Applied by
[`scripts/bootstrap-repo-governance.sh`](scripts/bootstrap-repo-governance.sh),
which wires a repo from these templates.

| File | What it sets | How it's applied |
|---|---|---|
| [`rulesets/`](rulesets/) | The **org-level** branch protection — four organization rulesets applied centrally, not committed per-repo: `org-main-product` / `org-main-core` / `org-main-baseline` guard `main` (block deletion + non-fast-forward; PR + **code-owner review** (HITL on control-plane paths only); **0 approvals** on product & baseline, **1** on core; **not strict** and **no stale-dismiss** — an approval persists through pushes; required checks **Quality gate** + **no-attribution**), and `org-branch-naming` natively enforces the Linear / Conventional-Branch / bot branch-name pattern on every non-`main` branch. Spec: [`CANONICAL-ORG-RULESET.md`](CANONICAL-ORG-RULESET.md). | imported at org level by the org-admin (`gh api orgs/<org>/rulesets --method POST`) |
| [`CODEOWNERS`](CODEOWNERS) | **Two-tier** review routing — only the control plane (the gate's own definition) is owned, so work merges autonomously on a green gate while gate-defining changes need a human. **No `* @OWNER`. Replace `@OWNER`** with your human team. | committed to the target repo's `.github/CODEOWNERS` |
| [`dependabot.yml`](dependabot.yml) | 3-day-cooldown dependency policy (pip + npm + github-actions), grouped, security-toggle-OFF. | committed to `.github/dependabot.yml` |
| [`pre-commit-config.yaml`](pre-commit-config.yaml) | The cheap local gate (hygiene + detect-secrets + actionlint + shellcheck + ruff + bandit) before the CI round-trip. | committed to `.pre-commit-config.yaml` |
| [`gitignore`](gitignore) | The canonical ignore baseline for local machine artefacts and build/test caches, including `.DS_Store`. | committed to `.gitignore` |
| [`agent-sdlc-access-and-hitl.md`](agent-sdlc-access-and-hitl.md) | The canonical SDLC-access + HITL standard: capability (per-agent GitHub Apps) vs enforcement (the gates a human owns). | read + apply per repo |
| [`agent-app-manifests/`](agent-app-manifests/) | The canonical per-agent GitHub App set (`tc-agent-builder`/`shape`/`consultant`/`growth`) with tiered permissions. Minted by the `agent-token` CLI + `github-app-token` action (`--agent`/`agent:`). | one App created per manifest by the org owner |

These are a **starting baseline** — a repo trims/extends them (drop `npm` if it
ships no JS; add repo-specific CODEOWNERS paths or pre-commit hooks). The
ruleset's required-check contexts are the Golden Path contract and should not be
weakened.

Branch protection is applied at the **org** level — no repo commits its own `main`
ruleset — so every repo enforces the same gate. The fitness gate itself lives in
[tc-fitness](https://github.com/three-cubes/tc-fitness); the reusable CI that
produces the required `Quality gate` (and `no-attribution`) checks lives here in
[tc-pipelines](../README.md).

The bar those checks must meet for a repo to run **autonomously** (0 approvals on work) is
the [**Gate-Hardening Standard**](gate-hardening.md) — harden a repo's gate to it and verify
it runs green *and deterministic* **before** flipping that repo to 0-review.
