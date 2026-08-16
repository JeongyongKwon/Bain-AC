"""A deterministic, no-network runner.

Two uses: it is what proves the runner abstraction is real rather than an
interface with a single implementation behind it, and it is what lets
tests/test_pipeline.py exercise the actual phase-blocking and parallel-dispatch
logic in pipeline.py without spending money or needing `claude-agent-sdk`
installed. `--dry-run` on the CLI skips agent dispatch entirely and proves
nothing about the pipeline's control flow; running the pipeline against this
runner does.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from panel.runners.base import AgentRunner, RunnerOutcome


@dataclass
class MockRunner(AgentRunner):
    """Returns canned output per agent name; records every call it saw.

    `responses` maps agent name -> RunnerOutcome. An agent with no entry gets
    a generic success so a test only has to configure the agents it cares
    about. `delay_seconds` simulates work long enough for a test to observe
    that phase-2 dispatches overlap in time, which is the property that
    actually distinguishes "parallel" from "sequential but fast".
    """

    name = "mock"

    responses: dict[str, RunnerOutcome] = field(default_factory=dict)
    delay_seconds: float = 0.0
    calls: list[dict] = field(default_factory=list)

    async def run(
        self,
        *,
        agent_name: str,
        system_prompt: str,
        task: str,
        tools: list[str],
        model: str,
        cwd: Path,
        max_budget_usd: float | None,
    ) -> RunnerOutcome:
        self.calls.append(
            {
                "agent_name": agent_name,
                "task": task,
                "tools": tuple(tools),
                "model": model,
                "cwd": cwd,
                "max_budget_usd": max_budget_usd,
                "started_at": asyncio.get_event_loop().time(),
            }
        )
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)

        if agent_name in self.responses:
            return self.responses[agent_name]
        return RunnerOutcome(text=f"[mock output for {agent_name}]", turns=1)
