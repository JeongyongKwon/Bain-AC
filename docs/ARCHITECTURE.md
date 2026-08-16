# Architecture

A strategy panel that takes a market research report and returns a defensible recommendation — built as ten agents with a verification spine, an isolation rule, and a challenge function.

---

## The design problem

Three requirements shaped every decision here, and they pull against each other.

**Independent perspectives.** Seven practice lenses must reach their own conclusions. If they see each other's work while forming a view, they converge — the second agent anchors on the first, and by the seventh you have one opinion wearing seven hats. The disagreements are the product; a panel that agrees with itself has told you nothing you could not have got from one agent.

**No hallucination.** MBB work is defensible or it is worthless. A number a client cannot trace to a source is a liability, and one wrong figure in a steering committee costs more credibility than the whole deck buys.

**Recurring, weekly.** Which means the cost of a round matters, and — less obviously — the panel must be honest about weeks where nothing happened.

These are in tension. Independence multiplies cost. Verification multiplies cost further. Weekly cadence multiplies it again. The architecture resolves this by making verification a **shared, once-per-round asset** rather than something each lens redoes, and by making quiet weeks genuinely cheap.

---

## Two axes, not one

The initial instinct for a panel like this is corporate functions: Finance, HR, Legal, IT. That is the wrong decomposition for a strategy team, because it mirrors an org chart rather than the structure of a strategic question.

An engagement team is organised on two orthogonal axes:

- **Craft roles** — what you *do*. Partner, Engagement Manager, Consultant, Research & Data Services.
- **Practice lenses** — what you *know*. Strategy, Commercial, Corporate Finance, Operations, Organization, Digital, Risk.

This system implements both. The seven lenses supply the domain views; four craft roles supply the discipline that turns seven views into one answer.

| Agent | Axis | Owns |
|---|---|---|
| `/panel` skill *(the Engagement Manager)* | Craft | Scoping, dispatch, quality control |
| `research-desk` | Craft | The verified fact base — the only citable source of numbers |
| `lens-market-strategy` | Lens | Market definition, sizing, competitive structure |
| `lens-commercial` | Lens | Demand, segmentation, pricing, customer economics |
| `lens-corporate-finance` | Lens | Unit economics, valuation, capital, value creation |
| `lens-operations` | Lens | Cost-to-serve, capacity, supply chain |
| `lens-organization` | Lens | Capability gaps, time-to-capability, incentives |
| `lens-digital-tech` | Lens | Technology displacement, data position, build/buy |
| `lens-risk-regulatory` | Lens | Regulatory trajectory, downside, tail scenarios |
| `red-team` | Craft | Adversarial challenge across all lenses |
| `partner-synthesis` | Craft | Conflict resolution, the recommendation |

The Engagement Manager is the `/panel` skill itself rather than a subagent. It needs to see every phase's output to quality-control it, which is exactly what the orchestrating context already does — making it a subagent would add a hop and lose the visibility.

---

## The pipeline

```
  ┌─────────────────────────────────────────────────────────────┐
  │ PHASE 0   Engagement Manager (the /panel skill)             │
  │           reads report + context → writes 00-brief.md       │
  └────────────────────────────┬────────────────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ PHASE 1   research-desk                        [BLOCKING]   │
  │           verifies every claim → 01-fact-base.md            │
  │                                → 01-contradictions.md       │
  └────────────────────────────┬────────────────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ PHASE 2   seven lenses, PARALLEL and MUTUALLY BLIND         │
  │  ┌────────┬────────┬────────┬────────┬────────┬─────┬─────┐ │
  │  │ market │ comm'l │ corpfin│  ops   │  org   │ tech│ risk│ │
  │  └────────┴────────┴────────┴────────┴────────┴─────┴─────┘ │
  │           each cites F-ids only → lenses/*.md               │
  └────────────────────────────┬────────────────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ PHASE 3   red-team — first agent to see everything          │
  │           attacks all seven → 02-red-team.md                │
  │           HIGH finding with a closable gap ──┐              │
  └────────────────────────────┬─────────────────┘              │
                               │        re-verify + re-run lens │
                               │◄───────────────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ PHASE 4   partner-synthesis                                 │
  │           → 03-conflict-map.md  (mechanical, no opinion)    │
  │           → 04-partner-synthesis.md  (the deliverable)      │
  └────────────────────────────┬────────────────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ PHASE 5   Engagement Manager QC — untagged-number scan,     │
  │           structure check, conflict test, [R-] test         │
  └─────────────────────────────────────────────────────────────┘
```

### Why Phase 1 blocks

This is the load-bearing decision in the whole design. If lenses ran before the fact base existed, each would need to verify claims itself — seven agents doing the same web searches, reaching seven slightly different numbers for the same quantity, with no shared reference to reconcile them against. Worse, an agent under time pressure with no verified source available will reason its way to a plausible figure. That is the hallucination path, and it opens the moment a lens is allowed to run unsourced.

Blocking here costs one sequential step and buys a single shared set of numbers that every downstream agent cites by ID.

### Why Phase 2 is blind

