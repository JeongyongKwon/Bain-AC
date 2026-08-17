from pathlib import Path

from panel.verify import (
    Finding,
    QCReport,
    check_estimate_tags,
    check_lens_structure,
    check_synthesis_evidence,
    collect_defined_fact_ids,
    find_dangling_fact_ids,
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

FACT_BASE = """# Fact base

## F-012 — EU installations, 2025

**Claim:** 3.1M units
**Grade:** A

## F-021 — Market entry precedent

**Claim:** three entrants since 2022
**Grade:** B
"""


def _write_round(
    tmp_path: Path,
    *,
    conflict_map: str,
    lens_body: str,
    fact_base: str | None = FACT_BASE,
) -> Path:
    (tmp_path / "lenses").mkdir(parents=True)
    (tmp_path / "lenses" / "market.md").write_text(lens_body, encoding="utf-8")
    (tmp_path / "03-conflict-map.md").write_text(conflict_map, encoding="utf-8")
    (tmp_path / "04-partner-synthesis.md").write_text(
        "## Recommended action\nEnter the market [F-021].\n", encoding="utf-8"
    )
    if fact_base is not None:
        (tmp_path / "01-fact-base.md").write_text(fact_base, encoding="utf-8")
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


# --------------------------------------------------------------------------
# fact-id cross-reference -- a citation must resolve to a real entry
# --------------------------------------------------------------------------

def test_collects_defined_ids_from_headings():
    assert collect_defined_fact_ids(FACT_BASE) == {"F-012", "F-021"}


def test_ignores_ids_that_are_only_cited_not_defined():
    text = "Some prose citing [F-999] without defining it.\n## F-012 — real entry\n"
    assert collect_defined_fact_ids(text) == {"F-012"}


def test_dangling_citation_flagged():
    findings = find_dangling_fact_ids("Cost is €3,180 [F-99999].", P, {"F-012"})
    assert len(findings) == 1
    assert findings[0].kind == "dangling-fact-id"
    assert "F-99999" in findings[0].detail


def test_resolving_citation_accepted():
    assert find_dangling_fact_ids("Cost is €3,180 [F-012].", P, {"F-012"}) == []


def test_dangling_citation_fails_a_round(tmp_path):
    """The headline case: a fabricated or mistyped fact id reaches the
    recommendation and nothing previously noticed."""
    dirty = FULL_LENS.replace("## Findings\nx", "## Findings\nCost is €3,180 [F-99999].")
    conflict = "## K-01\nA real and decisive disagreement between two lenses, described at length.\n"
    report = run_qc(_write_round(tmp_path, conflict_map=conflict, lens_body=dirty))
    assert len(report.dangling_fact_ids) == 1
    assert not report.ok
    assert "do not exist" in report.summary()


def test_missing_fact_base_is_reported_once_not_per_citation(tmp_path):
    report = run_qc(
        _write_round(tmp_path, conflict_map="## K-01\n" + "x" * 100, lens_body=FULL_LENS, fact_base=None)
    )
    assert report.missing_fact_base
    assert report.dangling_fact_ids == []
    assert not report.ok


def test_fact_base_itself_is_not_scanned_for_untagged_numbers(tmp_path):
    """The fact base is the source of F-ids, so its own numbers carry no
    citations. Scanning it would flag every entry it defines."""
    conflict = "## K-01\nOperations and Commercial disagree on achievable margin, and the gap is decisive for the recommendation.\n"
    report = run_qc(_write_round(tmp_path, conflict_map=conflict, lens_body=FULL_LENS))
    assert report.untagged == []
    assert report.ok, report.summary()


# --------------------------------------------------------------------------
# estimate reproducibility
# --------------------------------------------------------------------------

def test_estimate_naming_a_fact_accepted():
    assert check_estimate_tags("TAM ~€900M [EST: F-012 volume x F-018 price]", P) == []


def test_estimate_naming_a_context_file_accepted():
    assert check_estimate_tags("Floor 34% [EST: C-finance/unit-econ.md]", P) == []


def test_estimate_showing_arithmetic_accepted():
    assert check_estimate_tags("Value €13.0B [EST: 3.1 × 4200]", P) == []


def test_vague_estimate_rejected():
    findings = check_estimate_tags("Margin ~12% [EST: vibes]", P)
    assert len(findings) == 1
    assert findings[0].kind == "unreproducible-estimate"


def test_empty_estimate_rejected():
    findings = check_estimate_tags("Margin ~12% [EST:]", P)
    assert len(findings) == 1
    assert "states no method" in findings[0].detail


def test_weak_estimate_fails_a_round(tmp_path):
    dirty = FULL_LENS.replace("## Findings\nx", "## Findings\nMargin ~12% [EST: industry experience].")
    conflict = "## K-01\nA real and decisive disagreement between two lenses, described at length.\n"
    report = run_qc(_write_round(tmp_path, conflict_map=conflict, lens_body=dirty))
    assert len(report.weak_estimates) == 1
    assert not report.ok


def test_all_findings_collects_every_category():
    r = QCReport(
        untagged=[Finding(P, 1, "a", "d", "l")],
        dangling_fact_ids=[Finding(P, 2, "b", "d", "l")],
        weak_estimates=[Finding(P, 3, "c", "d", "l")],
    )
    assert len(r.all_findings()) == 3
