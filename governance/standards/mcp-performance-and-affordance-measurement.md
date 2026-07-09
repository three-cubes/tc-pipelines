---
type: standard
status: adopted
date: 2026-06-29
last_reviewed: 2026-06-30
operationalises: affordance-assurance standard (the "Measured" property)
operationalised_by:
  - capability-health-probe (--perf)
  - mcp_affordance_lint check
  - mcp_utilization_audit check
  - skill_mcp_affordance_linkage check
---

# Capability performance + agent-affordance measurement

Operationalises the fifth property of the affordance-assurance standard — **Measured** — for **every capability surface an agent reaches**: skills, plugins, native tools, and the MCP services that back them. The first four properties (discoverable / reachable / invocable / fit) already have probes; this standard makes *performance* and *agent UX/affordance* measurable, so an under-performing or low-affordance capability is caught the same way a broken one is.

**Scope.** The contract — a declared latency budget, an affordance score, and a utilisation signal — applies to every capability surface. The MCP service surface is the **reference implementation**: its plumbing (`mcp-tool-kit` telemetry, `capability-health-probe.py`) already exists, so the gates land there first and the mechanics below are written against it. A skill, plugin, or native tool inherits the same `perf` budget through its ToolPack binding and the same affordance/utilisation scoring; where a mechanic names an MCP construct (`defineTool`, `ToolCallEvent`), read it as "the equivalent surface for that capability class." The design contract this measures is the capability-product standard §"Performance contract" + §"Runtime verification".

## Intent

MCP tools and the skills that front them are the agent's affordance surface — how an agent discovers and does work. A capability that is **slow to wake, slow to answer, hard to choose, or unpredictable on failure** is one an agent abandons (typically falling back to a general LLM answer or to `kairix search`). The cost is invisible to humans and to per-call telemetry, so it goes unmeasured and uncorrected.

The hypothesis this standard exists to test, continuously: *the MCP services are under-utilised because they (a) take too long / are non-performant, or (b) do not give agents confidence, direction, and predictability.* That decomposes into three falsifiable questions, each with its own signal:

| Question | Signal | Where from |
|---|---|---|
| Is it **slow**? | latency distribution vs an SLO budget | synthetic cold-start probe + warm `latency_ms` telemetry |
| Does it give **confidence / direction / predictability**? | an affordance score per tool + skill | static lint (every push) + LLM-judge (sampled) |
| Is it **used at all**? | invocation count per tool per agent | telemetry aggregation — `calls == 0` is the strongest evidence |

These are not a new framework. The plumbing already exists and is unwired: the `mcp-tool-kit` helper emits a `ToolCallEvent{tool, agent, outcome, latency_ms, coerced_fields, dropped_fields, error_code}` through a pluggable `setTelemetrySink` (default JSONL); `capability-health-probe.py` already runs `initialize` + `tools/list` over the live transport with a monotonic deadline and discards the number. "Measured" is a sink-wire plus a handful of scripts away — never a parallel system.

## Axis A — Performance

### Metrics (per tool, per call)

| Metric | Source | Why it matters |
|---|---|---|
| **cold-start latency** — process up → `initialize` ok → `tools/list` | synthetic probe (`capability-health-probe.py --perf`) | stdio servers stay warm for the gateway-session life, so this is paid ~once per session per server — but a 2–3s wake is the first-use tax that erodes confidence |
| **warm per-call latency** — `latency_ms` p50/p95/p99 | `ToolCallEvent.latency_ms` on real calls | the real abandonment trigger: high p95 → the agent stops reaching for the tool |
| **result size** — bytes/tokens of the result `content` | new `result_bytes` on `ToolCallEvent` | oversized blobs burn the agent's context — a *perceived* slowness/UX cost even when the call is fast |
| **outcome mix** — ok / ok-with-notes / invalid-input / handler-error | `ToolCallEvent.outcome` | error rate is the predictability signal |

### SLO budgets (declared by category, inherited by default)

SLOs live in the ToolPack manifest (the ToolPack manifest schema gains a `perf: {category, slo_ms, probe_tool}` block), defaulted by category so most tools inherit and only outliers override:

| Category | warm p95 | cold-start | Examples |
|---|---|---|---|
| read / search / list / get | **1000 ms** | < 2.5 s | `dex` search, `kairix` search, `sharepoint` find |
| write / create / update / send | **2000 ms** | < 2.5 s | `delivery-management` specify, `outlook` send |
| fast-render / batch / upload | **5000 ms** | < 3 s | `powerpoint` upload, `render` office→pdf |
| long-running synthesis / generate | **45000 ms** | < 3 s | `image_generate` (single + batch), video render, large multi-slide deck render |
| health / handshake | **500 ms** | < 2 s | `tools/list` |

