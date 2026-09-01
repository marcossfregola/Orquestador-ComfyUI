"""Durable recovery planning and an explicit, single-chunk execution boundary."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from ..domain.core import BackendJobRef, Lifecycle, DomainError
from ..domain.recovery import (BackendJobObservation,
    BackendJobState, Decision, Action, ReconciliationResult, reconcile)
from ..domain.recovery import EvidenceCode
from .bridge import BackendEvidence, map_backend_evidence
from .bridge import SubmitOutcome
from .chunk_execution import _clone_execution, _copy_execution_state
from ..adapters.http import HistoryResult
from ..domain.core import ErrorRecord, Artifact, Phase

class RecoveryOutcome(str, Enum):
    COMPLETE='complete'; WAIT='wait'; RETRIED_WAIT='retried_wait'; RETRIED_COMPLETE='retried_complete'
    NEEDS_MANUAL_REVIEW='needs_manual_review'; BLOCKED='blocked'

@dataclass(frozen=True)
class RecoveryExecutionResult:
    outcome: RecoveryOutcome; execution_id: str; chunk_id: str|None = None; attempt_id: str|None = None
    reason: str = ''; plan: RecoveryPlan|None = None; completion: Any = None

class RecoveryRepository(Protocol):
    def load(self, project_id: Any): ...
    def load_transitions(self, execution_id: Any): ...

class FreshRecoveryBackend(Protocol):
    def observe(self, external_job_ref: BackendJobRef) -> Any: ...

@dataclass(frozen=True)
class RecoveryPlan:
    result: ReconciliationResult
    cause: str | None = None
    observed: Any = None

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
        _, executions = self.repository.load(project_id)
        matches = [e for e in executions if execution_id is None or str(e.id) == str(execution_id)]
        if not matches:
            raise ValueError("execution not found")
        if execution_id is None and len(matches) != 1:
            return RecoveryPlan(ReconciliationResult("ambiguous", Decision.NEEDS_MANUAL_REVIEW, None, None, None, (), (Action.BLOCK_FOR_REVIEW,), False), "execution selection is ambiguous")
        execution = matches[0]
        chunk = next((c for c in execution.chunks if c.attempts and c.state is not Lifecycle.SUCCEEDED), None)
        if chunk is None:
            return RecoveryPlan(reconcile(execution))
        attempt = chunk.attempts[-1]
        if attempt.external_job_ref is None:
            # No trustworthy binding means resubmission is unsafe, regardless of lifecycle.
            return RecoveryPlan(ReconciliationResult(str(execution.id), Decision.NEEDS_MANUAL_REVIEW,
                None, chunk.order, str(attempt.id), (), (Action.BLOCK_FOR_REVIEW,), False),
                "durable attempt has no external_job_ref")
        try:
            source = self.backend.observe(attempt.external_job_ref)  # mandatory fresh observation
        except (TimeoutError, ConnectionError, OSError) as exc:
            return RecoveryPlan(ReconciliationResult(str(execution.id), Decision.NEEDS_MANUAL_REVIEW, None, chunk.order, str(attempt.id), (EvidenceCode.BACKEND_UNKNOWN,), (Action.BLOCK_FOR_REVIEW,), False), str(exc))
        if isinstance(source, BackendJobObservation):
            observation = source
        else:
            evidence = map_backend_evidence(execution=execution, project_id=str(execution.project_id), execution_id=str(execution.id), chunk_id=str(chunk.id), attempt_id=str(attempt.id), job_ref=attempt.external_job_ref, source=source)
            observation = BackendJobObservation(evidence.project_id, evidence.execution_id, evidence.chunk_id, evidence.attempt_id, evidence.state, evidence.job_ref)
        result = _apply_f6_retry_policy(execution, reconcile(execution, jobs=(observation,)), (observation,))
        return RecoveryPlan(result, observed=source)

class ResumeExecutionUseCase:
    """Executable, single-chunk F6 boundary composed from F5 services."""
    def __init__(self, repository, backend, coordinator, submitter):
        self.repository, self.backend, self.coordinator, self.submitter = repository, backend, coordinator, submitter

    def _manual(self, e, c=None, a=None, reason=''):
        return RecoveryExecutionResult(RecoveryOutcome.NEEDS_MANUAL_REVIEW, str(e.id), str(c.id) if c else None, str(a.id) if a else None, reason)

    def resume(self, project_id, execution_id=None, *, prompt=None, project=None):
        project, executions = self.repository.load(project_id) if project is None else (project, self.repository.load(project_id)[1])
        matches=[e for e in executions if execution_id is None or str(e.id)==str(execution_id)]
        if len(matches)!=1: return RecoveryExecutionResult(RecoveryOutcome.BLOCKED, str(execution_id or 'ambiguous'), reason='execution selection is ambiguous or missing')
        e=matches[0]
        if self._durably_complete(e):
            return RecoveryExecutionResult(RecoveryOutcome.COMPLETE,str(e.id),reason='durably complete')
        c=next((x for x in e.chunks if x.state is not Lifecycle.SUCCEEDED),None)
        if c is None: return self._manual(e,reason='no actionable chunk')
        a=c.attempts[-1] if c.attempts else None
        if a is None or a.external_job_ref is None: return self._manual(e,c,a,'actionable attempt has no trustworthy external_job_ref')
        ref=a.external_job_ref
        try: source=self.backend.observe(ref)
        except (TimeoutError,ConnectionError,OSError) as exc: return self._manual(e,c,a,str(exc))
        if isinstance(source, BackendJobObservation):
            if (source.project_id,source.execution_id,source.chunk_id,source.attempt_id) != (str(project_id),str(e.id),str(c.id),str(a.id)) or source.external_job_ref != ref:
                return self._manual(e,c,a,'backend observation provenance mismatch')
            state=source.state
        else:
            ev=map_backend_evidence(execution=e,project_id=str(project_id),execution_id=str(e.id),chunk_id=str(c.id),attempt_id=str(a.id),job_ref=ref,source=source); state=ev.state
        # Crash-safe retry re-entry: a bound attempt 2 may survive while the
        # chunk is still FAILED. Reopen through the narrow domain contract.
        if c.state is Lifecycle.FAILED and a.number == 2:
            try:
                c.reopen_for_retry()
                self.repository.save(project, [e])
            except DomainError as exc:
                return self._manual(e,c,a,str(exc))
        if state in (BackendJobState.QUEUED,BackendJobState.RUNNING): return RecoveryExecutionResult(RecoveryOutcome.WAIT,str(e.id),str(c.id),str(a.id))
        if state in (BackendJobState.UNKNOWN,BackendJobState.CANCELLED): return self._manual(e,c,a,f'backend state {state.value}')
        if state is BackendJobState.COMPLETED:
            history = source if isinstance(source,HistoryResult) else (self.backend.history(ref) if hasattr(self.backend,'history') else None)
            if not isinstance(history,HistoryResult) or history.prompt_id!=ref: return self._manual(e,c,a,'missing or mismatched HistoryResult')
            completion=self.coordinator.complete_submitted_attempt(project,e,c,a,history)
            if not getattr(completion,'success',False): return self._manual(e,c,a,getattr(completion,'reason','completion failed'))
            return RecoveryExecutionResult(RecoveryOutcome.RETRIED_COMPLETE if a.number>1 else RecoveryOutcome.COMPLETE,str(e.id),str(c.id),str(a.id),completion=completion)
        # FAILED: persist terminal attempt before delegating exactly one retry.
        if len(c.attempts)>=2 or a.state is Lifecycle.CANCELLED: return self._manual(e,c,a,'retry budget exhausted or cancelled')
        if a.state is not Lifecycle.FAILED:
            clone=_clone_execution(e); cc=next(x for x in clone.chunks if str(x.id)==str(c.id)); aa=next(x for x in cc.attempts if str(x.id)==str(a.id));
            if aa.state is Lifecycle.RUNNING: aa.transition(Lifecycle.FAILED,error=ErrorRecord('backend_failed','backend reported FAILED'))
            self.repository.save(project,[clone]); _copy_execution_state(e,clone); a=next(x for x in c.attempts if str(x.id)==str(a.id))
        result=self.submitter.submit(project,e,c.id,prompt)
        if result.outcome is not SubmitOutcome.SUCCEEDED or result.job_ref is None: return self._manual(e,c,a,result.outcome.value)
        # A retry reopens the failed chunk before completion orchestration; the
        # coordinator requires the aggregate to be RUNNING when it promotes the
        # newly submitted attempt.
        a2=next(x for x in c.attempts if str(x.id)==str(result.attempt_id))
        if c.state is Lifecycle.FAILED:
            try:
                c.reopen_for_retry()
            except DomainError as exc:
                return self._manual(e,c,a2,str(exc))
            self.repository.save(project, [e])
        src2=self.backend.observe(result.job_ref)
        if isinstance(src2,BackendJobObservation):
            if (src2.project_id,src2.execution_id,src2.chunk_id,src2.attempt_id,src2.external_job_ref) != (str(project_id),str(e.id),str(c.id),str(a2.id),result.job_ref):
                return self._manual(e,c,a2,'retry backend observation provenance mismatch')
            st2=src2.state
        else: st2=map_backend_evidence(execution=e,project_id=str(project_id),execution_id=str(e.id),chunk_id=str(c.id),attempt_id=str(a2.id),job_ref=result.job_ref,source=src2).state
        if st2 in (BackendJobState.QUEUED,BackendJobState.RUNNING): return RecoveryExecutionResult(RecoveryOutcome.RETRIED_WAIT,str(e.id),str(c.id),str(a2.id))
        if st2 is BackendJobState.COMPLETED:
            h=src2 if isinstance(src2,HistoryResult) else (self.backend.history(result.job_ref) if hasattr(self.backend,'history') else None)
            if not isinstance(h,HistoryResult) or h.prompt_id!=result.job_ref: return self._manual(e,c,a2,'missing or mismatched HistoryResult')
            completion=self.coordinator.complete_submitted_attempt(project,e,c,a2,h)
            return RecoveryExecutionResult(RecoveryOutcome.RETRIED_COMPLETE if completion.success else RecoveryOutcome.NEEDS_MANUAL_REVIEW,str(e.id),str(c.id),str(a2.id),completion=completion)
        return self._manual(e,c,a2,'retry attempt did not complete successfully')

    def _durably_complete(self, e):
        if e.state is not Lifecycle.SUCCEEDED or not e.chunks or any(c.state is not Lifecycle.SUCCEEDED for c in e.chunks): return False
        arts={(str(x.chunk_id),str(x.attempt_id),x.phase,x.output.uri) for x in getattr(e,'artifacts',())}
        try:
            transitions = tuple(self.repository.load_transitions(e.id))
        except (AttributeError, NotImplementedError):
            return False
        for i,c in enumerate(e.chunks):
            a=next((x for x in reversed(c.attempts) if x.state is Lifecycle.SUCCEEDED and x.output and x.evidence),None)
            if a is None or (str(c.id),str(a.id),Phase.OUTPUT,a.output.uri) not in arts: return False
            frames=[t for t in transitions if str(t.source_chunk_id)==str(c.id) and str(t.source_attempt_id)==str(a.id)]
            if len(frames)!=1: return False
            t=frames[0]
            if (str(t.project_id),str(t.execution_id),t.source_output) != (str(e.project_id),str(e.id),a.output): return False
            if (isinstance(t.frame_count, bool) or not isinstance(t.frame_count, int) or t.frame_count <= 0): return False
            if (isinstance(t.source_frame_index, bool) or not isinstance(t.source_frame_index, int) or t.source_frame_index < 0 or t.source_frame_index != t.frame_count - 1): return False
            expected_target = None if i == len(e.chunks)-1 else str(e.chunks[i+1].id)
            if (str(t.target_chunk_id) if t.target_chunk_id is not None else None) != expected_target: return False
        return True

class RetryExecutionUseCase:
    """Explicit retry seam enforcing the durable one-retry boundary.

    The normal resume route reconciles active executions.  This route is only
    entered for a durably failed execution/chunk with exactly Attempt 1
    failed; it then delegates orchestration to the existing resume primitive.
    """
    def __init__(self, repository, resume):
        self.repository, self.resume_usecase = repository, resume

    def retry(self, project_id, execution_id=None, **kwargs):
        project, executions = self.repository.load(project_id)
        matches = [e for e in executions if execution_id is None or str(e.id) == str(execution_id)]
        if len(matches) != 1:
            raise ValueError("execution selection is ambiguous or missing")
        execution = matches[0]
        chunk = next((c for c in execution.chunks if c.state is Lifecycle.FAILED), None)
        if execution.state is not Lifecycle.FAILED or chunk is None or len(chunk.attempts) != 1:
            raise ValueError("retry requires a durably failed execution with exactly one failed attempt")
        attempt = chunk.attempts[-1]
        if attempt.state is not Lifecycle.FAILED:
            raise ValueError("retry requires a failed Attempt 1")
        # ResumeExecutionUseCase performs the existing F6 backend observation,
        # durable Attempt 2 creation, budget enforcement, and completion flow.
        return self.resume_usecase.resume(project_id, execution_id, **kwargs)
