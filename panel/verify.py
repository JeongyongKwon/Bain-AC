"""Deterministic quality control for panel round outputs.

Everything in this module is pure and testable. The evidence contract is the
one part of the system that must not depend on a model's judgement -- if the
check for untagged numbers were itself an LLM call, it would inherit exactly
the failure mode it exists to catch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Evidence tags defined in docs/HOUSE-STANDARD.md.
#   [F-012]                    verified fact, lives in the fact base
#   [R-p14]                    the input report asserts it; nobody checked
#   [C-finance/unit-econ.md]   internal context pack
#   [EST: method]              agent's own estimate, method stated
#   [ASSUMPTION]               knowingly unevidenced premise
EVIDENCE_TAG = re.compile(r"\[(?:F-\d+|R-[\w.]+|C-[^\]]+|EST:[^\]]*|ASSUMPTION)\]")

# A quantity is a number carrying a unit that implies a factual claim.
# Bare integers are excluded deliberately -- "the 3 lenses" is not a claim
# about the world, and flagging it would bury the real findings in noise.
QUANTITY = re.compile(
    r"""
    (?<![\w.])                          # not mid-identifier
    (?:[€$£¥]\s?)?                      # optional leading currency
    \d{1,3}(?:,\d{3})+(?:\.\d+)?        # 1,234,567.8
    |
    (?<![\w.])
    (?:[€$£¥]\s?)?
    \d+(?:\.\d+)?
    \s?
    (?:%|pp|bps|bn|BN|[Mm]n|[Bb]n|[Kk]|[Mm](?![\w])|x(?![\w])|€|\$|£|¥)
    """,
    re.VERBOSE,
)

# Lines that look quantitative but carry no factual claim.
_SKIP_LINE = re.compile(
    r"""
    ^\s*\|?\s*[-:|\s]+\|?\s*$        # markdown table separator
    | ^\s*\#{1,6}\s                  # heading
    | ^\s*(?:\[|!\[)                 # link / image only
    | ^\s*(?:\*\*)?(?:Source|URL|Accessed|Verbatim|Grade|출처|근거)(?:\*\*)?\s*:  # fact-base provenance rows
    """,
    re.VERBOSE | re.IGNORECASE,
)

FENCE = re.compile(r"^\s*(?:```|~~~)")

REQUIRED_LENS_SECTIONS = (
    "bottom line",
    "report",          # "Where the report holds up..."
    "findings",
    "number that matters",
    "risks",
    "open questions",
    "recommended action",
)


@dataclass
class Finding:
    """One QC defect, located precisely enough to act on."""

    path: Path
    line_no: int
    kind: str
    detail: str
    line: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line_no}  [{self.kind}] {self.detail}\n    {self.line.strip()}"


@dataclass
class QCReport:
    untagged: list[Finding] = field(default_factory=list)
    structure: list[Finding] = field(default_factory=list)
    empty_conflict_map: bool = False
    unverified_in_synthesis: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (
            self.untagged
            or self.structure
            or self.empty_conflict_map
            or self.unverified_in_synthesis
        )

    def summary(self) -> str:
        if self.ok:
            return "QC passed: no untagged quantities, all sections present, conflict map non-empty."
        parts = []
        if self.untagged:
            parts.append(f"{len(self.untagged)} untagged quantit{'y' if len(self.untagged) == 1 else 'ies'}")
        if self.structure:
            parts.append(f"{len(self.structure)} structural defect(s)")
        if self.empty_conflict_map:
            parts.append("conflict map is empty (lens isolation may have failed)")
        if self.unverified_in_synthesis:
            parts.append(f"{len(self.unverified_in_synthesis)} unverified claim(s) load-bearing in synthesis")
        return "QC failed: " + "; ".join(parts)


def _content_lines(text: str) -> list[tuple[int, str]]:
    """Yield (1-indexed line number, line), skipping fenced code blocks."""
    out: list[tuple[int, str]] = []
    in_fence = False
    for i, line in enumerate(text.splitlines(), start=1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        out.append((i, line))
    return out


def find_untagged_quantities(text: str, path: Path) -> list[Finding]:
    """Every quantity on a line with no evidence tag is a contract violation.

    Scoped to the line rather than the sentence: agents write one claim per
    line in these reports, and line scope keeps the check explainable to
    whoever has to act on the result.
    """
    findings: list[Finding] = []
    for line_no, line in _content_lines(text):
        if _SKIP_LINE.search(line):
            continue
        if EVIDENCE_TAG.search(line):
            continue
        for match in QUANTITY.finditer(line):
            findings.append(
                Finding(
                    path=path,
                    line_no=line_no,
                    kind="untagged-quantity",
                    detail=f"{match.group(0)!r} carries no evidence tag",
                    line=line,
                )
            )
    return findings


def check_lens_structure(text: str, path: Path) -> list[Finding]:
    """A lens report must carry all seven house-standard sections."""
    headings = "\n".join(
        line.lower() for _, line in _content_lines(text) if line.lstrip().startswith("#")
    )
    missing = [s for s in REQUIRED_LENS_SECTIONS if s not in headings]
    if not missing:
        return []
    return [
        Finding(
            path=path,
            line_no=0,
            kind="missing-section",
            detail=f"missing section(s): {', '.join(missing)}",
            line="",
        )
    ]


def check_synthesis_evidence(text: str, path: Path) -> list[Finding]:
    """Flag unverified claims inside the synthesis's recommendation.

    An [R-] tag anywhere in the deliverable is fine and often necessary. One
    inside the recommendation itself means the answer rests on something
    nobody checked, and that has to be visible rather than buried.
    """
    findings: list[Finding] = []
    in_reco = False
    for line_no, line in _content_lines(text):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            lowered = stripped.lower()
            in_reco = "recommend" in lowered or "권고" in lowered or "결론" in lowered
            continue
        if not in_reco:
            continue
        for tag in re.finditer(r"\[(?:R-[\w.]+|ASSUMPTION)\]", line):
            findings.append(
                Finding(
                    path=path,
                    line_no=line_no,
                    kind="unverified-in-recommendation",
                    detail=f"{tag.group(0)} is load-bearing in the recommendation",
                    line=line,
                )
            )
    return findings


def _is_substantive(text: str) -> bool:
    """True if a file has real content rather than a heading and whitespace."""
    body = [
        line
        for _, line in _content_lines(text)
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return len("\n".join(body).strip()) > 80


def run_qc(round_dir: Path) -> QCReport:
    """Run the full phase-5 quality control pass over a completed round."""
    report = QCReport()
    lens_dir = round_dir / "lenses"

    if lens_dir.is_dir():
        for lens_file in sorted(lens_dir.glob("*.md")):
            text = lens_file.read_text(encoding="utf-8")
            rel = lens_file.relative_to(round_dir)
            report.untagged += find_untagged_quantities(text, rel)
            report.structure += check_lens_structure(text, rel)

    synthesis = round_dir / "04-partner-synthesis.md"
    if synthesis.is_file():
        text = synthesis.read_text(encoding="utf-8")
        rel = synthesis.relative_to(round_dir)
        report.untagged += find_untagged_quantities(text, rel)
        report.unverified_in_synthesis += check_synthesis_evidence(text, rel)

    conflict_map = round_dir / "03-conflict-map.md"
    report.empty_conflict_map = not (
        conflict_map.is_file() and _is_substantive(conflict_map.read_text(encoding="utf-8"))
    )

    return report