Parallelism here is not primarily an optimisation — it is what enforces the isolation. Seven agents dispatched in one message cannot read each other's output because none of it exists yet. The independence is structural rather than a rule an agent has to remember to follow.

### Why Phase 3 exists separately

The red team is the first agent permitted to see everything, and cross-lens contradiction is its richest seam. Folding this into synthesis would be a mistake: the Partner's job is to *decide*, and an agent that has just spent its effort attacking the work is poorly positioned to then back a conclusion drawn from it. Separating challenge from decision is standard MBB practice for the same reason.

---

## The evidence contract

Full specification in [`HOUSE-STANDARD.md`](HOUSE-STANDARD.md). The core of it:

Every quantified claim carries a tag. `[F-012]` means verified — the Research Desk found a source, recorded the URL, the access date, and the verbatim supporting sentence. `[R-p14]` means the input report asserts it on page 14 and **nobody has checked**. `[C-path]` is internal context. `[EST: method]` is the agent's own estimate with a reproducible derivation. `[ASSUMPTION]` is a knowingly-unevidenced premise.

The `[F-]` versus `[R-]` distinction does most of the work. Collapsing them is how a strategy team ends up confidently reselling a client's own marketing claims back to them. **Only the Research Desk can promote `[R-]` to `[F-]`** — a lens that wants a claim verified has to ask, which keeps a single agent accountable for the fact base's integrity.

Facts are graded A through D by provenance, plus `U` for unverified. A `U` grade is a finding, not a failure: when a report's central market-size figure cannot be corroborated, that tells you something important about the report.

Enforcement is at Phase 5, with a grep for numbers lacking tags. Mechanical, cheap, and it catches the drift that creeps in when an agent is writing fluently.

---

## Cost

*Estimates below are modelled from published token pricing and expected context sizes — they are `[EST]` by this system's own standard, not measured. Run three rounds and replace them with observed figures.*

Model assignment reflects where capability actually pays back:

| Agent | Model | Reasoning |
|---|---|---|
| `research-desk` | Opus 5 | Verification discipline — knowing when a source does *not* support a claim is the hard part |
| 7 lenses | Sonnet 5 | Near-Opus on structured analytical work; this is 70% of round volume |
| `red-team` | Opus 5 | Finding the broken middle step in a well-written argument |
| `partner-synthesis` | Opus 5 | Judgment under conflicting evidence |

Per full round, at Opus 5 ($5/$25 per MTok) and Sonnet 5 ($3/$15):

| Phase | Est. cost |
|---|---|
| Research desk | ~$1.60 |
| Seven lenses | ~$3.15 |
| Red team | ~$1.15 |
| Partner synthesis | ~$1.10 |
| **Full round** | **~$7** |
| Delta review (quiet week) | ~$1.50 |

A realistic month — one new report plus three delta reviews — lands around **$12**. Running every agent on Opus 5 raises a full round to roughly $9.

Two levers if cost becomes a constraint: move `red-team` to Sonnet 5 (saves ~$0.70/round, some loss in challenge quality), or drop to a five-lens roster for routine reports. Do not economise on the Research Desk — it is the cheapest phase and the one everything else depends on.

### Why not a vector database

For a context corpus under a few thousand pages, file-based agentic search — `grep`, `glob`, and an accurate `INDEX.md` — outperforms retrieval. Opus 5 and Sonnet 5 both carry a **1M token context window**, and each subagent gets its own, so seven lenses have seven independent windows rather than seven slices of one. A retrieval layer would add infrastructure, index staleness, and chunk-boundary errors in exchange for solving a capacity problem that does not exist at this scale.

The interface is retrieval-shaped anyway: agents ask the index what exists and open what they need. If the corpus ever outgrows the approach, an embedding index slots in behind `INDEX.md` without touching a single agent prompt.

**Prompt caching note:** concurrent requests sharing a prefix all miss the cache, since none can read what the others are still writing — so the seven parallel lenses do not share cached context. This costs nothing here, because the file-based design means each lens reads only its own slice plus the shared brief, rather than a large common prefix.

---

## Weekly cadence

A weekly round on a report that has not changed produces noise. The `/panel` skill handles this with a **delta review**: read the previous synthesis's "what would change our view" triggers, dispatch only the Research Desk to check whether any has fired, and stop if none has.

This is the discipline that keeps a recurring panel credible. A panel that manufactures findings to justify its schedule stops being read within a month — and the failure is silent, because the reports keep arriving.

---

## Extending the roster

Adding a lens is one file in `.claude/agents/` plus one line in the `/panel` skill's Phase 2 dispatch list. Copy an existing lens and change three things:

1. **The question it owns** — stated as something the other lenses demonstrably do not cover
2. **The number it owns** — its section 4; one figure it contributes to the decision
3. **Where it stops** — explicit handoffs, so it does not write another lens's section

That third item does the most work. Lenses without a stated boundary drift toward general commentary, and six agents all writing general commentary is a worse panel than four with sharp edges.

Industry lenses (Healthcare, Financial Services, Industrials) work the same way and can be swapped in per engagement — keep the practice lenses standing and rotate the industry one.
