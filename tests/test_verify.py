from pathlib import Path

from panel.verify import (
    QCReport,
    check_lens_structure,
    check_synthesis_evidence,
    find_untagged_quantities,
    run_qc,
)

P = Path("lenses/test.md")


# --------------------------------------------------------------------------
# untagged quantities -- the core of the evidence contract
# --------------------------------------------------------------------------

def test_flags_bare_percentage():
    findings = find_untagged_quantities("Installs fell 4% in 2025.", P)
    assert len(findings) == 1
    assert "4%" in findings[0].detail


def test_accepts_tagged_percentage():
    assert find_untagged_quantities("Installs fell 4% in 2025 [F-012].", P) == []


def test_accepts_each_tag_form():
    for tag in ("[F-1]", "[R-p14]", "[C-finance/unit-econ.md]", "[EST: F-1 x F-2]", "[ASSUMPTION]"):
        assert find_untagged_quantities(f"Margin is 34% {tag}", P) == [], tag


def test_flags_currency_amounts():
    findings = find_untagged_quantities("Delivered cost is €3,180 per unit.", P)
    assert len(findings) == 1


def test_flags_multiple_on_one_line():
    findings = find_untagged_quantities("Cost €3,180 against a price of €3,400.", P)
    assert len(findings) == 2


def test_ignores_bare_integers():
    # "7 lenses" is not a claim about the world.
    assert find_untagged_quantities("The panel runs 7 lenses in parallel.", P) == []


def test_ignores_code_fences():
    text = "```\ngrowth = 0.09  # 9%\n```\nGrowth is 9% [F-3]."
    assert find_untagged_quantities(text, P) == []


def test_ignores_table_separator():
    assert find_untagged_quantities("|---|---:|---|", P) == []


def test_ignores_fact_base_provenance_rows():
    text = "**Verbatim:** \"reached 3,142,000 units, a 4% decline\"\n**Grade:** A"
    assert find_untagged_quantities(text, P) == []


def test_reports_line_number():
    text = "line one\nline two\nMargin is 12%.\n"
    findings = find_untagged_quantities(text, P)
    assert findings[0].line_no == 3


def test_multiplier_and_basis_points():
    assert len(find_untagged_quantities("Trading at 14x earnings.", P)) == 1
    assert len(find_untagged_quantities("Spread widened 250bps.", P)) == 1


# --------------------------------------------------------------------------
# lens report structure
# --------------------------------------------------------------------------

FULL_LENS = """
# Market Strategy
## Bottom line
x
## Where the report holds up
x
## Findings
x
## The number that matters
x
## Risks and falsifiers
x
## Open questions
x
## Recommended action from this lens
x
"""


def test_complete_lens_passes():
    assert check_lens_structure(FULL_LENS, P) == []


def test_missing_section_flagged():
    truncated = FULL_LENS.replace("## Open questions\nx\n", "")
    findings = check_lens_structure(truncated, P)
    assert len(findings) == 1
    assert "open questions" in findings[0].detail


# --------------------------------------------------------------------------
# unverified claims inside the recommendation
# --------------------------------------------------------------------------

def test_unverified_in_recommendation_flagged():
    text = "## Findings\nShare is 12% [R-p14].\n## Recommended action\nEnter, on 12% share [R-p14].\n"
    findings = check_synthesis_evidence(text, P)
    assert len(findings) == 1
    assert findings[0].line_no == 4


def test_unverified_outside_recommendation_allowed():
    text = "## Findings\nShare is 12% [R-p14].\n## Open questions\nUnconfirmed [R-p14].\n"
    assert check_synthesis_evidence(text, P) == []


def test_verified_in_recommendation_allowed():
    text = "## Recommended action\nEnter, on 12% share [F-021].\n"
    assert check_synthesis_evidence(text, P) == []


# --------------------------------------------------------------------------
# full round QC
# --------------------------------------------------------------------------

def _write_round(tmp_path: Path, *, conflict_map: str, lens_body: str) -> Path:
    (tmp_path / "lenses").mkdir(parents=True)
    (tmp_path / "lenses" / "market.md").write_text(lens_body, encoding="utf-8")
    (tmp_path / "03-conflict-map.md").write_text(conflict_map, encoding="utf-8")
    (tmp_path / "04-partner-synthesis.md").write_text(
        "## Recommended action\nEnter the market [F-021].\n", encoding="utf-8"
    )
    return tmp_path


def test_clean_round_passes(tmp_path):
    conflict = "## K-01\nOperations and Commercial disagree on achievable margin, and the gap is decisive for the recommendation.\n"
    report = run_qc(_write_round(tmp_path, conflict_map=conflict, lens_body=FULL_LENS))
    assert report.ok, report.summary()


def test_empty_conflict_map_fails(tmp_path):
    report = run_qc(_write_round(tmp_path, conflict_map="# Conflict Map\n", lens_body=FULL_LENS))
    assert report.empty_conflict_map
    assert not report.ok
    assert "conflict map is empty" in report.summary()


def test_untagged_number_in_lens_fails(tmp_path):
    dirty = FULL_LENS.replace("## Findings\nx", "## Findings\nMargin is 12%.")
    conflict = "## K-01\nA real and decisive disagreement between two lenses, described at length.\n"
    report = run_qc(_write_round(tmp_path, conflict_map=conflict, lens_body=dirty))
    assert len(report.untagged) == 1
    assert not report.ok


def test_summary_is_clean_when_passing():
    assert QCReport().ok
    assert "QC passed" in QCReport().summary()
