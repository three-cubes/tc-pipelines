# Engineering NFR Standard — the non-functional checklist every design must clear

> Every ADR, design note, or capability that adds or changes a runtime surface MUST reason
> explicitly about the six non-functional dimensions below. A design that names only the happy
> path is **incomplete** — return it. This standard is the checklist; the
> [architecture-decision-method](architecture-decision-method.md) is where it is applied.

## Why

Defects and cost overruns land in the dimensions a design leaves unstated. "It works" answers
one dimension (functional correctness) and silently defers the other six to production. Naming
each dimension — even to say "not applicable, because X" — forces the trade-off into the open
where a reviewer can challenge it, and gives the next agent a decision it can act on instead of
rediscover.

## The six dimensions (cover every one, or state why it is out of scope)

| Dimension | The question the design MUST answer | Evidence a reviewer looks for |
|---|---|---|
| **Cost / licensing** | What does this cost to run and to own? Per-request, per-month, and at 10×. Any new dependency's licence (permissive vs copyleft vs commercial) and whether it obliges anything. | A named cost driver + rough magnitude; licence of each new dep; the cheaper option considered and why rejected. |
| **Security** | What is the new attack surface? Authn/authz on every new entry point; secret handling; injection/SSRF/path-traversal exposure; least-privilege on any identity or grant. | Threat named + mitigation; no secret in code/logs; scopes are the minimum that works. |
| **Performance / scalability** | What is the latency/throughput budget, and where does it break? Behaviour at expected load and at 10×; the bottleneck resource; back-pressure when it saturates. | A stated budget (e.g. read ≤1 s, write ≤2 s) + the limiting resource + degradation mode. |
| **Reliability** | What happens when a dependency is slow, down, or returns garbage? Timeouts, retries (bounded, idempotent), failure isolation, the recovery point. | Every external call has a timeout + failure path; no unbounded retry; blast radius named. |
| **Operability** | How is this observed, deployed, and rolled back? The signal that tells an operator it is unhealthy; the deploy + rollback path; the runbook entry. | A named health signal/log/metric; a rollback that is faster than rebuild; actionable failure messages (`fix:`/`next:`). |
| **Privacy** | What data does this touch, where does it flow, and who may see it? Classification of any personal/client data; residency/retention; whether it crosses a trust boundary (external service, third-party API, artifact). | Data classified; no internal/client content sent to an external surface without explicit consent; retention stated. |

## Depth is proportional to reversibility

A **one-way door** (data model, external contract, security boundary, a dependency you cannot
easily drop) MUST cover all six dimensions with evidence. A **two-way door** (an easily reverted,
internal, low-blast-radius change) MAY dispatch a dimension in a sentence — but still name it.
When in doubt, treat it as one-way.

## No unsourced quantitative claims

Every number that defends a decision (a latency budget, a cost figure, a load estimate, a "this
is typical") MUST carry an inline source — a measurement, a vendor doc, a prior incident. "Typical",
"normal", and "should be fine" are red flags: replace the label with a cited fact or delete the claim.

## How to apply

1. **Author** — before writing the decision, walk the six-row table. For each row, write one to
   three sentences: the answer, or "out of scope because X". Delete nothing silently.
2. **One-way doors** — attach evidence (a measurement, a threat + mitigation, a cost driver), not
   an assertion. Cite every number.
3. **Reviewer** — a design missing a dimension, or defending a decision with an unsourced number,
   is **not done**. Ask for the row, not a rewrite.
4. **Enforce** — where a repo wants machine backing, add a fitness function that fails an ADR/design
   doc which omits the NFR section (a `design_covers_nfrs`-style structural check). The checklist is
   the contract; the gate makes it non-optional.
