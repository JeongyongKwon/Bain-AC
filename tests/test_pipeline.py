"""Exercises the orchestrator's actual control flow -- phase blocking, the
parallel dispatch of the seven lenses, and runner injection -- against the
`mock` runner, so these run offline, free, and without `claude-agent-sdk`
installed. `--dry-run` on the CLI skips agent dispatch entirely and proves
nothing about this; these tests call `run_agent`/`run_phase`/`run_round`
directly.

Note: the real agents write their own output files via tool calls inside the
SDK session. MockRunner does not simulate that -- these tests verify the
*orchestrator's* behaviour (who got called, in what order, with what budget),
not file output, which is why phase-5 QC below correctly reports an empty
conflict map: nothing wrote `03-conflict-map.md`, and it should say so.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path

import pytest

from panel.agents import load_roster
from panel.config import PIPELINE, RoundConfig
from panel.pipeline import run_agent, run_phase, run_round
from panel.runners import RunnerOutcome
from panel.runners.mock import MockRunner

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LENS_PHASE = next(p for p in PIPELINE if p.parallel)
FACT_BASE_PHASE = PIPELINE[0]


def run_sync(coro):
    return asyncio.run(coro)


@pytest.fixture
def project(tmp_path) -> tuple[Path, Path]:
    """An isolated project directory carrying only what the pipeline reads:
    the real .claude/agents roster, copied so tests never touch it or the
    real reports/ directory."""
    shutil.copytree(PROJECT_ROOT / ".claude", tmp_path / ".claude")
    report = tmp_path / "inbox" / "report.md"
    report.parent.mkdir()
    report.write_text("# Test report\n\nSample content for the pipeline to reference.\n")
    return tmp_path, report


def make_cfg(project: tuple[Path, Path], **overrides) -> RoundConfig:
    root, report = project
    return RoundConfig(project_root=root, report_path=report, **overrides)


# --------------------------------------------------------------------------
# a full round, offline
# --------------------------------------------------------------------------

def test_full_round_calls_every_one_of_the_ten_agents(project):
    runner = MockRunner()
    cfg = make_cfg(project)
    result = run_sync(run_round(cfg, log=lambda *_: None, runner=runner))

    assert len(runner.calls) == 10
    assert {c["agent_name"] for c in runner.calls} == {r.name for r in result.runs}
    assert len(result.runs) == 10
    assert all(r.ok for r in result.runs)


def test_full_round_runs_qc_and_correctly_flags_the_empty_conflict_map(project):
    # MockRunner writes no files, so QC should catch exactly that -- proving
    # phase 5 runs against whatever actually landed on disk, not against a
    # success flag the pipeline invents for itself.
    result = run_sync(run_round(make_cfg(project), log=lambda *_: None, runner=MockRunner()))
    assert result.qc is not None
    assert result.qc.empty_conflict_map
    assert not result.qc.ok


# --------------------------------------------------------------------------
# phase 1 blocks phase 2+
# --------------------------------------------------------------------------

def test_research_desk_failure_stops_the_round_before_any_lens_runs(project):
    runner = MockRunner(
        responses={"research-desk": RunnerOutcome(text="", turns=0, error="verification service unreachable")}
    )
    result = run_sync(run_round(make_cfg(project), log=lambda *_: None, runner=runner))

    assert len(runner.calls) == 1, "no lens should have been dispatched after the fact base failed"
    assert runner.calls[0]["agent_name"] == "research-desk"
    assert len(result.failed) == 1
    assert result.qc is None, "QC should not run over a round that never finished"


def test_lens_failure_does_not_stop_the_round(project):
    """Phase 2 is not marked blocking -- one lens failing should not prevent
    the red team and Partner from working with the other six."""
    runner = MockRunner(responses={"lens-digital-tech": RunnerOutcome(text="", turns=0, error="timed out")})
    result = run_sync(run_round(make_cfg(project), log=lambda *_: None, runner=runner))

    assert len(runner.calls) == 10, "red team and Partner should still have been dispatched"
    failed_names = {r.name for r in result.failed}
    assert failed_names == {"lens-digital-tech"}


# --------------------------------------------------------------------------
# phase 2 is genuinely concurrent, not just fast
# --------------------------------------------------------------------------

def test_seven_lenses_are_dispatched_concurrently_not_sequentially(project):
    root, report = project
    delay = 0.08
    runner = MockRunner(delay_seconds=delay)
    cfg = make_cfg(project)
    roster = load_roster(cfg.agents_dir)

    started = time.monotonic()
    runs = run_sync(run_phase(LENS_PHASE, roster, cfg, runner, log=lambda *_: None))
    elapsed = time.monotonic() - started

    assert len(runs) == 7
    # Sequential would take ~7*delay (0.56s); concurrent should land close to
    # one delay plus scheduling overhead. The threshold is generous on purpose
    # -- this asserts overlap happened, not a tight performance bound.
    assert elapsed < delay * 3, f"seven lenses took {elapsed:.3f}s at delay={delay} -- looks sequential"


def test_research_desk_phase_is_sequential_by_construction(project):
    """Phase 1 has exactly one agent, so 'sequential' and 'parallel' are
    indistinguishable by timing -- assert on the phase config instead."""
    assert not FACT_BASE_PHASE.parallel
    assert FACT_BASE_PHASE.agents == ("research-desk",)


# --------------------------------------------------------------------------
# what actually reaches the runner
# --------------------------------------------------------------------------

def test_model_string_reaches_the_runner_unmodified(project):
    """The pipeline must not interpret or rewrite the model alias -- that is
    the selected runner's job. Proves the provider boundary is where it
    should be: model names never touch pipeline.py's logic."""
    runner = MockRunner()
    run_sync(run_round(make_cfg(project), log=lambda *_: None, runner=runner))
    by_name = {c["agent_name"]: c["model"] for c in runner.calls}
    assert by_name["research-desk"] == "opus"
    assert by_name["lens-commercial"] == "sonnet"


