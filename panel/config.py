"""Round configuration and the phase graph.

The pipeline's shape lives here as data rather than as control flow, so the
blocking/parallel structure is inspectable and testable without running a
round or spending anything.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

RESEARCH_DESK = "research-desk"
RED_TEAM = "red-team"
PARTNER = "partner-synthesis"

LENSES: tuple[str, ...] = (
    "lens-market-strategy",
    "lens-commercial",
    "lens-corporate-finance",
    "lens-operations",
    "lens-organization",
    "lens-digital-tech",
    "lens-risk-regulatory",
)

REQUIRED_AGENTS: tuple[str, ...] = (RESEARCH_DESK, *LENSES, RED_TEAM, PARTNER)


@dataclass(frozen=True)
class Phase:
    """One stage of the pipeline.

    `parallel` is what enforces lens isolation: the seven lenses are dispatched
    together, so none can read another's output because none of it exists yet.

    `blocking` defaults to False: an agent failure is visible in the round's
    result and in phase-5 QC, but only phase 1's fact base is load-bearing
    enough to justify aborting the round outright over one agent's failure --
    see docs/ARCHITECTURE.md § Why Phase 1 blocks. Set it explicitly, per
    phase, rather than leaving readers to notice a default that only one
    phase actually wants.
    """

    number: int
    name: str
    agents: tuple[str, ...]
    parallel: bool = False
    blocking: bool = False
    produces: tuple[str, ...] = ()


PIPELINE: tuple[Phase, ...] = (
    Phase(
        number=1,
        name="fact base",
        agents=(RESEARCH_DESK,),
        blocking=True,  # the one hard gate -- see the Phase docstring above
        produces=("01-fact-base.md", "01-contradictions.md"),
    ),
    Phase(
        number=2,
        name="seven lenses",
        agents=LENSES,
        parallel=True,
        produces=tuple(f"lenses/{n.removeprefix('lens-')}.md" for n in LENSES),
    ),
    Phase(
        number=3,
        name="red team",
        agents=(RED_TEAM,),
        produces=("02-red-team.md",),
    ),
    Phase(
        number=4,
        name="partner synthesis",
        agents=(PARTNER,),
        produces=("03-conflict-map.md", "04-partner-synthesis.md"),
    ),
)


def slugify(value: str) -> str:
    """A filesystem-safe slug that keeps non-Latin scripts intact."""
    value = unicodedata.normalize("NFKC", value).strip().lower()
    value = re.sub(r"[\s_]+", "-", value)
    value = re.sub(r"[^\w\-]", "", value, flags=re.UNICODE)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value[:48] or "round"


@dataclass
class RoundConfig:
    """Everything one round needs to know about where things live."""

    project_root: Path
    report_path: Path
    lang: str = "en"
    when: date = field(default_factory=date.today)
    max_budget_usd: float | None = 15.0
    dry_run: bool = False
    runner: str = "claude-agent-sdk"  # which model API drives every agent this round; see panel/runners/

    @property
    def agents_dir(self) -> Path:
        return self.project_root / ".claude" / "agents"

    @property
    def context_dir(self) -> Path:
        return self.project_root / "context"

    @property
    def round_dir(self) -> Path:
        return self.project_root / "reports" / f"{self.when:%Y-%m-%d}-{slugify(self.report_path.stem)}"

    def ensure_dirs(self) -> None:
        (self.round_dir / "lenses").mkdir(parents=True, exist_ok=True)

    def context_is_populated(self) -> bool:
        """True once the core brief has been filled in.

        A round run against the shipped template still works, but the lenses
        reason with no knowledge of the business -- worth warning about rather
        than failing on.
        """
        brief = self.context_dir / "00-core-brief.md"
        if not brief.is_file():
            return False
        return "Template — replace this content" not in brief.read_text(encoding="utf-8")
