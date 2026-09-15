"""Durable, fail-closed reconciliation for the single active product queue item.

F13.8 owns the atomic queue claim.  This module owns only the restart-time
decision for its survivor: it validates that exact claim, reuses the existing
chain/recovery boundary, and never authorizes a replacement submit for an
ambiguous durable attempt.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from ..domain.core import Lifecycle, Phase, editable_virgin
from .chunk_execution import _clone_execution, _copy_execution_state


class QueueRecoveryOutcome(str, Enum):
    TERMINAL = "terminal"
    WAIT = "wait"
    MANUAL_REVIEW = "manual_review"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class QueueRecoveryResult:
    outcome: QueueRecoveryOutcome
    execution_id: str
    queue_item_id: str
    reason: str = ""


class ActiveQueueRecoveryUseCase:
    """Reconcile one already-active QueueItem before another may be claimed.

    A submit made through the product boundary always leaves a durable Attempt
    before transport is called.  Therefore an active, running execution with
    no attempts is safe to continue through the existing engine, while any
    unbound attempt is an unknown transport outcome and stays blocked for
    human review.  Bound attempts are always observed through the supplied
    ``resume_claimed`` path with its no-resubmit recovery mode.
    """

    def __init__(
        self,
        repository,
        start_claimed: Callable[..., Any],
        resume_claimed: Callable[..., Any],
        *,
        completion_validator: Callable[[Any], bool],
    ):
        if repository is None:
            raise ValueError("queue recovery repository is required")
        if not callable(start_claimed) or not callable(resume_claimed):
            raise ValueError("queue recovery execution boundaries must be callable")
        if not callable(completion_validator):
            raise ValueError("queue recovery completion validator must be callable")
        self.repository = repository
        self.start_claimed = start_claimed
        self.resume_claimed = resume_claimed
        self.completion_validator = completion_validator

    @staticmethod
    def _result(outcome, execution_id, queue_item_id, reason=""):
        return QueueRecoveryResult(
            QueueRecoveryOutcome(outcome), str(execution_id), str(queue_item_id), reason
        )

    def _load_exact(self, project_id, execution_id, queue_item_id):
        validator = getattr(self.repository, "validate_active_queue_claim", None)
        if not callable(validator):
            raise RuntimeError("active queue claim validation is unavailable")
        validator(queue_item_id, execution_id)
        project, executions = self.repository.load(project_id)
        matches = [entry for entry in executions if str(entry.id) == str(execution_id)]
        if len(matches) != 1:
            raise RuntimeError("active queue execution selection is missing or ambiguous")
        if str(project.id) != str(project_id):
            raise RuntimeError("active queue project identity changed")
        return project, matches[0]

    def _outputs_are_present(self, execution):
        """Require imported durable output files, not metadata alone."""
        root = getattr(self.repository, "root", None)
        if root is None:
            return False
        try:
            root = Path(root).resolve()
            artifacts = tuple(getattr(execution, "artifacts", ()) or ())
            for artifact in artifacts:
                if getattr(artifact, "phase", None) is not Phase.OUTPUT:
                    continue
                output = getattr(artifact, "output", None)
                uri = getattr(output, "uri", None)
                if not isinstance(uri, str) or not uri.strip():
                    return False
                path = (root / uri).resolve()
                if not path.is_relative_to(root) or not path.is_file():
                    return False
        except (OSError, TypeError, ValueError):
            return False
        return True

    def _success_is_reconciled(self, execution):
        try:
            return bool(self.completion_validator(execution)) and self._outputs_are_present(execution)
        except Exception:
            return False

    def _promote_durable_success(self, project, execution):
        """Persist a lost final execution transition only from complete evidence."""
        if execution.state is not Lifecycle.RUNNING:
            return False
        try:
            candidate = _clone_execution(execution)
            candidate.transition(Lifecycle.SUCCEEDED)
        except Exception:
            return False
        if not self._success_is_reconciled(candidate):
            return False
        try:
            self.repository.save(project, [candidate])
        except Exception:
            return False
        _copy_execution_state(execution, candidate)
        return True

    @staticmethod
    def _actionable_attempt(execution):
        chunk = next((entry for entry in execution.chunks if entry.state is not Lifecycle.SUCCEEDED), None)
        if chunk is None:
            return None, None
        return chunk, (chunk.attempts[-1] if chunk.attempts else None)

    @staticmethod
    def _staged_stale_retry(execution, chunk, attempt):
        """Recognize only the retry row created by stale-job retirement.

        A generic unbound live attempt is still ambiguous and must remain a
        manual-review stop.  This exact two-attempt shape is different: its
        predecessor carries the durable stale-observation error and the first
        attempt retains the backend reference that recovery can observe again.
        """
        if execution.state is not Lifecycle.FAILED or chunk.state is not Lifecycle.FAILED:
            return False
        if len(chunk.attempts) != 2 or attempt is not chunk.attempts[-1]:
            return False
        first, staged = chunk.attempts
        return (
            first.number == 1
            and first.state is Lifecycle.FAILED
            and first.external_job_ref is not None
            and getattr(first.error, "code", None) == "stale_external_job_not_found"
            and staged.number == 2
            and staged.state is Lifecycle.PENDING
            and staged.external_job_ref is None
        )

    @staticmethod
    def _outcome_value(result):
        outcome = getattr(result, "outcome", None)
        value = getattr(outcome, "value", outcome)
        nested = getattr(result, "recovery_result", None)
        nested_outcome = getattr(nested, "outcome", None)
        nested_value = getattr(nested_outcome, "value", nested_outcome)
        if value in {"blocked", "complete"} and nested_value is not None:
            return nested_value
        return value

    def _fresh_terminal_result(self, execution, queue_item_id):
        if execution.state not in {Lifecycle.FAILED, Lifecycle.CANCELLED}:
            return None
        if any(
            attempt.state in {Lifecycle.PENDING, Lifecycle.RUNNING}
            for chunk in execution.chunks
            for attempt in chunk.attempts
        ):
            return None
        return self._result(QueueRecoveryOutcome.TERMINAL, execution.id, queue_item_id)

    def _after_drive(self, project_id, execution_id, queue_item_id, result, action):
        try:
            project, refreshed = self._load_exact(project_id, execution_id, queue_item_id)
        except Exception as exc:
            return self._result(
                QueueRecoveryOutcome.BLOCKED, execution_id, queue_item_id,
                f"active queue reload failed after {action}: {exc}",
            )
        outcome = self._outcome_value(result)
        terminal = self._terminal_result(project, refreshed, queue_item_id)
        if terminal is not None:
            if terminal.outcome is QueueRecoveryOutcome.MANUAL_REVIEW:
                detail = getattr(result, "reason", "")
                if detail:
                    return self._result(
                        QueueRecoveryOutcome.MANUAL_REVIEW, execution_id, queue_item_id, detail
                    )
            return terminal
        if outcome in {"failed", "cancelled"}:
            terminal = self._fresh_terminal_result(refreshed, queue_item_id)
            if terminal is not None:
                return terminal
        if outcome in {"wait", "retried_wait"}:
            return self._result(
                QueueRecoveryOutcome.WAIT, execution_id, queue_item_id,
                f"active execution remains observable after {action}",
            )
        detail = getattr(result, "reason", "") or "recovery did not reach a reconciled terminal state"
        return self._result(QueueRecoveryOutcome.MANUAL_REVIEW, execution_id, queue_item_id, detail)

    def _drive(self, callback, project_id, execution_id, queue_item_id, action):
        try:
            result = callback(str(project_id), str(execution_id), str(queue_item_id))
        except Exception as exc:
            return self._result(
                QueueRecoveryOutcome.BLOCKED, execution_id, queue_item_id,
                f"active queue {action} failed: {exc}",
            )
        return self._after_drive(project_id, execution_id, queue_item_id, result, action)

    def _terminal_result(self, project, execution, queue_item_id):
        if execution.state is Lifecycle.SUCCEEDED:
            if self._success_is_reconciled(execution):
                return self._result(QueueRecoveryOutcome.TERMINAL, execution.id, queue_item_id)
            return self._result(
                QueueRecoveryOutcome.MANUAL_REVIEW, execution.id, queue_item_id,
                "durable success lacks verified output, artifact, or transition evidence",
            )
        if execution.state not in {Lifecycle.FAILED, Lifecycle.CANCELLED}:
            return None
        chunk, attempt = self._actionable_attempt(execution)
        if chunk is None:
            return self._result(
                QueueRecoveryOutcome.MANUAL_REVIEW, execution.id, queue_item_id,
                "terminal execution has no non-success chunk",
            )
        if attempt is not None and attempt.external_job_ref is not None:
            # Even a locally terminal execution may carry a job accepted just
            # before a crash.  Observe it again before freeing the only active
            # queue slot.
            return None
        if attempt is not None and attempt.state in {Lifecycle.PENDING, Lifecycle.RUNNING}:
            if self._staged_stale_retry(execution, chunk, attempt):
                # Let the existing resume boundary re-observe Attempt 1's
                # exact reference and repair the staged retry.  It will bind
                # only after fresh active/completed evidence and never submit.
                return None
            return self._result(
                QueueRecoveryOutcome.MANUAL_REVIEW, execution.id, queue_item_id,
                "terminal execution retains an unbound live attempt",
            )
        return self._result(QueueRecoveryOutcome.TERMINAL, execution.id, queue_item_id)

    def reconcile(self, project_id, execution_id, queue_item_id):
        """Return a durable decision for exactly one active QueueItem."""
        try:
            project, execution = self._load_exact(project_id, execution_id, queue_item_id)
        except Exception as exc:
            return self._result(
                QueueRecoveryOutcome.BLOCKED, execution_id, queue_item_id,
                f"active queue load failed: {exc}",
            )

        terminal = self._terminal_result(project, execution, queue_item_id)
        if terminal is not None:
            return terminal

        if execution.state in {Lifecycle.FAILED, Lifecycle.CANCELLED}:
            # A bound attempt remains possibly live until the existing recovery
            # path has freshly observed it.
            return self._drive(
                self.resume_claimed, project.id, execution.id, queue_item_id, "terminal binding observation"
            )

        if execution.state is Lifecycle.PENDING:
            if not editable_virgin(execution):
                return self._result(
                    QueueRecoveryOutcome.MANUAL_REVIEW, execution.id, queue_item_id,
                    "active pending execution contains runtime evidence",
                )
            # Claim persisted but no runtime transition existed: no submission
            # could have started through the product boundary.
            return self._drive(
                self.start_claimed, project.id, execution.id, queue_item_id, "virgin claimed start"
            )

        if execution.state is not Lifecycle.RUNNING:
            return self._result(
                QueueRecoveryOutcome.MANUAL_REVIEW, execution.id, queue_item_id,
                f"unsupported active execution lifecycle {execution.state.value}",
            )

        if self._promote_durable_success(project, execution):
            return self._result(QueueRecoveryOutcome.TERMINAL, execution.id, queue_item_id)

        chunk, attempt = self._actionable_attempt(execution)
        if chunk is None:
            return self._result(
                QueueRecoveryOutcome.MANUAL_REVIEW, execution.id, queue_item_id,
                "running execution has no actionable chunk and lacks complete evidence",
            )
        if attempt is None:
            if chunk.state not in {Lifecycle.PENDING, Lifecycle.RUNNING}:
                return self._result(
                    QueueRecoveryOutcome.MANUAL_REVIEW, execution.id, queue_item_id,
                    "active execution has an unbound runtime gap",
                )
            # SubmitBoundary persists Attempt 1 before transport.  This is
            # therefore safe even after a prior chunk completed: the existing
            # chain validates every predecessor checkpoint before it submits
            # this still-unattempted chunk.
            return self._drive(
                self.resume_claimed, project.id, execution.id, queue_item_id, "unattempted running continuation"
            )
        if attempt.external_job_ref is None:
            return self._result(
                QueueRecoveryOutcome.MANUAL_REVIEW, execution.id, queue_item_id,
                "durable attempt has no external_job_ref; resubmission is unsafe",
            )
        return self._drive(
            self.resume_claimed, project.id, execution.id, queue_item_id, "bound attempt recovery"
        )


__all__ = ["ActiveQueueRecoveryUseCase", "QueueRecoveryOutcome", "QueueRecoveryResult"]
