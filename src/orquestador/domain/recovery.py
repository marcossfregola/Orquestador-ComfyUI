"""Pure, backend-agnostic recovery and reconciliation rules."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple

from .core import Execution, Lifecycle, OutputRef, TransitionFrame, BackendJobRef


class BackendJobState(str, Enum):
    UNKNOWN = "unknown"; QUEUED = "queued"; RUNNING = "running"
    COMPLETED = "completed"; FAILED = "failed"; CANCELLED = "cancelled"

class Decision(str, Enum):
    SAFE_TO_CONTINUE_FROM_NEXT_CHUNK = "safe_to_continue_from_next_chunk"
    RETRY_CURRENT_CHUNK = "retry_current_chunk"
    WAIT_FOR_EXTERNAL_JOB = "wait_for_external_job"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"
    BLOCKED_CORRUPT_STATE = "blocked_corrupt_state"
    COMPLETE = "complete"
    RECONCILE_EXTERNAL_COMPLETION = "reconcile_external_completion"

class Action(str, Enum):
    MARK_EXTERNAL_COMPLETION_FROM_VERIFIED_EVIDENCE = "mark_external_completion_from_verified_evidence"
    CREATE_NEW_ATTEMPT = "create_new_attempt"
    REGENERATE_TRANSITION_FRAME = "regenerate_transition_frame"
    WAIT = "wait"
    BLOCK_FOR_REVIEW = "block_for_review"

class EvidenceCode(str, Enum):
    VERIFIED_OUTPUT = "verified_output"; VERIFIED_TRANSITION = "verified_transition"
    MISSING_OUTPUT = "missing_output"; CORRUPT_OUTPUT = "corrupt_output"
    MISSING_TRANSITION = "missing_transition"; CORRUPT_TRANSITION = "corrupt_transition"
    BACKEND_ACTIVE = "backend_active"; BACKEND_UNKNOWN = "backend_unknown"
    BACKEND_TERMINAL_FAILURE = "backend_terminal_failure"; PROVENANCE_MISMATCH = "provenance_mismatch"
    GAP = "unresolved_gap"; EXTERNAL_COMPLETION_UNVERIFIED = "external_completion_unverified"

@dataclass(frozen=True)
class ArtifactObservation:
    project_id: str; execution_id: str; chunk_id: str; attempt_id: str
    output: Optional[OutputRef] = None; exists: bool = False; integrity_valid: bool = False
    kind: str = "output"

@dataclass(frozen=True)
class BackendJobObservation:
    project_id: str; execution_id: str; chunk_id: str; attempt_id: str
    state: BackendJobState
    external_job_ref: Optional[BackendJobRef] = None

@dataclass(frozen=True)
class TransitionObservation:
    project_id: str; execution_id: str; source_chunk_id: str; source_attempt_id: str
    target_chunk_id: Optional[str] = None; exists: bool = False; integrity_valid: bool = False
    source_output: Optional[OutputRef] = None

@dataclass(frozen=True)
class ReconciliationResult:
    execution_id: str; decision: Decision; last_safe_completed_chunk: Optional[int]
    next_actionable_chunk: Optional[int]; attempt_id: Optional[str]
    evidence_codes: Tuple[EvidenceCode, ...] = (); proposed_actions: Tuple[Action, ...] = ()
    durable_mutation_proposed: bool = False

def reconcile(execution: Execution, artifacts: Tuple[ArtifactObservation, ...] = (),
              jobs: Tuple[BackendJobObservation, ...] = (),
              transitions: Tuple[TransitionObservation, ...] = ()) -> ReconciliationResult:
    """Deterministically derive a safe continuation plan; never mutates ``execution``."""
    aid = str(execution.id); amap = {(a.chunk_id, a.attempt_id): a for a in artifacts}
    jmap = {(j.chunk_id, j.attempt_id): j for j in jobs}; tmap = {(t.source_chunk_id, t.target_chunk_id): t for t in transitions}
    last = None
    for i, chunk in enumerate(execution.chunks):
        successful = [a for a in chunk.attempts if a.state is Lifecycle.SUCCEEDED and a.output and a.evidence]
        if chunk.state is Lifecycle.SUCCEEDED and successful:
            a = successful[-1]; ob = amap.get((str(chunk.id), str(a.id)))
            if not ob or ob.project_id != str(execution.project_id) or ob.execution_id != aid or ob.output != a.output or not ob.exists or not ob.integrity_valid:
                return ReconciliationResult(aid, Decision.BLOCKED_CORRUPT_STATE, last, i, str(a.id), (EvidenceCode.MISSING_OUTPUT if not ob or not ob.exists else EvidenceCode.CORRUPT_OUTPUT,), (Action.BLOCK_FOR_REVIEW,), False)
            if i < len(execution.chunks)-1:
                tr = tmap.get((str(chunk.id), str(execution.chunks[i+1].id)))
                if not tr or tr.source_attempt_id != str(a.id) or tr.source_output != a.output or not tr.exists or not tr.integrity_valid:
                    return ReconciliationResult(aid, Decision.NEEDS_MANUAL_REVIEW, last, i, str(a.id), (EvidenceCode.MISSING_TRANSITION if not tr or not tr.exists else EvidenceCode.CORRUPT_TRANSITION,), (Action.REGENERATE_TRANSITION_FRAME,), True)
            last = i; continue
        attempt = chunk.attempts[-1] if chunk.attempts else None
        if attempt is None:
            return ReconciliationResult(aid, Decision.RETRY_CURRENT_CHUNK, last, i, None, (EvidenceCode.GAP,), (Action.CREATE_NEW_ATTEMPT,), True)
        key=(str(chunk.id),str(attempt.id)); job=jmap.get(key)
        if attempt.state is Lifecycle.RUNNING:
            if job and (job.project_id != str(execution.project_id) or job.execution_id != aid or job.external_job_ref != attempt.external_job_ref):
                return ReconciliationResult(aid, Decision.NEEDS_MANUAL_REVIEW,last,i,str(attempt.id),(EvidenceCode.PROVENANCE_MISMATCH,),(Action.BLOCK_FOR_REVIEW,),False)
            if job and job.state in (BackendJobState.RUNNING, BackendJobState.QUEUED): return ReconciliationResult(aid, Decision.WAIT_FOR_EXTERNAL_JOB,last,i,str(attempt.id),(EvidenceCode.BACKEND_ACTIVE,),(Action.WAIT,),False)
            if job and job.state in (BackendJobState.FAILED, BackendJobState.CANCELLED): return ReconciliationResult(aid, Decision.RETRY_CURRENT_CHUNK,last,i,str(attempt.id),(EvidenceCode.BACKEND_TERMINAL_FAILURE,),(Action.CREATE_NEW_ATTEMPT,),True)
            if job and job.state is BackendJobState.COMPLETED:
                ob = amap.get(key)
                if ob and ob.project_id == str(execution.project_id) and ob.execution_id == aid and ob.attempt_id == str(attempt.id) and ob.exists and ob.integrity_valid and ob.output:
                    return ReconciliationResult(aid, Decision.RECONCILE_EXTERNAL_COMPLETION,last,i,str(attempt.id),(EvidenceCode.VERIFIED_OUTPUT,),(Action.MARK_EXTERNAL_COMPLETION_FROM_VERIFIED_EVIDENCE,),True)
                return ReconciliationResult(aid, Decision.NEEDS_MANUAL_REVIEW,last,i,str(attempt.id),(EvidenceCode.EXTERNAL_COMPLETION_UNVERIFIED,),(Action.BLOCK_FOR_REVIEW,),False)
            return ReconciliationResult(aid, Decision.NEEDS_MANUAL_REVIEW,last,i,str(attempt.id),(EvidenceCode.BACKEND_UNKNOWN,),(Action.BLOCK_FOR_REVIEW,),False)
        if attempt.state in (Lifecycle.FAILED, Lifecycle.CANCELLED): return ReconciliationResult(aid, Decision.RETRY_CURRENT_CHUNK,last,i,str(attempt.id),(EvidenceCode.BACKEND_TERMINAL_FAILURE,),(Action.CREATE_NEW_ATTEMPT,),True)
        return ReconciliationResult(aid, Decision.BLOCKED_CORRUPT_STATE,last,i,str(attempt.id),(EvidenceCode.GAP,),(Action.BLOCK_FOR_REVIEW,),False)
    return ReconciliationResult(aid, Decision.COMPLETE, last, None, None, (EvidenceCode.VERIFIED_OUTPUT,), (), False)
