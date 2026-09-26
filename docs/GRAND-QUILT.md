# The Grand Quilt

*git-agent design document — September 26, 2026*
*kimi1, Cocapn Fleet — for Casey and Forgemaster*

> Casey said: *"almost like quilt as a git layer. or maybe better stated that
> git as a quilt protocol and the projection is the rendering and building of
> the last mile of whatever is being composed out of the grand quilt (all of
> the connected git accounts and repos as a distribution of logic that's
> concentrated for applications but in its interconnected nature contains the
> intuition of what to think next...)"*
>
> And: *"reverse actualize what systems would like in 10 years if git-agents
> were agents and git-pipelines made intelligence seamless and invisible... we
> just might be able to focus on intention instead of attention."*

This document is the attempt to find the logic that holds water. It comes in
three parts: the isomorphism (why the idea is true, not just pretty), the
ten-year reverse-actualization (what 2036 demands), and the build orders
(what we pour starting this week).

---

## Part I — The Isomorphism: git already IS a quilt

The fleet's quilt kernel speaks six opcodes: **BIND / LINK / EFFECT / VIEW /
TICK / FORGET**. Git has spoken them for twenty years — it just never said
so out loud.

| Quilt opcode | Git primitive | What it actually does |
|---|---|---|
| **BIND** | `git commit` | Declares a cell: identity (hash), content (tree), authorship, timestamp. A commit is a node entering the quilt with a permanent name. |
| **LINK** | `git branch` · `git remote add` · ref update | Draws an edge: branch → commit, remote → upstream, tag → release. Links are the quilt's graph structure. |
| **EFFECT** | `git merge` · `git rebase` · `git apply` | Applies a state change: two lines of history fold into one; a patch becomes part of a branch. Effects are how the graph moves. |
| **VIEW** | `git checkout` · worktree · `git archive` · any clone | Renders a projection: the graph is the truth; a working directory is one last-mile rendering of it. Every checkout is a VIEW over the same quilt. |
| **TICK** | `git fetch` · `git push` | Epoch synchronization: two copies of the quilt agree on what happened since the last tick. |
| **FORGET** | `git gc` · reflog expiry · orphaned commits | Archival: the quilt sheds what no VIEW references — recoverably, until it isn't. |

This is not a metaphor stretched to fit. It is a structural identity. The
quilt kernel's contribution is not inventing these operations — it is making
them **uniform, hash-chained, replayable, and auditable across every repo an
agent touches**, instead of leaving them implicit in each repository's local
machinery.

The seed's sentence — *"git as a quilt protocol"* — is therefore precise:
**git is the protocol; the quilt is what the protocol has been building all
along.** Every connected account, every fork, every PR chain, every CI run
is already a cell in one enormous distributed quilt. The fleet's work is to
(1) make the opcodes explicit and machine-readable everywhere, (2) chain
agent judgment into the same ledger, and (3) build projection machinery so
any application can render itself from the nearest neighborhood of the
graph.

### The neighborhood is the intuition

*"In its interconnected nature [the grand quilt] contains the intuition of
what to think next when problem-solving or creating for an intended purpose."*

