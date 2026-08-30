
"""Typed, fail-closed application boundary for ComfyUI evidence."""
from __future__ import annotations
from copy import copy
from dataclasses import dataclass
from enum import Enum
from typing import Any
from ..domain.core import BackendJobRef, Execution, Project, OutputRef
from ..domain.recovery import Action, ArtifactObservation, BackendJobObservation, BackendJobState, ReconciliationResult, reconcile
from ..adapters.http import HistoryResult, HistoryState, QueueSnapshot, QueueState
from ..adapters.events import ObservationEvent, ObservationKind
from ..adapters.outputs import OutputCorrelationResult, OutputCorrelationStatus, OutputDescriptor
from ..adapters.cancellation import CancellationResult
from ..adapters.physical_outputs import PhysicalOutputEvidence, PhysicalOutputStatus

@dataclass(frozen=True)
class BackendEvidence:
    project_id:str; execution_id:str; chunk_id:str; attempt_id:str; job_ref:BackendJobRef; state:BackendJobState
    logical_outputs:tuple[OutputDescriptor,...]=(); issue_kind:str|None=None; detail:str|None=None
@dataclass(frozen=True)
class CancellationEvidence:
    target:BackendJobRef; state:Enum; action:Enum; issue:str|None=None; issue_kind:Enum|None=None; phase:Enum|None=None

class SubmitOutcome(str, Enum):
    SUCCEEDED = 'succeeded'
    INVALID_REF = 'invalid_ref'
    AMBIGUOUS = 'ambiguous'
    BIND_FAILED = 'bind_failed'

@dataclass(frozen=True)
class SubmitAttemptResult:
    outcome: SubmitOutcome
    attempt_id: str
    job_ref: BackendJobRef | None = None
    error: str | None = None

class SubmitAttemptUseCase:
    """Durably create an attempt, submit exactly once, then bind and persist."""
    def __init__(self, repository, client, bridge=None):
        self.repository = repository
        self.client = client
        self.bridge = bridge or ComfyUIJobBridge(repository)

    def submit(self, project, execution, chunk_id, prompt, *, client_id=None):
        chunk = next((c for c in execution.chunks if str(c.id) == str(chunk_id)), None)
        if chunk is None:
            raise ValueError('chunk identity mismatch')
        attempt = chunk.new_attempt()
        # Intentionally propagate pre-submit persistence failures: no external request boundary has been crossed.
        self.repository.save(project, [execution])
        try:
            ref = self.client.submit(prompt, client_id=client_id)
        except Exception as exc:
            return SubmitAttemptResult(SubmitOutcome.AMBIGUOUS, str(attempt.id), error=str(exc))
        if not isinstance(ref, BackendJobRef) or not ref.value.strip():
            return SubmitAttemptResult(SubmitOutcome.INVALID_REF, str(attempt.id), error='invalid backend job reference')
        try:
            self.bridge.bind(project, execution, chunk_id, str(attempt.id), ref, execution_id=execution.id)
        except Exception as exc:
            return SubmitAttemptResult(SubmitOutcome.BIND_FAILED, str(attempt.id), ref, str(exc))
        return SubmitAttemptResult(SubmitOutcome.SUCCEEDED, str(attempt.id), ref)

def _authority(execution, project_id, execution_id, chunk_id, attempt_id, ref):
    if str(execution.project_id)!=str(project_id) or str(execution.id)!=str(execution_id): raise ValueError('provenance mismatch')
    for c in execution.chunks:
        if str(c.id)==str(chunk_id):
            for a in c.attempts:
                if str(a.id)==str(attempt_id):
                    if a.external_job_ref is None: raise ValueError('attempt has no bound backend reference')
                    if a.external_job_ref!=ref: raise ValueError('backend job reference mismatch')
                    return c,a
            raise ValueError('attempt identity mismatch')
    raise ValueError('chunk identity mismatch')

