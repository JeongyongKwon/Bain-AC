"""Command-line entry point.

    panel run inbox/report.pdf --lang ko
    panel run inbox/report.pdf --dry-run
    panel run inbox/report.pdf --runner mock
    panel qc reports/2026-08-16-report
    panel roster
    panel runners
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from panel.agents import AgentLoadError, load_roster, validate_roster
from panel.config import PIPELINE, REQUIRED_AGENTS, RoundConfig
from panel.pipeline import run_round
from panel.runners import UnknownRunnerError, available_runners
from panel.verify import run_qc


def _project_root(start: Path | None = None) -> Path:
    """Walk up to the directory holding .claude/agents."""
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".claude" / "agents").is_dir():
            return candidate
    raise SystemExit(
        "Not inside a panel project: no .claude/agents directory found in this "
        "directory or any parent."
    )


def _latest_in_inbox(root: Path) -> Path:
    inbox = root / "inbox"
    candidates = [
        p for p in inbox.glob("*")
        if p.is_file() and p.suffix.lower() in {".pdf", ".md", ".txt", ".docx", ".html"}
    ]
    if not candidates:
        raise SystemExit(f"No report given and nothing usable in {inbox}/")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def cmd_run(args: argparse.Namespace) -> int:
    root = _project_root()
    report = Path(args.report).resolve() if args.report else _latest_in_inbox(root)
    if not report.is_file():
        raise SystemExit(f"Report not found: {report}")

    cfg = RoundConfig(
        project_root=root,
        report_path=report,
        lang=args.lang,
        max_budget_usd=args.budget,
        dry_run=args.dry_run,
        runner=args.runner,
    )
    result = asyncio.run(run_round(cfg))

    if result.failed:
        return 1
    if result.qc and not result.qc.ok:
        return 2
    return 0


def cmd_qc(args: argparse.Namespace) -> int:
    round_dir = Path(args.round_dir).resolve()
    if not round_dir.is_dir():
        raise SystemExit(f"Round directory not found: {round_dir}")

    report = run_qc(round_dir)
    print(report.summary())
    for finding in report.all_findings():
        print(finding)
    return 0 if report.ok else 2


def cmd_roster(args: argparse.Namespace) -> int:
    root = _project_root()
    roster = load_roster(root / ".claude" / "agents", lang=args.lang)
    validate_roster(roster, REQUIRED_AGENTS)

    print(f"{len(roster)} agents loaded\n")
    for phase in PIPELINE:
        mode = "parallel, blind" if phase.parallel else "sequential"
        print(f"Phase {phase.number} — {phase.name}  ({mode})")
        for name in phase.agents:
            agent = roster[name]
            print(f"   {agent.name:<24} {agent.model:<8} {len(agent.tools)} tools, {len(agent.prompt):,} chars")
        print()
    return 0


def cmd_runners(args: argparse.Namespace) -> int:
    print("Available runners (select with `panel run --runner <name>`):\n")
    for name in available_runners():
        print(f"   {name}")
    print(
        "\nA runner implements panel.runners.AgentRunner. The pipeline never "
        "imports a provider SDK directly — swap the model API by adding a "
        "runner here, not by editing panel/pipeline.py. See panel/runners/base.py."
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="panel", description="MBB-style strategy panel")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a full panel round")
    run.add_argument("report", nargs="?", help="path to the market research report (default: newest in inbox/)")
    run.add_argument("--lang", default="en", choices=["en", "ko"], help="output language for the reports")
    run.add_argument("--budget", type=float, default=15.0, help="max USD per agent (default: 15)")
    run.add_argument("--dry-run", action="store_true", help="show the plan without dispatching agents")
    run.add_argument(
        "--runner",
        default="claude-agent-sdk",
        help="model API to run agents against (default: claude-agent-sdk; see `panel runners`)",
    )
    run.set_defaults(func=cmd_run)

    qc = sub.add_parser("qc", help="re-run quality control on a completed round")
    qc.add_argument("round_dir", help="path to reports/<round>")
    qc.set_defaults(func=cmd_qc)

    roster = sub.add_parser("roster", help="list the loaded agents and the phase graph")
    roster.add_argument("--lang", default="en", choices=["en", "ko"])
    roster.set_defaults(func=cmd_roster)

    runners = sub.add_parser("runners", help="list available model-API backends")
    runners.set_defaults(func=cmd_runners)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except AgentLoadError as exc:
        print(f"Agent load error: {exc}", file=sys.stderr)
        return 3
    except UnknownRunnerError as exc:
        print(f"Runner error: {exc}", file=sys.stderr)
        return 4
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
