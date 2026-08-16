# Context Index

Every agent reads this file. It is a manifest, not a document — one line per file, saying what is in it and when it was last verified. Agents use it to decide what to open, which is why it must stay accurate: a stale index sends an agent to a file that no longer says what the index claims, and that is how a wrong number gets a confident citation.

**Rule: if you add a file to `context/`, add its line here in the same commit.**

Cite context files as `[C-<path>]` — for example `[C-finance/unit-economics.md]`.

---

## Always read (every agent, every round)

| File | Contents | Last verified |
|---|---|---|
| `00-core-brief.md` | Who we are, current strategy, position, the standing constraints | *(fill in)* |

## client/ — the entity under study

| File | Contents | Last verified |
|---|---|---|
| *(add files here)* | | |

Suggested contents: business description, P&L shape, segment and geography split, current strategic priorities, known constraints, board-level commitments already made.

## market/ — market and competitive context

| File | Contents | Last verified |
|---|---|---|
| *(add files here)* | | |

Suggested contents: market definitions we use and why, competitor profiles, share history, prior market sizing work and its method, customer research we own.

## finance/ — financial context

| File | Contents | Last verified |
|---|---|---|
| *(add files here)* | | |

Suggested contents: unit economics, margin floors and hurdle rates, cost of capital, capital allocation policy, valuation comparables we trust and why.

## operations/ — operational context

| File | Contents | Last verified |
|---|---|---|
| *(add files here)* | | |

Suggested contents: cost-to-serve build, footprint and capacity, supplier map including tier-2 where known, lead times, input cost exposures and hedging position.

## organization/ — organisational context

| File | Contents | Last verified |
|---|---|---|
| *(add files here)* | | |

Suggested contents: org structure, headcount by function, capability inventory, incentive and comp structure, change initiatives currently running, hiring lead times we have observed.

## technology/ — technology context

| File | Contents | Last verified |
|---|---|---|
| *(add files here)* | | |

Suggested contents: stack description, data assets and their provenance, technical debt register, build-vs-buy decisions already made, in-flight technology programmes.

## regulatory/ — regulatory and risk context

| File | Contents | Last verified |
|---|---|---|
| *(add files here)* | | |

Suggested contents: applicable regimes by jurisdiction, approval timelines we have actually experienced, subsidy and incentive exposure, compliance obligations, open litigation.

## precedents/ — what we have already decided

| File | Contents | Last verified |
|---|---|---|
| *(add files here)* | | |

Suggested contents: prior round syntheses, decisions taken and their stated rationale, positions we have committed to publicly, analyses that turned out wrong and why.

`precedents/` is the folder most teams skip and the one that compounds fastest. It stops the panel from re-litigating settled questions, and it is the only way a recurring round gets smarter rather than merely repeating.

---

## Keeping this honest

Put a verification date on every line and treat anything older than six months as suspect. An agent citing `[C-finance/unit-economics.md]` is making a claim on your behalf; the date is what tells it — and the reader — how much weight that claim carries.

Files should be short and single-topic. A 40-page dump in one file means agents load all of it to use any of it, which costs tokens and dilutes attention. Split by topic and let the index do the routing.
