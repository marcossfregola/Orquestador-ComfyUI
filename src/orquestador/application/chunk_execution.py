"""Durable, single-chunk completion coordinator."""
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
from ..domain.core import (Artifact, Attempt, BackendJobRef, Chunk, Evidence,
    Execution, Lifecycle, OutputRef, TransitionFrame, Phase)
from ..domain.recovery import BackendJobState
from ..adapters.http import HistoryResult
from ..adapters.outputs import correlate_outputs
from ..adapters.physical_outputs import validate_physical_output
from .bridge import SubmitOutcome, map_backend_evidence, map_verified_artifact_observation

@dataclass(frozen=True)
class ChunkExecutionResult:
    success: bool
    reason: str
    attempt_id: str
    artifact: Artifact|None = None
    transition: TransitionFrame|None = None

class ChunkExecutionCoordinator:
    def __init__(self, repository, submitter, monitor, *, extractor, trusted_root, correlator=correlate_outputs, physical_validator=validate_physical_output):
        self.repository,self.submitter,self.monitor=repository,submitter,monitor
        self.extractor,self.trusted_root,self.correlator,self.physical_validator=extractor,Path(trusted_root),correlator,physical_validator
    def execute(self, project, execution, chunk_id, prompt, **submit_kwargs):
        chunk=next((c for c in execution.chunks if str(c.id)==str(chunk_id)),None)
        if chunk is None: return ChunkExecutionResult(False,'chunk identity mismatch','')
        result=self.submitter.submit(project,execution,chunk_id,prompt,**submit_kwargs)
        if result.outcome is not SubmitOutcome.SUCCEEDED or not isinstance(result.job_ref, BackendJobRef): return ChunkExecutionResult(False,result.outcome.value,result.attempt_id)
        attempt=next((a for a in chunk.attempts if str(a.id)==result.attempt_id), None)
        if attempt is None or attempt.external_job_ref != result.job_ref: return ChunkExecutionResult(False,'attempt/reference mismatch',result.attempt_id)
        ref=result.job_ref
        try:
            observed=self.monitor(ref, execution=execution, chunk=chunk, attempt=attempt) if callable(self.monitor) else self.monitor
            if isinstance(observed,(list,tuple)):
                if not observed: return ChunkExecutionResult(False,'missing monitor evidence',result.attempt_id)
                observed=observed[-1]
        except Exception as exc:
            return ChunkExecutionResult(False,f'monitor failed: {exc}',result.attempt_id)
        if not isinstance(observed, HistoryResult) or observed.prompt_id != ref: return ChunkExecutionResult(False,'monitor reference mismatch',result.attempt_id)
        return self.complete_submitted_attempt(project, execution, chunk, attempt, observed)

    def complete_submitted_attempt(self, project, execution, chunk, attempt, observed):
        ref = attempt.external_job_ref
        if not isinstance(observed, HistoryResult) or observed.prompt_id != ref: return ChunkExecutionResult(False,'monitor reference mismatch',str(attempt.id))
        evidence=map_backend_evidence(execution=execution,project_id=project.id,execution_id=execution.id,chunk_id=chunk.id,attempt_id=attempt.id,job_ref=ref,source=observed)
        if evidence.state is not BackendJobState.COMPLETED: return ChunkExecutionResult(False,'monitor not terminal success',str(attempt.id))
        corr=self.correlator(observed,ref)
        if getattr(corr,'status',None).value!='valid' or len(corr.descriptors)!=1: return ChunkExecutionResult(False,'output absent or ambiguous',str(attempt.id))
        evidence = replace(evidence, logical_outputs=tuple(corr.descriptors))
        physical=self.physical_validator(corr.descriptors[0],self.trusted_root)
        obs=map_verified_artifact_observation(evidence=evidence,physical=physical,project_id=project.id,execution_id=execution.id,chunk_id=chunk.id,attempt_id=attempt.id,job_ref=ref)
        if obs is None: return ChunkExecutionResult(False,'physical/provenance validation failed',str(attempt.id))
        # Persistence stores project-relative artifact references; physical validation
        # intentionally retains the absolute trusted-root path for extraction.
        try:
            relative_output = physical.resolved_path.resolve().relative_to(self.trusted_root.resolve()).as_posix()
        except (ValueError, OSError, RuntimeError):
            return ChunkExecutionResult(False, 'physical output escapes trusted root', str(attempt.id))
        obs = replace(obs, output=OutputRef(relative_output))
        try:
            frame_path=self.trusted_root/'transitions'/f'{attempt.id}.png'; frame=self.extractor.extract_last_frame(physical.resolved_path,frame_path)
            if frame.frame_index != frame.frame_count-1: raise ValueError('frame is not N-1')
        except Exception as exc: return ChunkExecutionResult(False,f'extractor failed: {exc}',str(attempt.id))
        clone = _clone_execution(execution)
        cc=next(c for c in clone.chunks if str(c.id)==str(chunk.id)); aa=next(a for a in cc.attempts if str(a.id)==str(attempt.id)); cc.transition(Lifecycle.RUNNING); aa.transition(Lifecycle.RUNNING); aa.transition(Lifecycle.SUCCEEDED,output=obs.output,evidence=Evidence('correlated output, physical validation, decodable N-1 frame'))
        artifact=Artifact(project.id,clone.id,cc.id,aa.id,Phase.OUTPUT,obs.output)
        transition=TransitionFrame(project.id,clone.id,cc.id,aa.id,obs.output,frame.frame_index,frame.frame_count)
        cc.transition(Lifecycle.SUCCEEDED)
        if clone.chunks and all(x.state is Lifecycle.SUCCEEDED for x in clone.chunks):
            # Promote execution only when its durable lifecycle is already RUNNING;
            # legacy F5 callers may persist a PENDING execution alongside completed chunk data.
            if clone.state is Lifecycle.RUNNING: clone.transition(Lifecycle.SUCCEEDED)
        try: self.repository.save(project,[clone],artifacts=[artifact],transitions=[transition])
        except Exception as exc: return ChunkExecutionResult(False,f'persistence failed: {exc}',str(attempt.id))
        _copy_execution_state(execution, clone)
        return ChunkExecutionResult(True,'completed',str(attempt.id),artifact,transition)