def test_budget_and_cwd_are_forwarded_to_the_runner(project):
    root, _ = project
    runner = MockRunner()
    run_sync(run_round(make_cfg(project, max_budget_usd=3.25), log=lambda *_: None, runner=runner))
    assert all(c["max_budget_usd"] == 3.25 for c in runner.calls)
    assert all(c["cwd"] == root for c in runner.calls)


# --------------------------------------------------------------------------
# runner injection bypasses the string-keyed registry
# --------------------------------------------------------------------------

def test_injected_runner_bypasses_cfg_runner_name_entirely(project):
    """cfg.runner names a registry entry that does not exist. If the
    orchestrator ever fell back to `get_runner(cfg.runner)` despite an
    explicit runner being passed, this would raise UnknownRunnerError."""
    runner = MockRunner()
    cfg = make_cfg(project, runner="this-name-is-not-registered")
    result = run_sync(run_round(cfg, log=lambda *_: None, runner=runner))
    assert len(runner.calls) == 10
    assert result.runs


# --------------------------------------------------------------------------
# dry-run never touches the runner
# --------------------------------------------------------------------------

def test_dry_run_calls_the_runner_zero_times(project):
    runner = MockRunner()
    result = run_sync(run_round(make_cfg(project, dry_run=True), log=lambda *_: None, runner=runner))
    assert runner.calls == []
    assert result.qc is None
    assert all(r.seconds == 0.0 for r in result.runs)


# --------------------------------------------------------------------------
# run_agent in isolation
# --------------------------------------------------------------------------

def test_run_agent_wraps_a_raised_exception_as_an_error_not_a_crash(project):
    class ExplodingRunner(MockRunner):
        name = "exploding"

        async def run(self, **kwargs):
            raise RuntimeError("provider connection reset")

    cfg = make_cfg(project)
    roster = load_roster(cfg.agents_dir)
    run = run_sync(run_agent(roster["research-desk"], cfg, FACT_BASE_PHASE, ExplodingRunner()))

    assert not run.ok
    assert "provider connection reset" in run.error
