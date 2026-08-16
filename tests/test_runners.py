import asyncio
from pathlib import Path

import pytest

from panel.runners import AgentRunner, RunnerOutcome, UnknownRunnerError, get_runner
from panel.runners.mock import MockRunner
from panel.runners.registry import available_runners, register_runner


def run_sync(coro):
    """No pytest-asyncio dependency -- run one coroutine to completion."""
    return asyncio.run(coro)


# --------------------------------------------------------------------------
# the registry
# --------------------------------------------------------------------------

def test_builtins_are_listed():
    names = available_runners()
    assert "claude-agent-sdk" in names
    assert "mock" in names


def test_get_runner_returns_an_agent_runner():
    runner = get_runner("mock")
    assert isinstance(runner, AgentRunner)


def test_unknown_runner_raises_with_available_list():
    with pytest.raises(UnknownRunnerError, match="mock"):
        get_runner("does-not-exist")


def test_claude_agent_sdk_is_lazily_constructible_without_the_package_installed():
    """Selecting the runner must not require the SDK to be importable --
    only *calling* .run() should. This is what keeps `panel roster` and
    `panel runners` working in an environment with no API key configured."""
    runner = get_runner("claude-agent-sdk")
    assert runner.name == "claude-agent-sdk"


def test_custom_runner_can_be_registered_from_outside_the_package():
    class FakeProvider(AgentRunner):
        name = "test-fake-provider"

        async def run(self, **kwargs):  # pragma: no cover - never invoked here
            return RunnerOutcome(text="", turns=0)

    register_runner(FakeProvider)
    assert "test-fake-provider" in available_runners()
    assert isinstance(get_runner("test-fake-provider"), FakeProvider)


def test_register_runner_rejects_unnamed_class():
    class NoName(AgentRunner):
        async def run(self, **kwargs):  # pragma: no cover
            return RunnerOutcome(text="", turns=0)

    with pytest.raises(ValueError, match="name"):
        register_runner(NoName)


# --------------------------------------------------------------------------
# the contract every runner must satisfy
# --------------------------------------------------------------------------

def test_agent_runner_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        AgentRunner()  # abstract -- run() has no implementation


def test_runner_outcome_ok_property():
    assert RunnerOutcome(text="x", turns=1).ok
    assert not RunnerOutcome(text="", turns=0, error="boom").ok


# --------------------------------------------------------------------------
# MockRunner behaviour
# --------------------------------------------------------------------------

async def _run(runner: MockRunner, name: str = "some-agent") -> RunnerOutcome:
    return await runner.run(
        agent_name=name,
        system_prompt="You are a test agent.",
        task="Do the thing.",
        tools=["Read"],
        model="sonnet",
        cwd=Path("/tmp/round"),
        max_budget_usd=5.0,
    )


def test_default_response_is_generic_success():
    outcome = run_sync(_run(MockRunner()))
    assert outcome.ok
    assert "some-agent" in outcome.text


def test_configured_response_is_returned_verbatim():
    canned = RunnerOutcome(text="fact base contents", turns=3)
    runner = MockRunner(responses={"research-desk": canned})
    outcome = run_sync(_run(runner, name="research-desk"))
    assert outcome is canned


def test_configured_failure_is_returned_as_error_not_raised():
    runner = MockRunner(responses={"lens-operations": RunnerOutcome(text="", turns=0, error="refused")})
    outcome = run_sync(_run(runner, name="lens-operations"))
    assert not outcome.ok
    assert outcome.error == "refused"


def test_calls_are_recorded_for_assertions():
    runner = MockRunner()
    run_sync(_run(runner, name="lens-commercial"))
    assert len(runner.calls) == 1
    assert runner.calls[0]["agent_name"] == "lens-commercial"
    assert runner.calls[0]["max_budget_usd"] == 5.0