def _clone_execution(execution: Execution) -> Execution:
    """Clone the mutable aggregate without copying mappingproxy defaults."""
    clone = Execution(execution.project_id, execution.id, dict(execution.defaults),
                      execution.state, [], execution.workflow_profile_ref,
                      list(execution.artifacts), list(execution.errors))
    for source in execution.chunks:
        chunk = Chunk(source.id, source.order, source.execution_id,
                      dict(source.defaults), source.state, [], source.first_frame)
        for attempt in source.attempts:
            chunk.attempts.append(Attempt(attempt.id, attempt.number, attempt.state,
                                          attempt.output, attempt.evidence, attempt.error,
                                          attempt.external_job_ref))
        clone.add_chunk(chunk)
    return clone


def _copy_execution_state(target: Execution, source: Execution) -> None:
    """Apply a successfully persisted clone back to the caller's aggregate."""
    target.state = source.state
    target.artifacts = list(source.artifacts)
    target.errors = list(source.errors)
    for target_chunk, source_chunk in zip(target.chunks, source.chunks):
        target_chunk.state = source_chunk.state
        target_chunk.first_frame = source_chunk.first_frame
        for target_attempt, source_attempt in zip(target_chunk.attempts, source_chunk.attempts):
            target_attempt.state = source_attempt.state
            target_attempt.output = source_attempt.output
            target_attempt.evidence = source_attempt.evidence
            target_attempt.error = source_attempt.error
            target_attempt.external_job_ref = source_attempt.external_job_ref