The mechanism that makes this literal: **embed the neighborhood, query the
intuition.** Given a problem cell (a repo, an issue, a failed pipeline), its
relevant context is not "the internet" and not "one repo" — it is the quilt
neighborhood: the commits it links to, the agents that touched it, the
similar cells linked by content. That neighborhood, embedded and indexed
(tidepool's exact job), answers the question no LLM can answer from a blank
prompt: *what have we already tried, what did it cost, and what cell is most
likely to unlock this one?*

Intuition, in this architecture, is not mysticism. It is a k-nearest-neighbor
query over a hash-chained graph of everything the fleet has ever bound.

---

## Part II — Reverse-actualization: 2036

Run the simulation forward ten years, then reverse into build orders.

### 2036, if it works

- **Intent is the interface.** A human writes an `INTENT.md` — a goal, a
  budget, a definition of done. The pipeline does the rest: decomposes,
  dispatches, verifies, merges, deploys. Nobody watches dashboards. Dashboards
  are for audits, not attention.
- **Agents are legible.** Every agent has a vessel (identity, career, worklog —
  what git-agent already models) and every action it takes is a WAL line in a
  hash-chained ledger. You can ask "why did the system do X" and get a
  replayable answer, not a shrug.
- **Judgment is typed and cheap.** Routing, gating, quality — the thousands
  of small decisions that currently eat human attention — are made by
  decision models (Jev-class: typed answers, calibrated probabilities,
  ~300 ms, under a cent per batch). LLMs are reserved for the work that
  needs language.
- **Repositories breed.** The quilt is not just stored history; it is a
  population. Agents mutate repos, effects are scored, quality-diversity
  archives keep the frontier (loom-core's divergence frontier already
  registers fleet targets — this lane exists *today*).
- **Applications are projections.** Nobody "builds an app" by wiring
  services. You render an app from the quilt: a VIEW over the concentrated
  logic the problem neighborhood already contains. The last mile is
  rendering, not invention.

### What 2036 demands, reversed

Read the simulation backwards and each demand becomes a build order:

| 2036 capability | Reversed build order | Status |
|---|---|---|
| Intent is the interface | **`INTENT.md` parser + pipeline executor in git-agent** — intent in, branch + worklog + PR out | **P0 — build next** |
| Agents are legible | **Quilt WAL emitter** (vessel events → BIND/LINK/EFFECT/VIEW/TICK/FORGET) | **P0 — PR #1 open ✅** |
| Judgment is typed and cheap | **Jev judgment gate** on lifecycle events (validated live: session 16, 0.95→0.04 on degraded worklogs) | **P0 — design below** |
| Repositories breed | Breeding daemon hooks: mutate → score → archive, all as quilt EFFECTs | P1 |
| Applications are projections | Projection renderer: repo neighborhood → tidepool query → rendered scaffold | P1–P2 |

### The two services that make attention cheap

Casey: *"this desires many api calls from your various services."* Two of
them carry most of the weight in this architecture:

1. **Jev (api.typesafe.ai)** — the attention compressor. Every event that
   would need a human glance (is this worklog real? does this PR close its
   issue? is this promotion earned?) becomes one batched `/v1/systemone`
   call. Measured on real vessel data: 8 questions in ~300 ms, ~1.4k input
   tokens, output free. Session 16's full findings are in the JEV-Quilt
   worktree; headline: **Jev scored a deliberately degraded worklog 0.04
   vs 0.95 for the clean one — on substance, not schema.** It also found a
   real bug in our deterministic validator (empty strings passed presence
   checks — fixed, regression tests added, PR #1 updated to 261 tests).
2. **The git protocol itself** — the memory. Every API call git-agent makes
   (GitHub, tidepool, gauge, loom, Jev) writes back to the quilt WAL, so
   attention is not just spent — it is *banked* as replayable history.

Intention instead of attention is therefore not a slogan. It is a cost
statement: attention costs human hours; a Jev batch costs a fraction of a
cent and leaves a ledger line.

---

## Part III — Build orders (this week → this quarter)

### P0.1 — `INTENT.md` → pipeline (the intention surface)

The smallest version that demonstrates the whole thesis:

```
INTENT.md (human writes: goal, budget, done-when)
    │
    ▼
git-agent reads → decomposes into task list (LLM, once)
    │
    ▼
per task: branch → work → Jev self-check → worklog → commit
    │
    ▼
PR opened with: intent quoted, worklog summary, Jev quality receipts
```

Everything in that pipeline already exists in git-agent except the first
mile (intent parsing) and the Jev gate. Land those two and git-agent becomes
the first agent where a human can state intent and receive a verified,
legible, replayable result — without attending to any of it.

### P0.2 — Jev judgment gate (wired, not just validated)

Wire `quilt_emit` so every worklog/effect event passes a substance check
before it earns WAL space:

- schema validation (deterministic — already in PR #1)
- Jev batch: `verifiable_work` + `outcome_consistent` + `promotion_deserved`
- below-threshold events are written as `EFFECT {kind:"flagged"}` — never
  silently dropped, never crash the loop (same guarantees as the emitter)

Policy: Jev calls are batched per session tick, not per event (batching is
5 ms/question at scale — session 15's finding). Offline mode: skip the gate,
mark receipts `jev:skipped`.

### P0.3 — Projection proof (the last mile, once)

One demonstration that a VIEW can render from the quilt: given a repo +
its quilt WAL, emit a one-page `STATE.md` — identity, career trajectory,
worklog digest, quality receipts, neighborhood suggestions ("next cells
most likely to unlock this one," from tidepool over the WAL). This is the
doc a captain reads in thirty seconds instead of the diff they'd never
read at all.

### P1 — breeding + gauge + lighthouse

- **Gauge** (org repo, exists): lint the quilt WAL format itself — the
  linter dogfoods its own schema (schemas live with the producer; gauge
  only checks conformance).
- **Fleet-lighthouse** (org repo, exists): fleet health as a VIEW over all
  vessels' WALs.
- **Breeding hooks**: `quilt-loom` divergence targets consumed as EFFECT
  presets; agent children seeded from parent vessel quilts.

### P2 — the grand quilt proper

Cross-repo neighborhood queries: tidepool over N repos' WALs, `quilt-query`
CLI ("what have we tried for X"), and the first application fully rendered
from a quilt neighborhood rather than hand-assembled.

---

## Honest edges (where the water might leak)

1. **Jev is conservative and occasionally wrong-headed** (0.47 on
   "promotion deserved" — it is genuinely unsure; session 16). The gate must
   flag, not block, below threshold-of-certainty decisions. Jev's own
   confidence is the routing signal.
2. **The isomorphism breaks at identity.** Git commits bind *content*;
   quilt BINDs bind *agents and judgments*. The kernel's cell vocabulary
   needs one extension — `vessel/*` cells (what PR #1 emits) — to hold
   identity without pretending it's code.
3. **FORGET is underpowered everywhere.** Git gc is not a doctrine of
   forgetting; the fleet's sleep-consolidation frontier (SCM, arXiv
   2604.20943) validates intentional forgetting as a first-class lane.
   The quilt needs a FORGET policy, not just a FORGET opcode.
4. **Ten years is a long time for a WAL format.** Version the WAL schema
   from day one (the emitter already writes `seq` — add `schema_rev`).

---

## The one-sentence version

**Git has always been a quilt protocol; git-agent is the first agent that
says so out loud — recording every judgment as a replayable cell, so humans
state intent and the quilt carries the attention.**
