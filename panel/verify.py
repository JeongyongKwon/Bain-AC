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

# EVIDENCE_TAG is a lexer: it answers "is a tag of the right shape present."
# Whether the tag means anything is a separate question, and the two below
# are what answer it.
#
# A fact is *defined* by a heading in the fact base (`## F-012 — title`) and
# *cited* by a bracketed tag anywhere downstream. Nothing previously connected
# the two, so `[F-99999]` satisfied EVIDENCE_TAG and no check ever noticed
# that no such entry existed.
FACT_DEFINITION = re.compile(r"^#{1,6}\s+(F-\d+)\b", re.MULTILINE)
FACT_CITATION = re.compile(r"\[(F-\d+)\]")

# The method text inside [EST: ...]. HOUSE-STANDARD.md promises an estimate is
# reproducible -- "anyone reading [EST: F-012 × F-018] can redo your arithmetic"
# -- but the tag regex accepts any text after the colon, so `[EST: vibes]` and
# `[EST:]` passed identically. These make the promise checkable.
ESTIMATE_TAG = re.compile(r"\[EST:([^\]]*)\]")
_EST_FACT_REF = re.compile(r"\bF-\d+\b")
_EST_CONTEXT_REF = re.compile(r"\bC-[\w./-]+")
_EST_ARITHMETIC = re.compile(r"\d[\d,. ]*\s*[×*x/+\-−÷]\s*[\d(]")

# Files that may cite a fact. The fact base itself is excluded deliberately --
# it is the *source* of F-ids, so its own numbers carry no citations, and
# scanning it here would flag every entry it defines.
CITING_FILES = ("04-partner-synthesis.md", "02-red-team.md", "03-conflict-map.md")
FACT_BASE_FILE = "01-fact-base.md"

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
    dangling_fact_ids: list[Finding] = field(default_factory=list)
    weak_estimates: list[Finding] = field(default_factory=list)
    missing_fact_base: bool = False

    @property
    def ok(self) -> bool:
        return not (
            self.untagged
            or self.structure
            or self.empty_conflict_map
            or self.unverified_in_synthesis
            or self.dangling_fact_ids
            or self.weak_estimates
            or self.missing_fact_base
        )

    def all_findings(self) -> list[Finding]:
        """Every located defect, for callers that just want to print them."""
        return (
            self.untagged
            + self.structure
            + self.unverified_in_synthesis
            + self.dangling_fact_ids
            + self.weak_estimates
        )

    def summary(self) -> str:
        if self.ok:
            return (
                "QC passed: no untagged quantities, every cited fact resolves, "
                "all sections present, conflict map non-empty."
            )
        parts = []
        if self.missing_fact_base:
            parts.append(f"{FACT_BASE_FILE} is missing -- no citation can be checked")
        if self.dangling_fact_ids:
            parts.append(f"{len(self.dangling_fact_ids)} citation(s) of facts that do not exist")
        if self.untagged:
            parts.append(f"{len(self.untagged)} untagged quantit{'y' if len(self.untagged) == 1 else 'ies'}")
        if self.weak_estimates:
            parts.append(f"{len(self.weak_estimates)} unreproducible estimate(s)")
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


def collect_defined_fact_ids(fact_base_text: str) -> set[str]:
    """Every F-id the fact base actually defines, keyed off its heading."""
    return set(FACT_DEFINITION.findall(fact_base_text))


def find_dangling_fact_ids(text: str, path: Path, defined: set[str]) -> list[Finding]:
    """Citations of facts that do not exist.

    The cheapest high-value check in the system: a fabricated or mistyped
    `[F-99999]` is indistinguishable from a real citation to every other
    check, and propagates through seven lenses into the recommendation.
    """
    findings: list[Finding] = []
    for line_no, line in _content_lines(text):
        for match in FACT_CITATION.finditer(line):
            fact_id = match.group(1)
            if fact_id not in defined:
                findings.append(
                    Finding(
                        path=path,
                        line_no=line_no,
                        kind="dangling-fact-id",
                        detail=f"[{fact_id}] is cited but no such entry exists in {FACT_BASE_FILE}",
                        line=line,
                    )
                )
    return findings


def check_estimate_tags(text: str, path: Path) -> list[Finding]:
    """An estimate must name a method someone could actually redo.

    Accepts a method that references a fact (`F-012`), a context file
    (`C-finance/unit-econ.md`), or shows arithmetic between two quantities.
    Rejects an empty method and prose hand-waving.
    """
    findings: list[Finding] = []
    for line_no, line in _content_lines(text):
        for match in ESTIMATE_TAG.finditer(line):
            method = match.group(1).strip()
            if not method:
                detail = "[EST:] states no method"
            elif (
                _EST_FACT_REF.search(method)
                or _EST_CONTEXT_REF.search(method)
                or _EST_ARITHMETIC.search(method)
            ):
                continue
            else:
                detail = (
                    f"[EST: {method}] is not reproducible -- name a fact (F-nnn), "
                    "a context file (C-path), or show the arithmetic"
                )
            findings.append(
                Finding(
                    path=path,
                    line_no=line_no,
                    kind="unreproducible-estimate",
                    detail=detail,
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
    """Run the full phase-5 quality control pass over a completed round.

    The fact base is read as a *source of definitions*, never scanned as
    another report. Its entries are where F-ids come from, so its own numbers
    correctly carry no citations -- running the untagged-quantity scan over it
    would flag every entry it defines.
    """
    report = QCReport()
    lens_dir = round_dir / "lenses"

    fact_base = round_dir / FACT_BASE_FILE
    if fact_base.is_file():
        defined = collect_defined_fact_ids(fact_base.read_text(encoding="utf-8"))
    else:
        # Report this once rather than emitting a dangling finding per citation:
        # with no fact base, every citation is dangling and the list is noise.
        defined = set()
        report.missing_fact_base = True

    def scan(text: str, rel: Path, *, lens: bool = False, synthesis: bool = False) -> None:
        report.untagged += find_untagged_quantities(text, rel)
        report.weak_estimates += check_estimate_tags(text, rel)
        if not report.missing_fact_base:
            report.dangling_fact_ids += find_dangling_fact_ids(text, rel, defined)
        if lens:
            report.structure += check_lens_structure(text, rel)
        if synthesis:
            report.unverified_in_synthesis += check_synthesis_evidence(text, rel)

    if lens_dir.is_dir():
        for lens_file in sorted(lens_dir.glob("*.md")):
            scan(lens_file.read_text(encoding="utf-8"), lens_file.relative_to(round_dir), lens=True)

    synthesis = round_dir / "04-partner-synthesis.md"
    if synthesis.is_file():
        scan(synthesis.read_text(encoding="utf-8"), synthesis.relative_to(round_dir), synthesis=True)

    for name in CITING_FILES:
        if name == "04-partner-synthesis.md":
            continue  # already scanned above, with its synthesis-specific check
        path = round_dir / name
        if path.is_file():
            scan(path.read_text(encoding="utf-8"), path.relative_to(round_dir))

    conflict_map = round_dir / "03-conflict-map.md"
    report.empty_conflict_map = not (
        conflict_map.is_file() and _is_substantive(conflict_map.read_text(encoding="utf-8"))
    )

    return report
