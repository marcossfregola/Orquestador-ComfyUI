"""Application boundary for durable multi-chunk chaining (F7).

This module deliberately composes the F5 single-chunk coordinator.  It owns
only ordering, transition linking and durable checkpoints; backend and video
details remain behind their existing ports.
"""
from dataclasses import dataclass, replace
from enum import Enum

from ..domain.core import Lifecycle, MaterializedInputRef
from .chunk_execution import ChunkExecutionResult
from .robust_chunk_execution import RobustChunkExecutionCoordinator


class ChainOutcome(str, Enum):
    COMPLETE = "complete"
    WAIT = "wait"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ChainExecutionResult:
    outcome: ChainOutcome
    execution_id: str
    next_chunk: int | None = None
    reason: str = ""
    chunk_result: ChunkExecutionResult | None = None


class ChainExecutionUseCase:
    """Execute or resume a bounded (two/three chunk) chain.

    ``prompts`` may be a sequence or callable(order, chunk).  A checkpoint is
    persisted after every successful chunk, before the next submit is made.
    """
    def __init__(self, repository, coordinator, recovery=None):
        self.repository = repository
        self.coordinator = coordinator
        self.recovery = recovery

    def run(self, project, execution, prompts, transition_rebinder=None, transition_materializer=None):
        if len(execution.chunks) < 2 or len(execution.chunks) > 3:
            return ChainExecutionResult(ChainOutcome.BLOCKED, str(execution.id), reason="F7 supports two or three chunks")
        if execution.state is Lifecycle.PENDING:
            execution.transition(Lifecycle.RUNNING)
            self.repository.save(project, [execution])
        # Durable reconciliation: a linked transition is the sole authority for
        # the next input; never silently trust an in-memory first_frame.
        try:
            durable = tuple(self.repository.load_transitions(execution.id))
        except Exception as exc:
            return ChainExecutionResult(ChainOutcome.BLOCKED, str(execution.id), reason=f'transition load failed: {exc}')
        for index, chunk in enumerate(execution.chunks):
            if chunk.state is Lifecycle.SUCCEEDED:
                if index < len(execution.chunks)-1:
                    links=[t for t in durable if t.target_chunk_id == execution.chunks[index+1].id]
                    if not links:
                        # A recovery completion may have persisted the F5
                        # provisional NULL-target transition before the chain
                        # process was interrupted.  Promote that one durable
                        # checkpoint to the immediate next chunk without
                        # resubmitting the already successful source job.
                        provisional=[t for t in durable
                                     if t.target_chunk_id is None
                                     and t.source_chunk_id == chunk.id]
                        if len(provisional) == 1:
                            linked=replace(provisional[0], target_chunk_id=execution.chunks[index+1].id)
                            execution.link_transition(execution.chunks[index+1], linked)
                            self.repository.save(project, [execution], transitions=(linked,))
                            durable=tuple(self.repository.load_transitions(execution.id))
                            links=[t for t in durable if t.target_chunk_id == execution.chunks[index+1].id]
                    if len(links)!=1 or links[0].source_chunk_id != chunk.id:
                        return ChainExecutionResult(ChainOutcome.BLOCKED,str(execution.id),index, 'missing or inconsistent continuity link')
                continue
            transition = None
            if index:
                links=[t for t in durable if t.target_chunk_id == chunk.id and t.source_chunk_id == execution.chunks[index-1].id]
                if len(links)!=1:
                    return ChainExecutionResult(ChainOutcome.BLOCKED,str(execution.id),index,'missing or inconsistent continuity link')
                transition=links[0]
                if chunk.first_frame is not None and chunk.first_frame != transition:
                    return ChainExecutionResult(ChainOutcome.BLOCKED,str(execution.id),index,'durable first_frame mismatch')
                try:
                    if not (self.repository.root / transition.source_output.uri).is_file():
                        return ChainExecutionResult(ChainOutcome.BLOCKED,str(execution.id),index,'missing source artifact')
                except (AttributeError, OSError):
                    return ChainExecutionResult(ChainOutcome.BLOCKED,str(execution.id),index,'invalid source artifact path')
            prompt = prompts(index, chunk) if callable(prompts) else prompts[index]
            if index:
                try:
                    materialized = transition.materialized_ref
                    if materialized is None:
                        if transition_materializer is None:
                            return ChainExecutionResult(ChainOutcome.BLOCKED,str(execution.id),index,'transition materializer required')
                        materialized = transition_materializer(transition)
                        if isinstance(materialized, MaterializedInputRef):
                            # Persist the effective ComfyUI input reference
                            # before submitting the next chunk.  A reopened
                            # chain can then reuse it without a duplicate upload.
                            transition = replace(transition, materialized_ref=materialized)
                            execution.link_transition(execution.chunks[index], transition)
                            self.repository.save(project, [execution], transitions=(transition,))
                            durable = tuple(self.repository.load_transitions(execution.id))
                    if hasattr(materialized,'load_image_value'): materialized = materialized.load_image_value
                    if not isinstance(materialized,str) or not materialized.strip(): raise ValueError('empty materialized reference')
                    prompt = (transition_rebinder(prompt, materialized)
                              if transition_rebinder is not None
                              else dict(prompt, first_frame=materialized))
                except Exception:
                    return ChainExecutionResult(ChainOutcome.BLOCKED,str(execution.id),index,'invalid prompt binding')
            if chunk.state in (Lifecycle.FAILED, Lifecycle.RUNNING) and self.recovery is None:
                return ChainExecutionResult(ChainOutcome.BLOCKED,str(execution.id),index,'recovery required')
            runner = self.recovery if chunk.state in (Lifecycle.FAILED, Lifecycle.RUNNING) else self.coordinator
            if hasattr(runner, 'resume'):
                rr = runner.resume(project.id, execution.id, prompt=prompt, project=project)
                result = getattr(rr, 'completion', None)
                if result is None:
                    return ChainExecutionResult(ChainOutcome.BLOCKED, str(execution.id), index, getattr(rr, 'reason', 'recovery did not complete'))
            else:
                result = runner.execute(project, execution, chunk.id, prompt)
            if hasattr(result,'completion') and result.completion is not None: result = result.completion
            if not result.success:
                return ChainExecutionResult(ChainOutcome.BLOCKED, str(execution.id), index, result.reason, result)
            if runner is self.recovery:
                _, refreshed = self.repository.load(project.id)
                exact = [item for item in refreshed if str(item.id) == str(execution.id)]
                if len(exact) != 1:
                    return ChainExecutionResult(ChainOutcome.BLOCKED, str(execution.id), index, 'execution refresh is ambiguous or missing')
                fresh = exact[0]
                execution.chunks = fresh.chunks
                execution.state = fresh.state
                execution.artifacts = list(fresh.artifacts)
                execution.errors = list(fresh.errors)
            if index < len(execution.chunks) - 1:
                # F5 creates a source transition with a nullable target. Link it
                # only after durable completion, then persist the next input.
                linked = replace(result.transition, target_chunk_id=execution.chunks[index + 1].id)
                execution.link_transition(execution.chunks[index + 1], linked)
                self.repository.save(project, [execution], artifacts=(result.artifact,), transitions=(linked,))
                durable = tuple(self.repository.load_transitions(execution.id))
        if execution.state is not Lifecycle.SUCCEEDED:
            execution.transition(Lifecycle.SUCCEEDED)
            self.repository.save(project, [execution])
        return ChainExecutionResult(ChainOutcome.COMPLETE, str(execution.id))
