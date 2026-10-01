from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from types import TracebackType

logger = logging.getLogger(__name__)

_REGISTRY_LOCK = threading.Lock()


def _attach_cancel_listener(
    event: threading.Event, listener: Callable[[], None]
) -> Callable[[], None]:
    """Attach a callback to be invoked when ``event.set()`` is called.

    Returns a callable to detach the listener.
    """
    with _REGISTRY_LOCK:
        if event.is_set():
            try:
                listener()
            except Exception:
                logger.exception("Error in immediate cancel listener execution")
            return lambda: None

        listeners: list[Callable[[], None]] | None = getattr(event, "_cancel_listeners", None)
        if listeners is None:
            listeners = []
            event._cancel_listeners = listeners  # type: ignore[attr-defined]
            orig_set = event.set

            def wrapped_set() -> None:
                orig_set()
                with _REGISTRY_LOCK:
                    cbs = list(getattr(event, "_cancel_listeners", []))
                for cb in cbs:
                    try:
                        cb()
                    except Exception:
                        logger.exception("Error executing cancel listener")

            event.set = wrapped_set  # type: ignore[assignment]
        listeners.append(listener)

    def detach() -> None:
        with _REGISTRY_LOCK:
            current_listeners = getattr(event, "_cancel_listeners", None)
            if current_listeners is not None and listener in current_listeners:
                current_listeners.remove(listener)

    return detach


class CancellationBridge:
    """Bridges parent cancellation into child cancellation while the child is active.

    Ensures the bridge thread unblocks and terminates immediately when child work
    completes, eliminating thread leaks without polling or arbitrary sleeps.
    """

    def __init__(
        self,
        parent_event: threading.Event | None,
        child_event: threading.Event,
        bridge_name: str = "_bridge_cancel",
    ) -> None:
        self._parent_event = parent_event
        self._child_event = child_event
        self._bridge_name = bridge_name
        self._cond = threading.Condition()
        self._done = False
        self._detach: Callable[[], None] | None = None
        self._thread: threading.Thread | None = None
        self._closed = False
        self._lock = threading.Lock()

        if self._parent_event is None:
            return

        if self._parent_event.is_set():
            self._child_event.set()
            return

        def on_parent_cancel() -> None:
            with self._cond:
                self._cond.notify_all()

        self._detach = _attach_cancel_listener(self._parent_event, on_parent_cancel)

        # Double check after attaching listener
        if self._parent_event.is_set():
            self._child_event.set()
            if self._detach:
                self._detach()
                self._detach = None
            return

        # Define bridge function with the explicit target name requested
        if bridge_name == "_bridge_exec_node_cancel":

            def _bridge_exec_node_cancel() -> None:
                with self._cond:
                    while not self._parent_event.is_set() and not self._done:
                        self._cond.wait()
                if self._parent_event.is_set():
                    self._child_event.set()

            target_fn = _bridge_exec_node_cancel
        elif bridge_name == "_bridge_parent_cancel":

            def _bridge_parent_cancel() -> None:
                with self._cond:
                    while not self._parent_event.is_set() and not self._done:
                        self._cond.wait()
                if self._parent_event.is_set():
                    self._child_event.set()

            target_fn = _bridge_parent_cancel
        else:

            def _bridge_generic_cancel() -> None:
                with self._cond:
                    while not self._parent_event.is_set() and not self._done:
                        self._cond.wait()
                if self._parent_event.is_set():
                    self._child_event.set()

            target_fn = _bridge_generic_cancel

        self._thread = threading.Thread(
            target=target_fn,
            name=bridge_name,
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        """Signal the bridge thread to finish and wait for it to exit."""
        with self._lock:
            if self._closed:
                return
            self._closed = True

        with self._cond:
            self._done = True
            self._cond.notify_all()

        if self._detach is not None:
            self._detach()
            self._detach = None

        if self._thread is not None and self._thread.is_alive():
            if threading.current_thread() != self._thread:
                self._thread.join()

    def __enter__(self) -> CancellationBridge:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()
