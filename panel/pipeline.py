"""The five-phase panel orchestrator.

Phase ordering is enforced here in Python rather than described in a prompt.
That matters for the two structural guarantees the architecture rests on:

  * the fact base blocks -- `await` on phase 1 means no lens can start before
    verified numbers exist, so none has to invent one to fill a gap;
  * the lenses are blind -- `asyncio.gather` dispatches all seven at once, so
    none can read another's output because none of it exists yet.

Neither depends on an agent remembering an instruction.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path

from panel.agents import LoadedAgent, load_roster, validate_roster
from panel.config import PIPELINE, REQUIRED_AGENTS, Phase, RoundConfig
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


async def run_agent(agent: LoadedAgent, cfg: RoundConfig, phase: Phase) -> AgentRun:
    """Invoke one agent to completion, collecting its output and cost."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        query,
    )

    started = time.monotonic()
    chunks: list[str] = []
    turns = 0
    error: str | None = None

    options = ClaudeAgentOptions(
        system_prompt=agent.prompt,
        allowed_tools=agent.tools,
        model=None if agent.model == "inherit" else agent.model,
        cwd=str(cfg.project_root),
        permission_mode="acceptEdits",
        # Prompts are passed explicitly above; loading project settings as well
        # would register the same roster twice.
        setting_sources=[],
        max_budget_usd=cfg.max_budget_usd,
    )

    try:
        async for message in query(prompt=build_task(agent, cfg, phase), options=options):
            if isinstance(message, AssistantMessage):
                turns += 1
                for block in message.content:
                    if isinstance(block, TextBlock):
                        chunks.append(block.text)
            elif isinstance(message, ResultMessage):
                if message.subtype == "failure":
                    error = f"{message.terminal_reason}: {message.result}"
    except Exception as exc:  # surfaced per-agent so one failure cannot sink the round
        error = f"{type(exc).__name__}: {exc}"

    return AgentRun(
        name=agent.name,
        seconds=time.monotonic() - started,
        turns=turns,
        text="\n".join(chunks),
        error=error,
    )


async def run_phase(
    phase: Phase,
    roster: dict[str, LoadedAgent],
    cfg: RoundConfig,
    log,
) -> list[AgentRun]:
    """Run one phase, in parallel where the phase says so."""
    mode = f"{len(phase.agents)} agents in parallel" if phase.parallel else "sequential"
    log(f"\n── Phase {phase.number}: {phase.name} ({mode})")

    if cfg.dry_run:
        for name in phase.agents:
            log(f"   [dry-run] would dispatch {name} ({roster[name].model})")
        return [AgentRun(name=n, seconds=0.0, turns=0, text="") for n in phase.agents]

    tasks = [run_agent(roster[name], cfg, phase) for name in phase.agents]

    if phase.parallel:
        runs = await asyncio.gather(*tasks)
    else:
        runs = [await task for task in tasks]

    for run in runs:
        status = "ok" if run.ok else f"FAILED — {run.error}"
        log(f"   {run.name:<24} {run.seconds:6.1f}s  {run.turns:>3} turns  {status}")
    return list(runs)


async def run_round(cfg: RoundConfig, log=print) -> RoundResult:
    """Execute a full panel round and return its result."""
    roster = load_roster(cfg.agents_dir, lang=cfg.lang)
    validate_roster(roster, REQUIRED_AGENTS)
    cfg.ensure_dirs()

    log(f"Round      {cfg.round_dir.name}")
    log(f"Report     {cfg.report_path}")
    log(f"Language   {cfg.lang}")
    log(f"Agents     {len(roster)} loaded from {cfg.agents_dir.relative_to(cfg.project_root)}")
    if cfg.max_budget_usd:
        log(f"Budget     ${cfg.max_budget_usd:.2f} per agent")
    if not cfg.context_is_populated():
        log("\n⚠  context/00-core-brief.md is still the shipped template.")
        log("   Lenses will reason from the input report alone, with no knowledge of the business.")

    result = RoundResult(round_dir=cfg.round_dir)

    for phase in PIPELINE:
        runs = await run_phase(phase, roster, cfg, log)
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
        for finding in (result.qc.untagged + result.qc.structure + result.qc.unverified_in_synthesis)[:20]:
            log(f"   {finding}")

    log(f"\nDone in {result.total_seconds:.0f}s → {cfg.round_dir}")
    return result
