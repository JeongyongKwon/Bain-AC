# Bain-AC — Strategy Panel

A multi-agent strategy panel. Give it a market research report; it returns a fact-checked, multi-lens review and one defensible recommendation.

Built as ten agents modelled on an MBB engagement team: a Research & Data Services desk that owns the verified fact base, seven practice lenses that read the report independently, a red team that attacks their work, and a Partner who decides.

> 한국어: [`README.ko.md`](README.ko.md)

## Run a round

Two runtimes, one shared set of agent definitions.

**Python CLI** — headless, for schedulers and CI:

```bash
pip install -e ".[dev,claude-agent-sdk]"   # dev = pytest; claude-agent-sdk = the default runner

panel run inbox/report.pdf --lang ko    # reports written in Korean
panel run inbox/report.pdf --dry-run    # show the plan, spend nothing
panel run inbox/report.pdf --runner mock  # exercise the full pipeline offline, free
panel roster                            # loaded agents and the phase graph
panel runners                           # available model-API backends
panel qc reports/2026-08-16-report      # re-check a completed round
```

The model API is swappable — `panel/pipeline.py` never imports a provider SDK directly, only the `AgentRunner` interface in `panel/runners/`. `claude-agent-sdk` is an *optional* dependency for exactly this reason: `pip install -e ".[dev]"` alone gets you the orchestrator, the agent loader, and the `mock` runner, with nothing Anthropic-specific required. See `docs/ARCHITECTURE.md` § Swappable model backend.

**Claude Code** — interactive:

```
/panel inbox/some-market-report.pdf
```

Output lands in `reports/YYYY-MM-DD-<slug>/`. The deliverable is `04-partner-synthesis.md`; everything else is the audit trail behind it.

## First-time setup

1. **Fill in `context/00-core-brief.md`.** Every agent reads it every round. Two pages, replacing the template.
2. **Add context files** under `context/*/` and register each one in `context/INDEX.md`. Start with whatever you have — the panel works with a thin context pack and gets sharper as it fills.
3. **Read `docs/HOUSE-STANDARD.md`.** It is the evidence contract the agents work to, and it is what you should hold their output against.

## How it works

```
report → fact base → 7 blind parallel lenses → red team → Partner synthesis
```

The design turns on three choices:

- **The fact base blocks everything.** No lens runs until claims are verified and graded, so no lens has to invent a number to fill a gap.
- **The lenses are blind to each other.** Dispatched in parallel, so none can read another's conclusion and anchor on it. Their disagreements are the product.
- **Challenge is separate from decision.** The red team attacks; the Partner decides. An agent that has just attacked the work is badly placed to then stand behind it.

Full reasoning in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## The evidence rule

No bare numbers. Every quantified claim carries a tag showing where it came from:

| Tag | Means |
|---|---|
| `[F-012]` | Verified — source, URL, access date, verbatim quote in the fact base |
| `[R-p14]` | The report says so on p.14. **Not verified.** |
| `[C-finance/unit-econ.md]` | From our internal context pack |
| `[EST: method]` | An estimate, with a reproducible derivation |
| `[ASSUMPTION]` | A knowingly unevidenced premise |

`[F-]` versus `[R-]` is the distinction that matters. One means someone checked; the other means the report asserted it. A recommendation resting on `[R-]` is flagged, not hidden.

## Layout

```
.claude/agents/       ten agent definitions — the single source of truth
.claude/skills/panel/ the /panel orchestrator (Claude Code)
panel/                Python runtime — pipeline, agent loader, QC verifier
panel/runners/         the provider boundary — AgentRunner interface + implementations
tests/                40 tests (pytest)
context/              your offline context pack; INDEX.md is the manifest
docs/                 HOUSE-STANDARD.md (evidence contract), ARCHITECTURE.md
docs/ko/              Korean documentation
inbox/                drop new reports here
reports/              round outputs
```

The markdown in `.claude/` is executable configuration — its YAML frontmatter
enforces model routing and tool permissions at runtime, and `panel/agents.py`
loads the same files into SDK objects. A strategist can retune a lens prompt
without touching Python, and both runtimes pick up the change.

## Development

```bash
python3 -m pytest tests/ -q     # 64 passed — no API key or network needed; the `mock` runner covers the rest
```

`panel/verify.py` is pure functions with no model calls. If the evidence-contract
check were itself an LLM call, it would inherit exactly the failure mode it
exists to catch.

## Cost

A full round is roughly **$7**; a quiet-day delta review about **$1.50**. Lens agents run on Sonnet 5, the Research Desk / Red Team / Partner on Opus 5 — change the `model:` line in any `.claude/agents/*.md` to shift the balance. At **daily** cadence the delta review's cost is the one that dominates the monthly bill (~30 of them a month, not ~3), landing a realistic month around **$67** rather than the ~$12 a weekly schedule would cost. Full cost model in `docs/ARCHITECTURE.md`.

## Daily rounds

With no new report, `/panel` runs a **delta review**: it checks only whether any trigger from the last synthesis has fired, and reports that nothing changed if nothing did. At daily frequency, most days *are* quiet — a recurring panel that manufactures findings to justify its schedule burns trust within the first week.

**Status:** this delta-review logic exists in the `/panel` skill for the Claude Code path. It is not yet implemented in `panel/pipeline.py` — the Python CLI's `run` command always executes the full pipeline, so unattended daily scheduling (cron/CI) needs that branch built first.
