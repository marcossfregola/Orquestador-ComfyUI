"""Session-scoped authorization for the durable product-queue policy."""
from __future__ import annotations

import threading

from ..domain.core import QueueStartMode


class QueueDispatchError(ValueError):
    """A queue dispatch policy operation is invalid or unavailable."""


class QueueDispatchSession:
    """Coordinate durable queue policy with a process-local manual gate.

    A new instance is created for each application runtime, so manual
    permission always starts closed and is never persisted.  The lock
    serializes UI policy changes with scheduler claims and authorization
    checks for active recovery.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._manual_open = False

    @staticmethod
    def _mode(mode):
        try:
            return QueueStartMode(mode)
        except (TypeError, ValueError) as exc:
            raise QueueDispatchError("queue start mode must be auto or manual") from exc

    def snapshot(self, repository):
        with self._lock:
            mode = self._mode(repository.get_queue_start_mode())
            return mode, bool(mode is QueueStartMode.MANUAL and self._manual_open)

    def claim_next(self, repository):
        with self._lock:
            return repository.claim_next_queue_item(
                manual_dispatch_open=self._manual_open
            )

    def permits_new_dispatch(self, repository):
        with self._lock:
            mode = self._mode(repository.get_queue_start_mode())
            return mode is QueueStartMode.AUTO or self._manual_open

    def set_mode(self, repository, mode):
        selected = self._mode(mode)
        with self._lock:
            current = self._mode(repository.get_queue_start_mode())
            if selected is current:
                return current
            # Close before making manual durable.  Claims use this same lock,
            # so no later claim can observe the old gate after this operation.
            self._manual_open = False
            return self._mode(repository.set_queue_start_mode(selected))

    def start_manual_session(self, repository):
        with self._lock:
            mode = self._mode(repository.get_queue_start_mode())
            if mode is not QueueStartMode.MANUAL:
                raise QueueDispatchError(
                    "Iniciar/Reanudar cola sólo habilita el modo manual"
                )
            self._manual_open = True
            return True


__all__ = ["QueueDispatchError", "QueueDispatchSession"]