def map_backend_evidence(*, execution:Execution, project_id:str, execution_id:str, chunk_id:str, attempt_id:str, job_ref:BackendJobRef, source:Any)->BackendEvidence:
    if not isinstance(job_ref,BackendJobRef): raise ValueError('invalid backend job reference')
    _authority(execution,project_id,execution_id,chunk_id,attempt_id,job_ref)
    state=BackendJobState.UNKNOWN; detail=None; issue=None; outputs=()
    if isinstance(source,QueueSnapshot):
        listed = job_ref in source.running, job_ref in source.pending
        if source.state is not QueueState.UNKNOWN:
            expected = QueueState.RUNNING if source.running and not source.pending else QueueState.PENDING if source.pending and not source.running else QueueState.EMPTY if not source.running and not source.pending else QueueState.UNKNOWN
            if source.state is not expected: detail='contradictory queue state'; return BackendEvidence(str(project_id),str(execution_id),str(chunk_id),str(attempt_id),job_ref,BackendJobState.UNKNOWN,(),None,detail)
        if listed==(True,True): detail='ambiguous queue evidence'
        elif job_ref in source.running: state=BackendJobState.RUNNING
        elif job_ref in source.pending: state=BackendJobState.QUEUED
        else: detail='job absent from queue'
    elif isinstance(source,HistoryResult):
        if source.prompt_id!=job_ref: raise ValueError('prompt_id/backend job reference mismatch')
        state={HistoryState.QUEUED:BackendJobState.QUEUED,HistoryState.RUNNING:BackendJobState.RUNNING,HistoryState.SUCCEEDED:BackendJobState.COMPLETED,HistoryState.FAILED:BackendJobState.FAILED,HistoryState.NOT_FOUND:BackendJobState.UNKNOWN,HistoryState.UNKNOWN:BackendJobState.UNKNOWN}[source.state]; detail=source.error
    elif isinstance(source,ObservationEvent):
        if source.job_ref!=job_ref: raise ValueError('observation/backend job reference mismatch')
        state={ObservationKind.QUEUED:BackendJobState.QUEUED,ObservationKind.RUNNING:BackendJobState.RUNNING,ObservationKind.PROGRESS:BackendJobState.UNKNOWN,ObservationKind.COMPLETED:BackendJobState.COMPLETED,ObservationKind.FAILED:BackendJobState.FAILED,ObservationKind.CANCELLED:BackendJobState.CANCELLED,ObservationKind.UNKNOWN:BackendJobState.UNKNOWN}[source.kind]; detail=source.error or ('progress is nondurable/non-lifecycle' if source.kind is ObservationKind.PROGRESS else None); issue=source.issue_kind.value if source.issue_kind else None
    elif isinstance(source,OutputCorrelationResult):
        if source.prompt_id!=job_ref: raise ValueError('output correlation reference mismatch')
        if source.status is OutputCorrelationStatus.VALID: outputs=tuple(source.descriptors)
        detail=source.reason or source.status.value
    else: raise TypeError('unsupported backend evidence source')
    return BackendEvidence(str(project_id),str(execution_id),str(chunk_id),str(attempt_id),job_ref,state,outputs,issue,detail)

def map_cancellation_evidence(*, execution:Execution, project_id:str, execution_id:str, chunk_id:str, attempt_id:str, result:CancellationResult)->CancellationEvidence:
    if not isinstance(result,CancellationResult): raise TypeError('result must be CancellationResult')
    _authority(execution,project_id,execution_id,chunk_id,attempt_id,result.target)
    return CancellationEvidence(result.target,result.state,result.action,result.issue,result.issue_kind,result.phase)

