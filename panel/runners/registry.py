"""Runner discovery: name -> class, resolved lazily so switching providers
never requires an unrelated dependency to be installed.

Every built-in runner's module is imported only on first `get_runner()` call
for that name, not at package import time. A project that only ever selects
`mock` (this test suite, for instance) never imports `claude_agent_sdk` and
therefore never needs it installed.
"""

from __future__ import annotations

from panel.runners.base import AgentRunner

_BUILTIN_MODULES: dict[str, str] = {
    "claude-agent-sdk": "panel.runners.claude_agent_sdk:ClaudeAgentSDKRunner",
    "mock": "panel.runners.mock:MockRunner",
}

_registry: dict[str, type[AgentRunner]] = {}


class UnknownRunnerError(ValueError):
    pass


def register_runner(cls: type[AgentRunner]) -> type[AgentRunner]:
    """Register a runner class, keyed by its `name` attribute.

    Usable as a decorator for a runner defined outside this package --
    a project-specific runner does not need to live under panel/runners/,
    it just needs to call this before `get_runner()` is asked for it.
    """
    if not getattr(cls, "name", None):
        raise ValueError(f"{cls!r} must set a non-empty `name` class attribute")
    _registry[cls.name] = cls
    return cls


def available_runners() -> list[str]:
    return sorted({*_registry, *_BUILTIN_MODULES})


def get_runner(name: str) -> AgentRunner:
    """Instantiate the named runner, importing its module on first use."""
    if name not in _registry and name in _BUILTIN_MODULES:
        module_path, _, class_name = _BUILTIN_MODULES[name].partition(":")
        import importlib

        module = importlib.import_module(module_path)
        register_runner(getattr(module, class_name))

    if name not in _registry:
        raise UnknownRunnerError(
            f"unknown runner {name!r}; available: {', '.join(available_runners())}"
        )
    return _registry[name]()
