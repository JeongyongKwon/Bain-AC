from pathlib import Path

import pytest

from panel.agents import AgentLoadError, load_roster, parse_agent, validate_roster
from panel.config import PIPELINE, REQUIRED_AGENTS, slugify

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = PROJECT_ROOT / ".claude" / "agents"

VALID = """---
name: test-agent
description: Does a thing.
tools: Read, Write, Grep
model: sonnet
---

You are a test agent. Do the thing well.
"""


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def test_parses_frontmatter_and_body():
    agent = parse_agent(VALID, Path("test.md"))
    assert agent.name == "test-agent"
    assert agent.model == "sonnet"
    assert agent.tools == ["Read", "Write", "Grep"]
    assert agent.prompt.startswith("You are a test agent")
    assert "---" not in agent.prompt


def test_missing_frontmatter_rejected():
    with pytest.raises(AgentLoadError, match="frontmatter"):
        parse_agent("Just a prompt, no metadata.", Path("bad.md"))


def test_missing_name_rejected():
    text = VALID.replace("name: test-agent\n", "")
    with pytest.raises(AgentLoadError, match="'name'"):
        parse_agent(text, Path("bad.md"))


def test_empty_body_rejected():
    with pytest.raises(AgentLoadError, match="empty"):
        parse_agent("---\nname: x\ndescription: y\n---\n\n   \n", Path("bad.md"))


def test_model_defaults_to_inherit():
    text = VALID.replace("model: sonnet\n", "")
    assert parse_agent(text, Path("t.md")).model == "inherit"


# --------------------------------------------------------------------------
# the real roster on disk
# --------------------------------------------------------------------------

def test_real_roster_loads():
    roster = load_roster(AGENTS_DIR)
    assert len(roster) == 10


def test_real_roster_satisfies_pipeline():
    validate_roster(load_roster(AGENTS_DIR), REQUIRED_AGENTS)


def test_pipeline_covers_every_agent():
    in_pipeline = {name for phase in PIPELINE for name in phase.agents}
    assert in_pipeline == set(load_roster(AGENTS_DIR))


def test_lenses_cannot_run_bash():
    """Tool restriction is enforced by the runtime, not by asking politely."""
    roster = load_roster(AGENTS_DIR)
    for name, agent in roster.items():
        if name.startswith("lens-"):
            assert "Bash" not in agent.tools, f"{name} must not have shell access"


def test_partner_cannot_search_the_web():
    """The Partner decides from the fact base; it does not gather new evidence."""
    partner = load_roster(AGENTS_DIR)["partner-synthesis"]
    assert "WebSearch" not in partner.tools
    assert "WebFetch" not in partner.tools


def test_research_desk_is_the_only_agent_with_bash():
    roster = load_roster(AGENTS_DIR)
    with_bash = {n for n, a in roster.items() if "Bash" in a.tools}
    assert with_bash == {"research-desk"}


def test_model_routing_matches_cost_model():
    roster = load_roster(AGENTS_DIR)
    assert roster["research-desk"].model == "opus"
    assert roster["red-team"].model == "opus"
    assert roster["partner-synthesis"].model == "opus"
    assert all(a.model == "sonnet" for n, a in roster.items() if n.startswith("lens-"))


def test_missing_agent_reported_before_spending():
    with pytest.raises(AgentLoadError, match="missing agents"):
        validate_roster(load_roster(AGENTS_DIR), ("lens-nonexistent",))


# --------------------------------------------------------------------------
# output language injection
# --------------------------------------------------------------------------

def test_korean_directive_appended():
    roster = load_roster(AGENTS_DIR, lang="ko")
    assert "출력 언어" in roster["partner-synthesis"].prompt


def test_english_leaves_prompt_untouched():
    en = load_roster(AGENTS_DIR, lang="en")["partner-synthesis"].prompt
    assert "출력 언어" not in en


def test_unsupported_language_rejected():
    with pytest.raises(AgentLoadError, match="unsupported language"):
        load_roster(AGENTS_DIR, lang="fr")


# --------------------------------------------------------------------------
# slug handling
# --------------------------------------------------------------------------

def test_slugify_ascii():
    assert slugify("EU Heat Pump Market 2026") == "eu-heat-pump-market-2026"


def test_slugify_keeps_hangul():
    assert slugify("2026 시장 분석") == "2026-시장-분석"


def test_slugify_strips_punctuation():
    assert slugify("Q3/Q4 — report (final).v2") == "q3q4-report-finalv2"


def test_slugify_never_empty():
    assert slugify("!!!") == "round"
