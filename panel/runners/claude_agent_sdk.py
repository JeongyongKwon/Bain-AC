"""Runner backed by the Claude Agent SDK (`claude-agent-sdk` on PyPI).

The default runner and the one every agent in this repo has been written
against -- the `model:` values in `.claude/agents/*.md` frontmatter (`opus`,
`sonnet`, `inherit`) are Claude Agent SDK aliases. Swapping to a different
runner does not require rewriting the agent prompts, but it will generally
mean revisiting the `model:` line in each one, since a different provider's
model names are this runner's business, not the pipeline's.
"""

from __future__ import annotations

from pathlib import Path

from panel.runners.base import AgentRunner, RunnerOutcome


class ClaudeAgentSDKRunner(AgentRunner):
    name = "claude-agent-sdk"

    def __init__(self, *, permission_mode: str = "acceptEdits") -> None:
        # Prompts are supplied explicitly per call; loading project settings
        # as well would register the same roster a second time from disk.
        self._permission_mode = permission_mode

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
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            TextBlock,
            query,
        )

        chunks: list[str] = []
        turns = 0
        error: str | None = None

        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            allowed_tools=tools,
            model=None if model == "inherit" else model,
            cwd=str(cwd),
            permission_mode=self._permission_mode,
            setting_sources=[],
            max_budget_usd=max_budget_usd,
        )

        async for message in query(prompt=task, options=options):
            if isinstance(message, AssistantMessage):
                turns += 1
                for block in message.content:
                    if isinstance(block, TextBlock):
                        chunks.append(block.text)
            elif isinstance(message, ResultMessage):
                if message.subtype == "failure":
                    error = f"{message.terminal_reason}: {message.result}"

        return RunnerOutcome(text="\n".join(chunks), turns=turns, error=error)
