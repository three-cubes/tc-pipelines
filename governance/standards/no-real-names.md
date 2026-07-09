---
type: standard
status: adopted
date: 2026-05-17
owner: platform
applies_to:
  - all-engineering
  - all-agents
purpose: >
  Synthetic test-data rules. Test fixtures, examples, and sample artefacts must
  use synthetic names. Real client / person / company names belong only in
  authoritative identity files (agent configs, BDD scenarios that name the
  agent itself), ADRs and runbooks that genuinely document live work, and
  user-auto-memory — never in fixtures.
---

# No real names in fixtures

## Why

Test fixtures and examples leak. They get screenshotted, pasted into issues,
copied into demos. Using real client names (Bupa, Avanade), real person names
(Dan McMahon, family members), or recognisable third-party brands (Microsoft as
a client example) in fixtures means anyone reading those fixtures sees real
relationships they shouldn't.

The rule: **fixtures use synthetic names from your repo's canonical mapping.**

## Canonical mapping table

Each repo keeps its own canonical mapping. The table below is an **illustrative example** — substitute the real names your repo needs to keep out of fixtures for synthetic stand-ins, and record the pairing so every author reaches for the same substitute.

| Real name | Synthetic substitute |
|---|---|
| Bupa | AcmeHealth |
| Avanade | NexusDigital |
| Three Cubes / 3CV | Triad Consulting |
| Dan McMahon | Alex Jordan |
| Microsoft (as a *client example*) | Softcorp |
| Helena / Ilaria / Ethan / Charlie / Tiger | Generic placeholder names; **never** family |

"Microsoft" only needs substitution when it's standing in as a fictional client
in a fixture. References to genuine Microsoft products (Azure, M365, etc.) in
runbooks or ADRs are fine — those describe real platform state, not fictional
deal scenarios.

## Scope of the rule

Your repo's no-real-names fixture check scans (for example):

- `tests/fixtures/**`
- `**/examples/**`

Anywhere else (ADRs, BDD scenarios that legitimately name a real agent target,
runbooks, the user memory directory) is out of scope — those are authoritative
records.

## Allowlist — per repo

Some files are intentionally allowed to reference real names — typically
because the file's purpose IS to document the real relationship (e.g. an
agent's BDD scenarios name the client that agent actually serves, because
that's the contract, not fixture data).

Each repo keeps its own allowlist, close to its own fixture check — commonly a
fenced code block inside the repo's copy of this standard, or a config list the
check reads. Paths are repo-relative. Lines starting with `#` are comments. An
illustrative entry:

```
# An agent's BDD scenarios name the agent's real scope — that's the contract,
# not a fixture. These are *not* synthetic test data; they're the
# specification of which real relationships each agent serves.
tests/bdd/agents/<agent>/scenarios.feature
```

To add a new path: append it inside your repo's allowlist, and explain in a
preceding `#` comment why the real-name reference is authoritative rather than
fixture data.

## How to use it

- Authoring a fixture? Use the substitutes from the mapping table.
- Importing a real document (PDF, contract) for testing? Sanitise it first —
  replace names with the synthetic substitutes; keep the structure.
- Got a legitimate exception? Add the path to your repo's allowlist with a
  comment explaining why.
