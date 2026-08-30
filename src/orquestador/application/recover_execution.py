"""Durable, plan-only recovery application boundary."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Protocol

from ..domain.core import BackendJobRef
from ..domain.recovery import (BackendJobObservation,
    BackendJobState, Decision, Action, ReconciliationResult, reconcile)
from .bridge import BackendEvidence, map_backend_evidence

class RecoveryRepository(Protocol):
    def load(self, project_id: Any): ...

class FreshRecoveryBackend(Protocol):
    def observe(self, external_job_ref: BackendJobRef) -> Any: ...

@dataclass(frozen=True)
class RecoveryPlan:
    result: ReconciliationResult
    cause: str | None = None

def _apply_f6_retry_policy(execution, result: ReconciliationResult, jobs=()) -> ReconciliationResult:
    """Application policy: authorize at most one retry; never retry cancellation."""
    if result.decision is not Decision.RETRY_CURRENT_CHUNK or Action.CREATE_NEW_ATTEMPT not in result.proposed_actions:
        return result
    target = next((c for c in execution.chunks if any(str(a.id) == result.attempt_id for a in c.attempts)), None)
    if target is None:
        return result
    attempt = next((a for a in target.attempts if str(a.id) == result.attempt_id), None)
    cancelled = attempt is not None and attempt.state.value == "cancelled"
    cancelled = cancelled or any(j.attempt_id == result.attempt_id and j.state is BackendJobState.CANCELLED for j in jobs)
    if cancelled or len(target.attempts) >= 2:
        return ReconciliationResult(result.execution_id, Decision.NEEDS_MANUAL_REVIEW,
            result.last_safe_completed_chunk, result.next_actionable_chunk, result.attempt_id,
            result.evidence_codes, (Action.BLOCK_FOR_REVIEW,), False)
    return result

class RecoverExecutionUseCase:
    """Load durable state, obtain fresh backend evidence, and reconcile only."""
    def __init__(self, repository: RecoveryRepository, backend: FreshRecoveryBackend):
        self.repository, self.backend = repository, backend

    def recover(self, project_id: Any, execution_id: Any | None = None) -> RecoveryPlan:
        loaded_execution_id = None
        try:
            _, executions = self.repository.load(project_id)
            execution = next((e for e in executions if execution_id is None or str(e.id) == str(execution_id)), None)
            if execution is None:
                raise ValueError("execution not found")
            loaded_execution_id = str(execution.id)
            chunk = next((c for c in execution.chunks if c.attempts and c.state.value not in ("succeeded",)), None)
            if chunk is None:
                return RecoveryPlan(_apply_f6_retry_policy(execution, reconcile(execution)))
            attempt = chunk.attempts[-1]
            if attempt.external_job_ref is None:
                return RecoveryPlan(_apply_f6_retry_policy(execution, reconcile(execution)), "durable attempt has no external_job_ref")
            source = self.backend.observe(attempt.external_job_ref)  # always fresh, never cached input
            if isinstance(source, BackendEvidence):
                observation = BackendJobObservation(source.project_id, source.execution_id, source.chunk_id, source.attempt_id, source.state, source.job_ref)
            elif isinstance(source, BackendJobObservation):
                observation = source
            else:
                evidence = map_backend_evidence(execution=execution, project_id=str(execution.project_id), execution_id=str(execution.id), chunk_id=str(chunk.id), attempt_id=str(attempt.id), job_ref=attempt.external_job_ref, source=source)
                observation = BackendJobObservation(evidence.project_id, evidence.execution_id, evidence.chunk_id, evidence.attempt_id, evidence.state, evidence.job_ref)
            return RecoveryPlan(_apply_f6_retry_policy(execution, reconcile(execution, jobs=(observation,)), (observation,)))
        except Exception as exc:
            durable_id = loaded_execution_id or (str(execution_id) if execution_id is not None else "unknown")
            return RecoveryPlan(ReconciliationResult(durable_id, Decision.NEEDS_MANUAL_REVIEW, None, None, None, (), (), False), str(exc))
