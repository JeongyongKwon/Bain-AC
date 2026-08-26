"""The provider boundary: everything the rest of the codebase should import.

    from panel.runners import AgentRunner, RunnerOutcome, get_runner

Add a new provider by writing a class here (or anywhere -- see
`register_runner`) that implements `AgentRunner.run()`, then registering its
name in `registry.py`'s `_BUILTIN_MODULES`, or calling `register_runner`
yourself if it lives outside this package entirely.
"""

from panel.runners.base import AgentRunner, RunnerOutcome
from panel.runners.registry import (
    UnknownRunnerError,
    available_runners,
    get_runner,
    register_runner,
)

__all__ = [
    "AgentRunner",
    "RunnerOutcome",
    "UnknownRunnerError",
    "available_runners",
    "get_runner",
    "register_runner",
]