The **long-running synthesis / generate** band exists so a healthy generate is not
flagged as a breach: `image_generate` runs ~26 s and a batch ~26 s, well over the
fast-render budget but normal for the work. Video and large-render capabilities
inherit this band. A capability declares its band in its `perf.category`; the gate
measures it against the band's budget, not against a one-size budget.

### Where measured / gated

- **Deploy-time (blocking on what we own):** `capability-health-probe.py --perf` times spawn + handshake and invokes the manifest's declared `probe_tool` per server. **Cold-start and handshake breaches block** the capability-apply verify step; a >15% warm-probe regression vs the recorded latency baseline blocks. The per-call SLO is **alert-tier only** at ops time — a slow external API (Graph/Dex rate limit) must never become a deploy-blocking false-positive that teams route around.
- **Ops-time (alert):** the existing health-sweep cron runs `--perf` hourly → the ops dashboard + the alert webhook on breach.
- **Continuous (truth):** warm p95 per tool comes from real agent calls via the telemetry sink. The synthetic probe is a regression tripwire measured against the tool's own prior baseline (so external-API variance cancels); production telemetry is the verdict.

## Axis B — Affordance

Score each **tool** *and the skill that wraps it* 0–2 on four dimensions (max 8). The dimension names are the operator's words for what an agent needs:

| Dimension | 0 | 1 | 2 |
|---|---|---|---|
| **Confidence** — knows what it gets back | opaque blob / undocumented result | prose, no example or result shape | description + example + explicit success/result shape ("`status: ok` → `{id,name}`; check field X") |
| **Direction** — knows when to use it | no "when to use" | overlaps a sibling tool, ambiguous | "Use when…" + contrast with the alternative + a realistic example |
| **Predictability** — knows what failure means | raw exception / generic "failed" | structured `{code, what}` only | full `{code, what, hint, fix, next, run}` per the agent-actionable-feedback standard + a recovery example |
| **Discoverability** — intent-named | leaks implementation (`click`, `fill`, `kv_read`, `-ts`) | intent-aligned but jargon/ambiguous | business-verb name, no language/impl suffix per the naming-for-agent-affordance standard |

**Two-tier judging — both, by cost:**

- **Tier 1 — static lint, every push (the `mcp_affordance_lint` check):** parses every `defineTool` / `@async_tool_handler` and scores the *structural* half deterministically — name regex vs the naming standard (Discoverability), presence of `defineErrorMapping`/`tryHint` + required error fields (Predictability), presence of `examples` + a non-empty result schema (Confidence floor), a "Use when" clause in the description (Direction floor). Baselined in a ratcheted affordance-score baseline (no regression; a new tool must score ≥ 6/8) — the same shape as the contract-test baseline.
- **Tier 2 — LLM-judge, sampled (weekly):** extends the existing deliverable-judge eval harness with a tool-affordance rubric. It reads the tool description + a real success result + a real error envelope (pulled from the telemetry JSONL) and grades the *semantic* half: does the description actually give direction; is the error actually actionable for the next step. Score ≥ 0.6 to pass; regressions route to the skill/MCP owner via Linear.

The tiers are complementary: lint catches "no `tryHint`"; the judge catches "`tryHint` present but useless." `mcp-dex` is the gold reference fixture (high on all four); `mcp-browse` interact (`click`/`fill`/`press`) and `mcp-x` raw-JSON results are the regression fixtures the rubric must score low. The skill `affordance.md` template gains two required sections — **Result shapes** ("success looks like `{…}`, check field X") and **Common errors + recovery** — the confidence/predictability signals the current template omits.

## Utilisation — are agents actually calling each tool?

The strongest and cheapest evidence. The `ToolCallEvent` already fires; it has no production sink. Wire `setTelemetrySink` to append to the telemetry JSONL path the tool-ux-contract already declares (e.g. `/data/state/tool-friction/<date>.jsonl`) and mirror an OTel `tool.invoked` span → App Insights (the sink the ops dashboard already reads); `agent` populates from the gateway's per-agent identity (ADR-020).

The `mcp_utilization_audit` check aggregates per `(agent, tool)`:

- **`calls_30d`** — `== 0` for a tool bound in an *active* ToolPack (after a 30-day grace) is the headline finding: a declared-but-dead capability. It's broken (route / affordance / latency) or it should be retired. Enforced as a **warning-tier** fitness function — the direct test of the under-utilisation hypothesis, immune to SLO/probe variance.
- **`abandonment_rate`** — invoked, then immediately followed by a `kairix`/fallback call in the same agent turn = "tried it, didn't trust it."
- **`error_rate` vs SLA, `p95_latency` vs SLO, top `coerced_fields`/`dropped_fields`** — which tools force agent rework.

## The skill layer — intent → ToolPack → MCP → skill

Raw-tool scores are necessary but not sufficient: an agent reaches a tool *through* a skill and a ToolPack route, and friction at any seam reads as "the MCP is bad." The `skill_mcp_affordance_linkage` check (extends `skill_maturity_ledger`, a sub-gate of the capability-product Runtime Affordance Contract) walks the whole path and asserts: **route truth** (every skill claiming an MCP capability has a ToolPack `route_test` landing on the real `mcp-<server>__<tool>`); **reachable-when-claimed** (a deployed skill's bound MCP passes the health probe); **no affordance divergence** (the skill's "Use when"/inputs/outputs don't contradict the MCP tool — an LLM-judge sub-check); **error continuity** (skill recovery routes through the MCP's real `error.code`s). SLO + utilisation propagate to the skill view in the ops dashboard, so a slow MCP surfaces as a slow *skill* — how the agent and operator actually experience it.

## Convergence — what each piece extends (not a parallel framework)

| New piece | Extends |
|---|---|
| `--perf` latency probe | `capability-health-probe.py` (already times the handshake) + this standard's SLO section |
| `perf{category,slo_ms,probe_tool}` block | the ToolPack manifest schema |
| latency + cold-start baseline / regression gate | the baseline ratchet (same pattern as the contract-test gate) |
| `mcp_affordance_lint` (Tier 1) | the naming-for-agent-affordance standard + the existing actionable-feedback `tryHint` coverage check |
| tool-affordance LLM rubric (Tier 2) | the deliverable-judge eval harness |
| sink wiring + `mcp_utilization_audit` | `mcp-tool-kit` `setTelemetrySink` + the tool-ux-contract JSONL path + the ops dashboard (already reads App Insights) |
| `skill_mcp_affordance_linkage` | `skill_maturity_ledger` + `toolpack_route_tests_pass` + capability-product Runtime Affordance Contract |

Net new code: ~3 scripts + one sink wire + two schema/template fields. Net new framework: zero.

## The cheap first probe (run first, ~1 day, no gates)

1. **Wire the sink for one week** (reversible toggle — the events already fire). After five working days there are real `(agent, tool, latency_ms, outcome)` rows → utilisation + warm-latency straight from production behaviour. This is the decisive test of the hypothesis.
2. **Cold-start sweep** — spawn each stdio server, time spawn → `initialize` → `tools/list`, print a sorted table (`capability-health-probe.py` with a `time.monotonic()` print).
3. **10-tool affordance spot-judge** — hand the existing eval judge 10 tools (gold: `dex`, `delivery-management`; suspected-weak: `browse` click, `x` bookmarks, `sharepoint` find; + 5 random) with the rubric, to calibrate it and check whether weak affordance correlates with low utilisation.

The output is one table — `tool | calls_30d | warm_p95 | cold_start | affordance_score` — that confirms the hypothesis (dead / slow / low-affordance tools cluster) or refutes it (tools are used and fast → look elsewhere). That table is the business case for building the gated version.

## Baseline snapshot — example cold-start sweep

First-use cost, spawn → `initialize` → `tools/list`; `tools/list` once warm is 3–9 ms throughout (the cost is the spawn, not the protocol):

| Band | Servers (cold-start) |
|---|---|
| Fast < 0.8 s | `x` 335 ms · `render` 384 ms · `image-gen` 653 ms · `browse` 715 ms |
| Medium 1.4–1.9 s | `delivery-management` 1.4 s · `dex` 1.5 s · `apple-calendar` 1.6 s · `spreadsheet` 1.9 s |
| Slow 2.4–2.9 s | `powerpoint` 2.4 s · `outlook` 2.6 s · `sharepoint` 2.9 s |

`mcp-kairix` is HTTP (`streamable-http`, `:8090/mcp`) — no per-session spawn; measure warm per-call + connection setup, not stdio cold-start. Tool-surface size is its own affordance/context cost: `powerpoint` 21 tools / 18 KB, `browse` 23 / 14 KB. Per-tool utilisation is **not yet available** — wiring the sink (step 1) is the prerequisite.
