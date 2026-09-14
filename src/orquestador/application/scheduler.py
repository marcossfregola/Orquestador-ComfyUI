"""F13.8 single-execution scheduler over the durable product queue.

The scheduler owns only promotion and dispatch authority.  The existing
StartGuiChainUseCase/ChainExecutionUseCase stack remains the sole generation
engine; this module reaches it through a narrow claimed-item boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import threading

from ..domain.core import Lifecycle, QueueClaimStatus
from .queue_recovery import QueueRecoveryOutcome


class SchedulerError(RuntimeError):
    """The scheduler could not safely continue."""


class SchedulerLockError(SchedulerError):
    """Another local scheduler authority already owns this project root."""


class SchedulerInstanceLock:
    """One process-local scheduler lock, backed by an OS file lock.

    The lock file intentionally remains after release.  The OS lock is tied
    to the open descriptor, so it is released after a process crash without
    interpreting a stale pathname as live scheduler authority.
    """

    def __init__(self, root, filename=".orquestador-scheduler.lock"):
        base = Path(root).resolve()
        if not isinstance(filename, str) or not filename or Path(filename).name != filename:
            raise SchedulerLockError("scheduler lock filename is invalid")
        self.path = base / filename
        self._fd: int | None = None

    @property
    def is_held(self):
        return self._fd is not None

    @staticmethod
    def _lock_descriptor(fd):
        try:
            import msvcrt
        except ImportError:
            try:
                import fcntl
            except ImportError as exc:
                raise SchedulerLockError("no supported local file-lock primitive") from exc
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    @staticmethod
    def _unlock_descriptor(fd):
        try:
            import msvcrt
        except ImportError:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
        else:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

    def acquire(self):
        if self._fd is not None:
            return self
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as exc:
            raise SchedulerLockError(f"scheduler lock open failed: {exc}") from exc
        try:
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
            os.lseek(fd, 0, os.SEEK_SET)
            self._lock_descriptor(fd)
        except OSError as exc:
            os.close(fd)
            raise SchedulerLockError("another local scheduler already owns this project root") from exc
        except Exception:
            os.close(fd)
            raise
        self._fd = fd
        return self

    def release(self):
        fd = self._fd
        if fd is None:
            return
        self._fd = None
        error = None
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            self._unlock_descriptor(fd)
        except OSError as exc:
            error = exc
        finally:
            os.close(fd)
        if error is not None:
            raise SchedulerLockError(f"scheduler lock release failed: {error}") from error

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_):
        self.release()


class SchedulerTickOutcome(str, Enum):
    NOT_STARTED = "not_started"
    BUSY = "busy"
    IDLE = "idle"
    PAUSED = "paused"
    RECOVERY_REQUIRED = "recovery_required"
    FINISHED = "finished"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class SchedulerTickResult:
    outcome: SchedulerTickOutcome
    queue_item_id: str | None = None
    execution_id: str | None = None
    reason: str = ""


class SchedulerExecutionBoundary:
    """Explicit authorization bridge from a durable claim to the old motor."""

    def __init__(self, start_claimed, *, reconcile_active=None, readiness=None):
        if not callable(start_claimed):
            raise SchedulerError("scheduler claimed-start boundary must be callable")
        if reconcile_active is not None and not callable(reconcile_active):
            raise SchedulerError("scheduler active-recovery boundary must be callable")
        if readiness is not None and not callable(readiness):
            raise SchedulerError("scheduler readiness boundary must be callable")
        self._start_claimed = start_claimed
        self._reconcile_active = reconcile_active
        self._readiness = readiness

    def ensure_ready(self):
        if self._readiness is not None:
            self._readiness()

    def start_claimed(self, project_id, execution_id, queue_item_id):
        return self._start_claimed(project_id, execution_id, queue_item_id)

    @property
    def supports_active_reconciliation(self):
        return self._reconcile_active is not None

    def reconcile_active(self, project_id, execution_id, queue_item_id):
        if self._reconcile_active is None:
            raise SchedulerError("scheduler active-recovery boundary is unavailable")
        return self._reconcile_active(project_id, execution_id, queue_item_id)


class SingleExecutionScheduler:
    """Deterministic application scheduler; callers choose its worker thread."""

    def __init__(self, repository, execution_boundary, instance_lock):
        if repository is None:
            raise SchedulerError("scheduler repository is required")
        if not callable(getattr(execution_boundary, "start_claimed", None)):
            raise SchedulerError("scheduler execution boundary is invalid")
        if not callable(getattr(instance_lock, "acquire", None)) or not callable(
            getattr(instance_lock, "release", None)
        ):
            raise SchedulerError("scheduler instance lock is invalid")
        self.repository = repository
        self.execution_boundary = execution_boundary
        self.instance_lock = instance_lock
        self._started = False
        self._drive_lock = threading.Lock()

    @property
    def started(self):
        return self._started

    def start(self):
        if self._started:
            return self
        self.instance_lock.acquire()
        self._started = True
        return self

    def stop(self):
        if not self._started:
            return
        self._started = False
        self.instance_lock.release()

    def close(self):
        try:
            self.stop()
        finally:
            close = getattr(self.repository, "close", None)
            if callable(close):
                close()

    @staticmethod
    def _result(outcome, queue_item_id=None, execution_id=None, reason=""):
        return SchedulerTickResult(
            SchedulerTickOutcome(outcome),
            None if queue_item_id is None else str(queue_item_id),
            None if execution_id is None else str(execution_id),
            reason,
        )

    def _load_claimed_execution(self, execution_id):
        project_id = self.repository.execution_project_id(execution_id)
        project, executions = self.repository.load(project_id)
        matches = [entry for entry in executions if str(entry.id) == str(execution_id)]
        if len(matches) != 1:
            raise SchedulerError("claimed execution selection is missing or ambiguous")
        return project, matches[0]

    def _reconcile_active(self, queue_item_id):
        """Drive only the durable survivor before considering another claim."""
        if not getattr(self.execution_boundary, "supports_active_reconciliation", False):
            return self._result(
                SchedulerTickOutcome.RECOVERY_REQUIRED,
                queue_item_id,
                reason="durable active queue item requires F13.9 reconciliation",
            )
        try:
            control = self.repository.get_queue_control()
        except Exception as exc:
            return self._result(
                SchedulerTickOutcome.BLOCKED,
                queue_item_id,
                reason=f"active queue control reload failed: {exc}",
            )
        if control.paused:
            return self._result(
                SchedulerTickOutcome.RECOVERY_REQUIRED,
                queue_item_id,
                reason="active queue item is paused; reconciliation is deferred",
            )
        try:
            item = self.repository.get_queue_item(queue_item_id)
            project, execution = self._load_claimed_execution(item.execution_id)
        except Exception as exc:
            return self._result(
                SchedulerTickOutcome.BLOCKED,
                queue_item_id,
                reason=f"active queue execution load failed: {exc}",
            )
        try:
            recovery = self.execution_boundary.reconcile_active(
                str(project.id), str(execution.id), str(item.id)
            )
        except Exception as exc:
            return self._result(
                SchedulerTickOutcome.BLOCKED,
                item.id,
                item.execution_id,
                f"active queue reconciliation failed: {exc}",
            )
        if str(getattr(recovery, "execution_id", execution.id)) != str(execution.id):
            return self._result(
                SchedulerTickOutcome.BLOCKED,
                item.id,
                item.execution_id,
                "active queue reconciliation returned a mismatched execution",
            )
        outcome = getattr(recovery, "outcome", None)
        if outcome is QueueRecoveryOutcome.TERMINAL:
            try:
                _, refreshed = self._load_claimed_execution(item.execution_id)
            except Exception as exc:
                return self._result(
                    SchedulerTickOutcome.BLOCKED,
                    item.id,
                    item.execution_id,
                    f"reconciled execution reload failed: {exc}",
                )
            if refreshed.state not in {
                Lifecycle.SUCCEEDED,
                Lifecycle.FAILED,
                Lifecycle.CANCELLED,
            }:
                return self._result(
                    SchedulerTickOutcome.BLOCKED,
                    item.id,
                    item.execution_id,
                    "active queue reconciliation reported terminal without a terminal execution",
                )
            try:
                self.repository.finish_claimed_queue_item(item.id, item.execution_id)
            except Exception as exc:
                return self._result(
                    SchedulerTickOutcome.BLOCKED,
                    item.id,
                    item.execution_id,
                    f"queue completion failed: {exc}",
                )
            return self._result(SchedulerTickOutcome.FINISHED, item.id, item.execution_id)
        if outcome in {QueueRecoveryOutcome.WAIT, QueueRecoveryOutcome.MANUAL_REVIEW}:
            return self._result(
                SchedulerTickOutcome.RECOVERY_REQUIRED,
                item.id,
                item.execution_id,
                getattr(recovery, "reason", "") or "active queue reconciliation is incomplete",
            )
        return self._result(
            SchedulerTickOutcome.BLOCKED,
            item.id,
            item.execution_id,
            getattr(recovery, "reason", "") or "active queue reconciliation is blocked",
        )

    def tick(self):
        """Drive one durable item, reconciling a survivor before any new claim."""
        if not self._started:
            return self._result(SchedulerTickOutcome.NOT_STARTED)
        if not self._drive_lock.acquire(blocking=False):
            return self._result(SchedulerTickOutcome.BUSY)
        try:
            try:
                readiness = getattr(self.execution_boundary, "ensure_ready", None)
                if callable(readiness):
                    readiness()
            except Exception as exc:
                return self._result(SchedulerTickOutcome.BLOCKED, reason=f"scheduler readiness failed: {exc}")
            try:
                claim = self.repository.claim_next_queue_item()
            except Exception as exc:
                return self._result(SchedulerTickOutcome.BLOCKED, reason=f"queue claim failed: {exc}")
            if claim.status is QueueClaimStatus.EMPTY:
                return self._result(SchedulerTickOutcome.IDLE)
            if claim.status is QueueClaimStatus.PAUSED:
                return self._result(SchedulerTickOutcome.PAUSED)
            if claim.status is QueueClaimStatus.ACTIVE_PRESENT:
                return self._reconcile_active(claim.active_queue_item_id)
            if claim.status is not QueueClaimStatus.CLAIMED or claim.item is None:
                return self._result(SchedulerTickOutcome.BLOCKED, reason="invalid queue claim result")
            item = claim.item
            try:
                project, execution = self._load_claimed_execution(item.execution_id)
            except Exception as exc:
                return self._result(
                    SchedulerTickOutcome.BLOCKED,
                    item.id,
                    item.execution_id,
                    f"claimed execution load failed: {exc}",
                )
            try:
                self.execution_boundary.start_claimed(
                    str(project.id), str(execution.id), str(item.id)
                )
            except Exception as exc:
                return self._result(
                    SchedulerTickOutcome.BLOCKED,
                    item.id,
                    item.execution_id,
                    f"claimed execution start failed: {exc}",
                )
            try:
                _, refreshed = self._load_claimed_execution(item.execution_id)
            except Exception as exc:
                return self._result(
                    SchedulerTickOutcome.BLOCKED,
                    item.id,
                    item.execution_id,
                    f"claimed execution reload failed: {exc}",
                )
            if refreshed.state not in {
                Lifecycle.SUCCEEDED,
                Lifecycle.FAILED,
                Lifecycle.CANCELLED,
            }:
                return self._result(
                    SchedulerTickOutcome.RECOVERY_REQUIRED,
                    item.id,
                    item.execution_id,
                    "claimed execution remains nonterminal; F13.9 reconciliation is required",
                )
            try:
                self.repository.finish_claimed_queue_item(item.id, item.execution_id)
            except Exception as exc:
                return self._result(
                    SchedulerTickOutcome.BLOCKED,
                    item.id,
                    item.execution_id,
                    f"queue completion failed: {exc}",
                )
            return self._result(SchedulerTickOutcome.FINISHED, item.id, item.execution_id)
        finally:
            self._drive_lock.release()


class SchedulerBackgroundRunner:
    """Thin non-Qt runtime adapter around ``SingleExecutionScheduler``."""

    def __init__(self, scheduler_factory, *, poll_interval=0.25, startup_timeout=10.0):
        if not callable(scheduler_factory):
            raise SchedulerError("scheduler factory must be callable")
        if poll_interval <= 0 or startup_timeout <= 0:
            raise SchedulerError("scheduler intervals must be positive")
        self._factory = scheduler_factory
        self._poll_interval = poll_interval
        self._startup_timeout = startup_timeout
        self._stop_event = threading.Event()
        self._startup_event = threading.Event()
        self._state_lock = threading.Lock()
        self._thread = None
        self._startup_error = None
        self.last_result = None

    @property
    def running(self):
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self):
        with self._state_lock:
            if self.running:
                return self
            self._stop_event.clear()
            self._startup_event.clear()
            self._startup_error = None
            self.last_result = None
            self._thread = threading.Thread(
                target=self._run,
                name="orquestador-single-execution-scheduler",
                daemon=True,
            )
            self._thread.start()
        if not self._startup_event.wait(self._startup_timeout):
            self.stop(timeout=0)
            raise SchedulerError("scheduler runtime did not start in time")
        if self._startup_error is not None:
            error = self._startup_error
            self.stop(timeout=0)
            if isinstance(error, SchedulerError):
                raise error
            raise SchedulerError(f"scheduler runtime startup failed: {error}") from error
        return self

    def _run(self):
        scheduler = None
        try:
            scheduler = self._factory()
            scheduler.start()
        except Exception as exc:
            self._startup_error = exc
            self._startup_event.set()
            if scheduler is not None:
                try:
                    scheduler.close()
                except Exception:
                    pass
            return
        self._startup_event.set()
        try:
            while not self._stop_event.is_set():
                self.last_result = scheduler.tick()
                delay = 0 if self.last_result.outcome is SchedulerTickOutcome.FINISHED else self._poll_interval
                if delay:
                    self._stop_event.wait(delay)
        finally:
            scheduler.close()

    def stop(self, *, timeout=5.0):
        self._stop_event.set()
        thread = self._thread
        if thread is None or thread is threading.current_thread():
            return True
        thread.join(timeout)
        return not thread.is_alive()


__all__ = [
    "SchedulerBackgroundRunner",
    "SchedulerError",
    "SchedulerExecutionBoundary",
    "SchedulerInstanceLock",
    "SchedulerLockError",
    "SchedulerTickOutcome",
    "SchedulerTickResult",
    "SingleExecutionScheduler",
]
