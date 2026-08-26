"""The five-phase panel orchestrator.

Phase ordering is enforced here in Python rather than described in a prompt.
That matters for the two structural guarantees the architecture rests on:

  * the fact base blocks -- `await` on phase 1 means no lens can start before
    verified numbers exist, so none has to invent one to fill a gap;
  * the lenses are blind -- `asyncio.gather` dispatches all seven at once, so
    none can read another's output because none of it exists yet.

Neither depends on an agent remembering an instruction, and neither depends on
which model API is actually running the agents -- this module talks only to
the `AgentRunner` interface in `panel.runners`, never to a provider SDK
directly. See `panel/runners/base.py` for the boundary and `docs/ARCHITECTURE.md`
§ Swappable model backend for why it is drawn there.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path

from panel.agents import LoadedAgent, load_roster, validate_roster
from panel.config import PIPELINE, REQUIRED_AGENTS, Phase, RoundConfig
from panel.runners import AgentRunner, get_runner
from panel.verify import QCReport, run_qc


@dataclass
class AgentRun:
    """What one agent invocation cost and produced."""

    name: str
    seconds: float
    turns: int
    text: str
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class RoundResult:
    round_dir: Path
    runs: list[AgentRun] = field(default_factory=list)
    qc: QCReport | None = None

    @property
    def failed(self) -> list[AgentRun]:
        return [r for r in self.runs if not r.ok]

    @property
    def total_seconds(self) -> float:
        return sum(r.seconds for r in self.runs)


def build_task(agent: LoadedAgent, cfg: RoundConfig, phase: Phase) -> str:
    """The user-turn brief handed to an agent.

    Deliberately thin. The agent's own definition carries its method; this
    supplies only the round's coordinates. Summarising other agents' work here
    would leak across the isolation boundary.
    """
    rel_round = cfg.round_dir.relative_to(cfg.project_root)
    outputs = "\n".join(f"  - {p}" for p in phase.produces)
    return f"""Round directory: {rel_round}
Input report: {cfg.report_path.relative_to(cfg.project_root)}
Context pack: context/ (start with INDEX.md and 00-core-brief.md)
House standard: docs/HOUSE-STANDARD.md — read this first.

Write your output to, and only to:
{outputs}

Every quantified claim carries an evidence tag. A number without one is a
defect and will be sent back by the quality-control pass."""


async def run_agent(
    agent: LoadedAgent,
    cfg: RoundConfig,
    phase: Phase,
    runner: AgentRunner,
) -> AgentRun:
    """Invoke one agent to completion via the active runner.

    Owns nothing provider-specific -- system prompt, task, tool list, and
    model string go in as plain values; text and an optional error come back
    the same way, regardless of which `AgentRunner` is behind `runner`.
    """
    started = time.monotonic()
    try:
        outcome = await runner.run(
            agent_name=agent.name,
            system_prompt=agent.prompt,
            task=build_task(agent, cfg, phase),
            tools=agent.tools,
            model=agent.model,
            cwd=cfg.project_root,
            max_budget_usd=cfg.max_budget_usd,
        )
        return AgentRun(
            name=agent.name,
            seconds=time.monotonic() - started,
            turns=outcome.turns,
            text=outcome.text,
            error=outcome.error,
        )
    except Exception as exc:
        # A runner should return RunnerOutcome(error=...) for ordinary
        # failures. This catches the extraordinary ones -- auth, network,
        # a provider bug -- so one agent's crash cannot sink the round.
        return AgentRun(
            name=agent.name,
            seconds=time.monotonic() - started,
            turns=0,
            text="",
            error=f"{type(exc).__name__}: {exc}",
        )


async def run_phase(
    phase: Phase,
    roster: dict[str, LoadedAgent],
    cfg: RoundConfig,
    runner: AgentRunner,
    log,
) -> list[AgentRun]:
    """Run one phase, in parallel where the phase says so."""
    mode = f"{len(phase.agents)} agents in parallel" if phase.parallel else "sequential"
    log(f"\n── Phase {phase.number}: {phase.name} ({mode})")

    if cfg.dry_run:
        for name in phase.agents:
            log(f"   [dry-run] would dispatch {name} ({roster[name].model})")
        return [AgentRun(name=n, seconds=0.0, turns=0, text="") for n in phase.agents]

    tasks = [run_agent(roster[name], cfg, phase, runner) for name in phase.agents]

    if phase.parallel:
        runs = await asyncio.gather(*tasks)
    else:
        runs = [await task for task in tasks]

    for run in runs:
        status = "ok" if run.ok else f"FAILED — {run.error}"
        log(f"   {run.name:<24} {run.seconds:6.1f}s  {run.turns:>3} turns  {status}")
    return list(runs)


async def run_round(cfg: RoundConfig, log=print, runner: AgentRunner | None = None) -> RoundResult:
    """Execute a full panel round and return its result.

    `runner` defaults to `get_runner(cfg.runner)` -- pass one explicitly to
    inject a pre-configured instance (a `MockRunner` with canned responses,
    for instance) without going through the string-keyed registry. The CLI
    never passes this; it exists for tests and for callers embedding the
    pipeline in a larger program.
    """
    roster = load_roster(cfg.agents_dir, lang=cfg.lang)
    validate_roster(roster, REQUIRED_AGENTS)
    cfg.ensure_dirs()
    runner = runner or get_runner(cfg.runner)

    log(f"Round      {cfg.round_dir.name}")
    log(f"Report     {cfg.report_path}")
    log(f"Language   {cfg.lang}")
    log(f"Runner     {cfg.runner}")
    log(f"Agents     {len(roster)} loaded from {cfg.agents_dir.relative_to(cfg.project_root)}")
    if cfg.max_budget_usd:
        log(f"Budget     ${cfg.max_budget_usd:.2f} per agent")
    if not cfg.context_is_populated():
        log("\n⚠  context/00-core-brief.md is still the shipped template.")
        log("   Lenses will reason from the input report alone, with no knowledge of the business.")

    result = RoundResult(round_dir=cfg.round_dir)

    for phase in PIPELINE:
        runs = await run_phase(phase, roster, cfg, runner, log)
        result.runs += runs

        # A phase-1 failure is fatal: every downstream agent cites the fact
        # base, and running them without it is the hallucination path.
        if phase.blocking and any(not r.ok for r in runs):
            failed = ", ".join(r.name for r in runs if not r.ok)
            log(f"\n✗ Phase {phase.number} failed ({failed}). Stopping before downstream phases.")
            return result

    if not cfg.dry_run:
        log("\n── Phase 5: quality control (deterministic)")
        result.qc = run_qc(cfg.round_dir)
        log(f"   {result.qc.summary()}")
        for finding in result.qc.all_findings()[:20]:
            log(f"   {finding}")

    log(f"\nDone in {result.total_seconds:.0f}s → {cfg.round_dir}")
    return result
