"""Fail-closed cancellation of ComfyUI jobs.

The safe F3-4 operation is deliberately narrow: a prompt may be removed from
the pending queue and the removal must then be verified with fresh queue and
history reads. A running prompt is never interrupted by this adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import socket
from collections.abc import Mapping
from typing import Any

from ..domain.core import BackendJobRef
from .http import (
    ComfyUIClient,
    ComfyUIProtocolError,
    ComfyUIRejectedError,
    ComfyUIServerError,
    ComfyUITransportError,
    ComfyUITimeoutError,
    HistoryResult,
    HistoryState,
    QueueSnapshot,
    QueueState,
)


class CancellationClassification(str, Enum):
    TARGET_PENDING = "target_pending"
    TARGET_RUNNING = "target_running"
    ALREADY_TERMINAL = "already_terminal"
    NOT_FOUND = "not_found"
    CONTRADICTORY = "contradictory"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


class CancellationState(str, Enum):
    CONFIRMED = "confirmed"
    REQUESTED = "requested"
    ALREADY_TERMINAL = "already_terminal"
    NOT_FOUND = "not_found"
    RUNNING_INTERRUPT_UNSAFE = "running_interrupt_unsafe"
    CONTRADICTORY = "contradictory"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"
    UNKNOWN = "unknown"
    RACED_TERMINAL = "raced_terminal"


class CancellationAction(str, Enum):
    QUEUE_DELETE = "queue_delete"
    NONE = "none"


class CancellationIssueKind(str, Enum):
    """Stable machine-readable issue classes for reads and mutations."""

    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    PROTOCOL = "protocol"
    REJECTED = "rejected"
    SERVER = "server"


class CancellationPhase(str, Enum):
    PREFLIGHT = "preflight"
    BEFORE_MUTATION = "before_mutation"
    # The request may have reached ComfyUI, so the outcome cannot be retried
    # automatically even when the client observed an error.
    MUTATION_ATTEMPTED_UNCERTAIN = "mutation_attempted_uncertain"
    POST_VERIFICATION = "post_verification"


@dataclass(frozen=True)
class CancellationIssue:
    """Optional structured form of an issue for callers that need one value."""

    kind: CancellationIssueKind
    phase: CancellationPhase
    message: str


@dataclass(frozen=True)
class CancellationPreflight:
    target: BackendJobRef
    classification: CancellationClassification
    queue: QueueSnapshot
    history: HistoryResult
    issue: str | None = None
    issue_kind: CancellationIssueKind | None = None
    phase: CancellationPhase | None = None


@dataclass(frozen=True)
class CancellationResult:
    target: BackendJobRef
    state: CancellationState
    action: CancellationAction
    issue: str | None = None
    preflight: CancellationPreflight | None = None
    issue_kind: CancellationIssueKind | None = None
    phase: CancellationPhase | None = None


_TERMINAL = frozenset({HistoryState.SUCCEEDED, HistoryState.FAILED})


def _issue_kind(exc: BaseException) -> CancellationIssueKind:
    """Map every known ComfyUI/client error deterministically."""

    if isinstance(exc, (ComfyUITimeoutError, TimeoutError, socket.timeout)):
        return CancellationIssueKind.TIMEOUT
    if isinstance(exc, (ComfyUITransportError, OSError)):
        return CancellationIssueKind.TRANSPORT
    if isinstance(exc, ComfyUIProtocolError):
        return CancellationIssueKind.PROTOCOL
    if isinstance(exc, ComfyUIRejectedError):
        return CancellationIssueKind.REJECTED
    if isinstance(exc, ComfyUIServerError):
        return CancellationIssueKind.SERVER
    # Non-ComfyUI exceptions from an injected transport are still fail-closed.
    # Their exact source is not knowable, so SERVER is the stable fallback.
    return CancellationIssueKind.SERVER


def _message(exc: BaseException) -> str:
    value = str(exc).strip()
    return value or exc.__class__.__name__


def _valid_queue(snapshot: Any) -> bool:
    """Reject malformed/internally inconsistent queue evidence."""

    if not isinstance(snapshot, QueueSnapshot) or not isinstance(snapshot.state, QueueState):
        return False
    if not isinstance(snapshot.running, tuple) or not isinstance(snapshot.pending, tuple):
        return False
    for group in (snapshot.running, snapshot.pending):
        seen: set[str] = set()
        for ref in group:
            if not isinstance(ref, BackendJobRef) or ref.value in seen:
                return False
            seen.add(ref.value)
    if snapshot.state is QueueState.UNKNOWN:
        return True
    if snapshot.state is QueueState.EMPTY:
        return not snapshot.running and not snapshot.pending
    if snapshot.state is QueueState.RUNNING:
        return bool(snapshot.running)
    if snapshot.state is QueueState.PENDING:
        return bool(snapshot.pending) and not snapshot.running
    return False


def _valid_history(result: Any, target: BackendJobRef) -> bool:
    return (
        isinstance(result, HistoryResult)
        and isinstance(result.prompt_id, BackendJobRef)
        and result.prompt_id.value == target.value
        and isinstance(result.state, HistoryState)
        and (result.raw is None or isinstance(result.raw, Mapping))
        and (result.error is None or isinstance(result.error, str))
    )


def _unknown_queue() -> QueueSnapshot:
    return QueueSnapshot(state=QueueState.UNKNOWN)


def _unknown_history(target: BackendJobRef, message: str) -> HistoryResult:
    return HistoryResult(target, HistoryState.UNKNOWN, error=message)


class ComfyUICancellationAdapter:
    """Safe pending cancellation adapter over :class:`ComfyUIClient`."""

    def __init__(self, client: ComfyUIClient) -> None:
        self.client = client

    def preflight(self, target: BackendJobRef) -> CancellationPreflight:
        """Read queue/history and classify without performing a mutation."""

        if not isinstance(target, BackendJobRef):
            raise TypeError("target must be BackendJobRef")

        try:
            queue = self.client.queue()
        except Exception as exc:
            message = _message(exc)
            return CancellationPreflight(
                target,
                CancellationClassification.UNKNOWN,
                _unknown_queue(),
                _unknown_history(target, message),
                message,
                _issue_kind(exc),
                CancellationPhase.PREFLIGHT,
            )
        if not _valid_queue(queue):
            message = "queue evidence is malformed"
            return CancellationPreflight(
                target,
                CancellationClassification.UNKNOWN,
                _unknown_queue(),
                _unknown_history(target, message),
                message,
                CancellationIssueKind.PROTOCOL,
                CancellationPhase.PREFLIGHT,
            )

        try:
            history = self.client.history(target)
        except Exception as exc:
            message = _message(exc)
            return CancellationPreflight(
                target,
                CancellationClassification.UNKNOWN,
                queue,
                _unknown_history(target, message),
                message,
                _issue_kind(exc),
                CancellationPhase.PREFLIGHT,
            )
        if not _valid_history(history, target):
            message = "history evidence is malformed or refers to another prompt"
            return CancellationPreflight(
                target,
                CancellationClassification.UNKNOWN,
                queue,
                _unknown_history(target, message),
                message,
                CancellationIssueKind.PROTOCOL,
                CancellationPhase.PREFLIGHT,
            )

        if queue.state is QueueState.UNKNOWN:
            message = "queue evidence is unknown"
            return CancellationPreflight(
                target,
                CancellationClassification.UNKNOWN,
                queue,
                history,
                message,
                CancellationIssueKind.PROTOCOL,
                CancellationPhase.PREFLIGHT,
            )

        target_id = target.value
        pending = any(ref.value == target_id for ref in queue.pending)
        running = any(ref.value == target_id for ref in queue.running)
        history_state = history.state

        if running and pending:
            classification = CancellationClassification.CONTRADICTORY
            message = "target appears in both running and pending queues"
        elif pending:
            # F1-backed policy: a pending queue entry with NOT_FOUND history is
            # still cancellable because ComfyUI may omit non-terminal history.
            if history_state in {HistoryState.QUEUED, HistoryState.NOT_FOUND}:
                classification, message = CancellationClassification.TARGET_PENDING, None
            elif history_state in {HistoryState.RUNNING, HistoryState.SUCCEEDED, HistoryState.FAILED}:
                classification = CancellationClassification.CONTRADICTORY
                message = "pending queue evidence conflicts with history"
            else:
                classification = CancellationClassification.UNKNOWN
                message = "history state is unknown for a pending target"
        elif running:
            if history_state is HistoryState.RUNNING:
                classification, message = CancellationClassification.TARGET_RUNNING, None
            elif history_state in {HistoryState.QUEUED, HistoryState.SUCCEEDED, HistoryState.FAILED}:
                classification = CancellationClassification.CONTRADICTORY
                message = "running queue evidence conflicts with history"
            elif history_state is HistoryState.NOT_FOUND:
                classification = CancellationClassification.AMBIGUOUS
                message = "running target has no history evidence"
            else:
                classification = CancellationClassification.UNKNOWN
                message = "running target has unknown history evidence"
        elif history_state in _TERMINAL:
            classification, message = CancellationClassification.ALREADY_TERMINAL, None
        elif history_state is HistoryState.NOT_FOUND:
            classification, message = CancellationClassification.NOT_FOUND, None
        elif history_state in {HistoryState.RUNNING, HistoryState.QUEUED}:
            classification = CancellationClassification.AMBIGUOUS
            message = "history is non-terminal but target is absent from the queue"
        else:
            classification = CancellationClassification.UNKNOWN
            message = "target state is unknown"

        return CancellationPreflight(
            target,
            classification,
            queue,
            history,
            message,
            CancellationIssueKind.PROTOCOL if classification is CancellationClassification.UNKNOWN else None,
            CancellationPhase.PREFLIGHT if classification is CancellationClassification.UNKNOWN else None,
        )

    @staticmethod
    def _without_mutation(
        target: BackendJobRef,
        preflight: CancellationPreflight,
        state: CancellationState,
    ) -> CancellationResult:
        return CancellationResult(
            target,
            state,
            CancellationAction.NONE,
            preflight.issue,
            preflight,
            preflight.issue_kind,
            preflight.phase,
        )

    def cancel(self, target: BackendJobRef) -> CancellationResult:
        """Cancel a pending target, never interrupting a running target."""

        if not isinstance(target, BackendJobRef):
            raise TypeError("target must be BackendJobRef")
        try:
            preflight = self.preflight(target)
        except Exception as exc:  # defensive for injected/adapted readers
            return CancellationResult(
                target,
                CancellationState.UNKNOWN,
                CancellationAction.NONE,
                _message(exc),
                None,
                _issue_kind(exc),
                CancellationPhase.PREFLIGHT,
            )
        classification = preflight.classification

        if classification is CancellationClassification.ALREADY_TERMINAL:
            return self._without_mutation(target, preflight, CancellationState.ALREADY_TERMINAL)
        if classification is CancellationClassification.NOT_FOUND:
            return self._without_mutation(target, preflight, CancellationState.NOT_FOUND)
        if classification is CancellationClassification.TARGET_RUNNING:
            return CancellationResult(
                target,
                CancellationState.RUNNING_INTERRUPT_UNSAFE,
                CancellationAction.NONE,
                "native /interrupt is non-atomic; running cancellation is refused",
                preflight,
                None,
                CancellationPhase.BEFORE_MUTATION,
            )
        if classification is CancellationClassification.CONTRADICTORY:
            return self._without_mutation(target, preflight, CancellationState.CONTRADICTORY)
        if classification is CancellationClassification.AMBIGUOUS:
            return self._without_mutation(target, preflight, CancellationState.AMBIGUOUS)
        if classification is CancellationClassification.UNKNOWN:
            return self._without_mutation(target, preflight, CancellationState.UNKNOWN)

        # The only mutating path is a target proved pending by preflight.
        try:
            self.client.delete_pending((target,))
        except ComfyUIRejectedError as exc:
            return CancellationResult(
                target,
                CancellationState.FAILED,
                CancellationAction.QUEUE_DELETE,
                _message(exc),
                preflight,
                CancellationIssueKind.REJECTED,
                CancellationPhase.BEFORE_MUTATION,
            )
        except Exception as exc:
            return CancellationResult(
                target,
                CancellationState.UNKNOWN,
                CancellationAction.QUEUE_DELETE,
                _message(exc),
                preflight,
                _issue_kind(exc),
                CancellationPhase.MUTATION_ATTEMPTED_UNCERTAIN,
            )

        try:
            postflight = self.preflight(target)
        except Exception as exc:  # defensive for injected clients
            return CancellationResult(
                target,
                CancellationState.REQUESTED,
                CancellationAction.QUEUE_DELETE,
                _message(exc),
                preflight,
                _issue_kind(exc),
                CancellationPhase.POST_VERIFICATION,
            )

        if postflight.classification is CancellationClassification.NOT_FOUND and postflight.issue is None:
            return CancellationResult(
                target,
                CancellationState.CONFIRMED,
                CancellationAction.QUEUE_DELETE,
                None,
                postflight,
                None,
                CancellationPhase.POST_VERIFICATION,
            )
        if postflight.classification is CancellationClassification.ALREADY_TERMINAL:
            return CancellationResult(
                target,
                CancellationState.RACED_TERMINAL,
                CancellationAction.QUEUE_DELETE,
                "target reached a terminal state during cancellation",
                postflight,
                None,
                CancellationPhase.POST_VERIFICATION,
            )
        if postflight.classification is CancellationClassification.TARGET_RUNNING:
            return CancellationResult(
                target,
                CancellationState.RUNNING_INTERRUPT_UNSAFE,
                CancellationAction.QUEUE_DELETE,
                "target raced from pending to running; no interrupt was issued",
                postflight,
                None,
                CancellationPhase.POST_VERIFICATION,
            )

        return CancellationResult(
            target,
            CancellationState.REQUESTED,
            CancellationAction.QUEUE_DELETE,
            postflight.issue or "post-verification did not confirm removal",
            postflight,
            postflight.issue_kind,
            CancellationPhase.POST_VERIFICATION,
        )


__all__ = [
    "CancellationClassification",
    "CancellationState",
    "CancellationAction",
    "CancellationIssueKind",
    "CancellationPhase",
    "CancellationIssue",
    "CancellationPreflight",
    "CancellationResult",
    "ComfyUICancellationAdapter",
]
