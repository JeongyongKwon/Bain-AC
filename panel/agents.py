"""Load agent definitions from .claude/agents/*.md into plain Python values.

The markdown files stay the single source of truth -- a strategist can edit a
lens prompt without touching Python, and the same files still work when the
panel is driven interactively from Claude Code. This module is the bridge, not
a second definition of the roster.

Deliberately provider-agnostic: a `LoadedAgent` is a name, a description, a
prompt, a tool list, and a model string -- nothing here imports a model API's
SDK. That conversion happens once, inside whichever `panel.runners.AgentRunner`
is selected for the round, so this module does not need to change when the
API behind the panel does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)

# Output language is injected at load time rather than written into each
# prompt, so one roster serves every language the team reports in.
_LANG_DIRECTIVE = {
    "ko": (
        "\n\n## 출력 언어\n\n"
        "보고서 본문은 한국어로 작성한다. 다음은 원문 그대로 유지한다: "
        "증거 태그(`[F-012]`, `[R-p14]`, `[C-...]`, `[EST: ...]`, `[ASSUMPTION]`), "
        "고유명사, 회사명, 인용문, 파일 경로, 섹션 제목의 영문 식별자. "
        "인용(verbatim)은 반드시 원어 그대로 두고, 필요하면 괄호 안에 번역을 덧붙인다."
    ),
    "en": "",
}


KNOWN_FRONTMATTER_KEYS = frozenset({"name", "description", "tools", "skills", "model"})


class AgentLoadError(RuntimeError):
    """Raised when an agent file is malformed -- fail loudly at startup."""


def _as_list(raw: object) -> list[str]:
    """Frontmatter lists may be written comma-separated or as a YAML list."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    return [str(item).strip() for item in raw if str(item).strip()]


@dataclass(frozen=True)
class LoadedAgent:
    """A parsed agent definition -- provider-neutral, ready for any runner.

    `model` is the raw string from frontmatter (`opus`, `sonnet`, `inherit`,
    or whatever alias scheme the target API uses). Interpreting it is the
    active runner's job, not this module's -- see panel/runners/base.py.
    """

    name: str
    description: str
    prompt: str
    tools: list[str]
    model: str
    source: Path
    skills: list[str] = field(default_factory=list)


def parse_agent(text: str, source: Path) -> LoadedAgent:
    match = FRONTMATTER.match(text)
    if not match:
        raise AgentLoadError(f"{source}: missing YAML frontmatter delimited by ---")

    raw, body = match.groups()
    try:
        meta = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise AgentLoadError(f"{source}: invalid YAML frontmatter: {exc}") from exc

    for key in ("name", "description"):
        if not meta.get(key):
            raise AgentLoadError(f"{source}: frontmatter is missing required key {key!r}")

    # Reject unknown keys rather than dropping them. Silent discard means a
    # typo in `tools:` -- the field that enforces an agent's capability
    # boundary -- vanishes without a word, and the agent runs with the
    # runner's defaults instead of the restrictions its author intended.
    unknown = sorted(set(meta) - KNOWN_FRONTMATTER_KEYS)
    if unknown:
        raise AgentLoadError(
            f"{source}: unknown frontmatter key(s): {', '.join(unknown)}; "
            f"expected any of {', '.join(sorted(KNOWN_FRONTMATTER_KEYS))}"
        )

    if not body.strip():
        raise AgentLoadError(f"{source}: agent body is empty -- there is no prompt to run")

    return LoadedAgent(
        name=str(meta["name"]),
        description=str(meta["description"]),
        prompt=body.strip(),
        tools=_as_list(meta.get("tools")),
        skills=_as_list(meta.get("skills")),
        model=str(meta.get("model", "inherit")),
        source=source,
    )


def load_roster(agents_dir: Path, lang: str = "en") -> dict[str, LoadedAgent]:
    """Load every agent definition, appending the output-language directive."""
    if not agents_dir.is_dir():
        raise AgentLoadError(f"{agents_dir} does not exist -- no agents to load")

    directive = _LANG_DIRECTIVE.get(lang)
    if directive is None:
        raise AgentLoadError(f"unsupported language {lang!r}; expected one of {sorted(_LANG_DIRECTIVE)}")

    roster: dict[str, LoadedAgent] = {}
    for path in sorted(agents_dir.glob("*.md")):
        agent = parse_agent(path.read_text(encoding="utf-8"), path)
        if agent.name in roster:
            raise AgentLoadError(
                f"{path}: duplicate agent name {agent.name!r}, already defined in {roster[agent.name].source}"
            )
        if directive:
            agent = LoadedAgent(**{**agent.__dict__, "prompt": agent.prompt + directive})
        roster[agent.name] = agent

    if not roster:
        raise AgentLoadError(f"{agents_dir} contains no agent definitions")
    return roster


def validate_roster(roster: dict[str, LoadedAgent], required: tuple[str, ...]) -> None:
    """Fail before spending money if the pipeline references a missing agent."""
    missing = [name for name in required if name not in roster]
    if missing:
        raise AgentLoadError(
            "roster is missing agents required by the pipeline: "
            + ", ".join(missing)
            + f"\navailable: {', '.join(sorted(roster))}"
        )
