"""The provider boundary.

Everything above this line -- pipeline.py, verify.py, config.py -- knows
nothing about which model API actually runs an agent. It calls `AgentRunner.run()`
with plain strings and gets plain strings back. Swapping providers means
writing one new class in this package; it never means touching the
orchestration logic, the evidence contract, or the tests that exercise them.

This is deliberately a narrow contract. An agent invocation, seen from the
pipeline's side, is "give it a role and a task, get back text or an error" --
nothing about tool-call loops, thinking blocks, or streaming needs to leak
above this boundary, because the panel's five-phase structure never inspects
those details.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunnerOutcome:
    """What one agent invocation produced, in provider-neutral terms."""

    text: str
    turns: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class AgentRunner(ABC):
    """One implementation per model API. Register it; don't special-case it.

    `name` is the registry key users pass as `--runner <name>` or set in
    `RoundConfig.runner`. Pick something that names the API, not the vendor's
    marketing name for a product tier -- "claude-agent-sdk" and
    "anthropic-messages" are both legitimate distinct runners against the same
    vendor, because they are different APIs with different capabilities.
    """

    name: str

    @abstractmethod
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
        """Run one agent to completion and return what it produced.

        `agent_name` is for tracing and error messages -- a session title,
        a log field, a key in a mock's canned-response table. It has no
        semantic weight to the API call itself.

        `tools` and `model` are the raw strings from the agent's frontmatter
        (`.claude/agents/*.md`) -- this method owns interpreting them for its
        own API. A tool name or model alias that only makes sense on one
        provider (e.g. `Bash`, or the alias `opus`) is that provider's runner's
        problem to translate or reject, not the pipeline's.

        Implementations should prefer returning `RunnerOutcome(error=...)` over
        raising for ordinary failures (refusal, budget exceeded, malformed
        tool call) -- the pipeline treats a raised exception as unexpected and
        logs it differently from a normal per-agent failure.
        """
        ...
