"""What the prompt and agent suite services share with the routes and the chat tools."""

from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any


class EvalNotFoundError(LookupError):
    """A suite, test case, run or workflow the user cannot reach, or that does not exist."""


@dataclass(frozen=True)
class DeferredJob:
    """A background job and its keyword arguments, started once the request has committed.

    A route queues it with ``background_tasks.add_task(job.func, **job.kwargs)``; the chat
    starts ``job.coroutine()`` detached, so the run outlives the turn that started it.
    """

    func: Callable[..., Coroutine[Any, Any, None]]
    kwargs: dict[str, Any] = field(default_factory=dict)

    def coroutine(self) -> Coroutine[Any, Any, None]:
        return self.func(**self.kwargs)