def map_verified_artifact_observation(*, evidence: BackendEvidence,
                                      physical: PhysicalOutputEvidence,
                                      project_id: str, execution_id: str,
                                      chunk_id: str, attempt_id: str,
                                      job_ref: BackendJobRef) -> ArtifactObservation | None:
    """Project coherent logical+physical evidence into the coarse F2 observation.

    This is deliberately pure: it neither persists nor mutates the supplied DTOs.
    """
    if not isinstance(evidence, BackendEvidence) or not isinstance(physical, PhysicalOutputEvidence):
        return None
    if not isinstance(job_ref, BackendJobRef) or evidence.job_ref != job_ref:
        return None
    if (evidence.project_id, evidence.execution_id, evidence.chunk_id, evidence.attempt_id) != (str(project_id), str(execution_id), str(chunk_id), str(attempt_id)):
        return None
    if evidence.state is not BackendJobState.COMPLETED:
        return None
    if len(evidence.logical_outputs) != 1 or physical.status is not PhysicalOutputStatus.EXISTS:
        return None
    descriptor = evidence.logical_outputs[0]
    if descriptor.prompt_id != job_ref or physical.descriptor != descriptor or physical.resolved_path is None:
        return None
    return ArtifactObservation(str(project_id), str(execution_id), str(chunk_id), str(attempt_id),
                               OutputRef(str(physical.resolved_path)), True, True, "output")

class ComfyUIJobBridge:
    def __init__(self,repository): self.repository=repository
    def bind(self,project,execution,chunk_id,attempt_id,job_ref,*,execution_id=None):
        if project.id != execution.project_id: raise ValueError('project/execution provenance mismatch')
        if execution_id is not None and str(execution.id)!=str(execution_id): raise ValueError('execution identity mismatch')
        for c in execution.chunks:
            if str(c.id)==str(chunk_id):
                for a in c.attempts:
                    if str(a.id)==str(attempt_id):
                        clone=copy(execution); clone.chunks=[copy(cc) for cc in execution.chunks];
                        for cc,orig in zip(clone.chunks,execution.chunks): cc.attempts=[copy(x) for x in orig.attempts]
                        ca=next(x for cc in clone.chunks if str(cc.id)==str(chunk_id) for x in cc.attempts if str(x.id)==str(attempt_id)); ca.assign_external_job_ref(job_ref)
                        self.repository.save(project,[clone]); a.assign_external_job_ref(job_ref)
                        return job_ref
        raise ValueError('attempt identity mismatch')
    def reconcile(self,execution,*,backend,artifacts=(),transitions=()):
        _authority(execution,backend.project_id,backend.execution_id,backend.chunk_id,backend.attempt_id,backend.job_ref)
        return reconcile(execution,artifacts=tuple(artifacts),jobs=(BackendJobObservation(backend.project_id,backend.execution_id,backend.chunk_id,backend.attempt_id,backend.state,backend.job_ref),),transitions=tuple(transitions))
    def apply(self,project,execution,result):
        if not isinstance(result,ReconciliationResult) or any(not isinstance(a,Action) for a in result.proposed_actions): raise ValueError('unknown action')
        actions=tuple(result.proposed_actions)
        if not actions or all(a in {Action.WAIT,Action.BLOCK_FOR_REVIEW} for a in actions): return result
        if any(a in {Action.REGENERATE_TRANSITION_FRAME,Action.MARK_EXTERNAL_COMPLETION_FROM_VERIFIED_EVIDENCE} for a in actions): raise ValueError('action requires out-of-scope physical evidence')
        if actions!=(Action.CREATE_NEW_ATTEMPT,) or result.attempt_id is None: raise ValueError('unsupported action')
        target=next((c for c in execution.chunks if any(str(a.id)==result.attempt_id for a in c.attempts)),None)
        if target is None: raise ValueError('attempt identity mismatch')
        clone=copy(execution); clone.chunks=[copy(cc) for cc in execution.chunks];
        for cc,orig in zip(clone.chunks,execution.chunks): cc.attempts=[copy(x) for x in orig.attempts]
        cclone=next(c for c in clone.chunks if str(c.id)==str(target.id)); cclone.new_attempt()
        self.repository.save(project,[clone]); target.new_attempt()
        return result

__all__=['BackendEvidence','CancellationEvidence','SubmitOutcome','SubmitAttemptResult','SubmitAttemptUseCase','map_backend_evidence','map_cancellation_evidence','map_verified_artifact_observation','ComfyUIJobBridge']
