"""Single-chunk deadline polling with one, fail-closed retry."""
from dataclasses import replace
from enum import Enum
import time
from ..domain.core import Lifecycle, ErrorRecord, DomainError
from ..domain.core import resolve_orchestration_timeout_seconds
from ..adapters.http import HistoryResult, HistoryState
from .bridge import SubmitOutcome
from .chunk_execution import _clone_execution, _copy_execution_state

class RobustOutcome(str, Enum):
    COMPLETED='COMPLETED'; FAILED='FAILED'; NEEDS_MANUAL_REVIEW='NEEDS_MANUAL_REVIEW'; BLOCKED='BLOCKED'

class RobustChunkExecutionResult:
    def __init__(self, outcome, reason='', attempts=(), completion=None):
        self.outcome=RobustOutcome(outcome); self.reason=reason; self.attempt_ids=tuple(attempts); self.completion=completion
    @property
    def success(self): return self.outcome is RobustOutcome.COMPLETED

class RobustChunkExecutionCoordinator:
    def __init__(self, coordinator, *, clock=None, sleeper=None, poll_interval=1.0):
        if poll_interval <= 0:
            raise ValueError('poll_interval must be positive')
        self.coordinator=coordinator; self.clock=clock or time.monotonic; self.sleeper=sleeper or time.sleep; self.poll_interval=poll_interval

    def _observe(self, ref, execution, chunk, attempt, deadline):
        last=None; previous = self.clock(); polls = 0
        while previous <= deadline:
            try:
                value=self.coordinator.monitor(ref, execution=execution, chunk=chunk, attempt=attempt) if callable(self.coordinator.monitor) else self.coordinator.monitor
            except Exception as exc: return None, f'monitor failed: {exc}'
            if isinstance(value,(list,tuple)):
                if value: value=value[-1]
            if isinstance(value,HistoryResult) and value.prompt_id == ref:
                last=value
                if value.state in {HistoryState.SUCCEEDED,HistoryState.FAILED}: return value,None
            now = self.clock()
            if now >= deadline: break
            self.sleeper(self.poll_interval)
            after = self.clock()
            polls += 1
            if after <= now:
                return last, 'clock did not advance; manual review required'
            previous = after
        return last, 'deadline exceeded'

    def _persist_failed(self, project, execution, chunk, attempt, reason):
        clone=_clone_execution(execution); cc=next(c for c in clone.chunks if str(c.id)==str(chunk.id)); aa=next(a for a in cc.attempts if str(a.id)==str(attempt.id))
        if aa.state is Lifecycle.PENDING: aa.transition(Lifecycle.RUNNING)
        if aa.state is Lifecycle.RUNNING: aa.transition(Lifecycle.FAILED,error=ErrorRecord('backend_failed',reason))
        self.coordinator.repository.save(project,[clone]); _copy_execution_state(execution,clone)

    def attempt_once(self, project, execution, chunk_id, prompt, **submit_kwargs):
        chunk=next((c for c in execution.chunks if str(c.id)==str(chunk_id)),None)
        if chunk is None: return RobustChunkExecutionResult(RobustOutcome.BLOCKED,'chunk identity mismatch')
        timeout=resolve_orchestration_timeout_seconds(project,execution,chunk)
        ids=[]
        try:
            result, validation_error = self.coordinator.submit_new(project, execution, chunk_id, prompt, **submit_kwargs)
            if validation_error is not None: return RobustChunkExecutionResult(RobustOutcome.BLOCKED, validation_error, ids)
        except Exception as exc: return RobustChunkExecutionResult(RobustOutcome.BLOCKED,f'submit failed: {exc}',ids)
        ids.append(result.attempt_id)
        if result.outcome is not SubmitOutcome.SUCCEEDED or result.job_ref is None: return RobustChunkExecutionResult(RobustOutcome.BLOCKED,result.outcome.value,ids)
        attempt=next((a for a in chunk.attempts if str(a.id)==str(result.attempt_id)),None)
        if attempt is None or attempt.external_job_ref != result.job_ref: return RobustChunkExecutionResult(RobustOutcome.BLOCKED,'attempt/reference mismatch',ids)
        observed, problem=self._observe(result.job_ref,execution,chunk,attempt,self.clock()+timeout)
        if problem: return RobustChunkExecutionResult(RobustOutcome.NEEDS_MANUAL_REVIEW,problem,ids)
        if observed.state is HistoryState.SUCCEEDED:
            completion=self.coordinator.complete_submitted_attempt(project,execution,chunk,attempt,observed)
            return RobustChunkExecutionResult(RobustOutcome.COMPLETED if completion.success else RobustOutcome.NEEDS_MANUAL_REVIEW,completion.reason,ids,completion)
        if observed.state is not HistoryState.FAILED: return RobustChunkExecutionResult(RobustOutcome.NEEDS_MANUAL_REVIEW,'nonterminal/ambiguous state',ids)
        try: self._persist_failed(project,execution,chunk,attempt,observed.error or 'backend failed')
        except Exception as exc: return RobustChunkExecutionResult(RobustOutcome.BLOCKED,f'failed attempt persistence: {exc}',ids)
        return RobustChunkExecutionResult(RobustOutcome.FAILED,observed.error or 'backend failed',ids)

    def execute(self, project, execution, chunk_id, prompt, **submit_kwargs):
        """Compatibility alias: exactly one mechanically executed attempt."""
        return self.attempt_once(project, execution, chunk_id, prompt, **submit_kwargs)

RobustChunkExecutionUseCase = RobustChunkExecutionCoordinator
