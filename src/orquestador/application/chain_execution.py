"""Application boundary for durable multi-chunk chaining (F7).

This module deliberately composes the F5 single-chunk coordinator.  It owns
only ordering, transition linking and durable checkpoints; backend and video
details remain behind their existing ports.
"""
from dataclasses import dataclass, replace
from enum import Enum

from ..domain.core import Lifecycle, MaterializedInputRef, Phase
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
    def __init__(self, repository, coordinator, recovery=None, orchestrator=None):
        self.repository = repository
        self.coordinator = coordinator
        self.recovery = recovery
        self.orchestrator = orchestrator

    def run(self, project, execution, prompts, transition_rebinder=None, transition_materializer=None):
        if len(execution.chunks) < 2:
            return ChainExecutionResult(ChainOutcome.BLOCKED, str(execution.id), reason="at least two chunks are required")
        if execution.state is Lifecycle.CANCELLED:
            return ChainExecutionResult(ChainOutcome.BLOCKED, str(execution.id), reason='execution cancelled')
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
            if execution.state is Lifecycle.CANCELLED or chunk.state is Lifecycle.CANCELLED:
                return ChainExecutionResult(ChainOutcome.BLOCKED, str(execution.id), index, 'cancelled')
            if chunk.state is Lifecycle.SUCCEEDED:
                if index < len(execution.chunks)-1:
                    next_chunk = execution.chunks[index + 1]
                    # A source chunk may have only one durable continuity
                    # checkpoint.  Do not select a provisional row merely by
                    # source_chunk_id: retries can leave multiple attempts or
                    # outputs, and choosing one would bless the wrong lineage.
                    source_transitions = [
                        transition for transition in durable
                        if transition.source_chunk_id == chunk.id
                    ]
                    if len(source_transitions) != 1:
                        return ChainExecutionResult(
                            ChainOutcome.BLOCKED, str(execution.id), index,
                            'missing or ambiguous source continuity checkpoint',
                        )
                    checkpoint = source_transitions[0]
                    if (
                        str(checkpoint.project_id) != str(project.id)
                        or str(checkpoint.execution_id) != str(execution.id)
                    ):
                        return ChainExecutionResult(
                            ChainOutcome.BLOCKED, str(execution.id), index,
                            'source continuity checkpoint provenance mismatch',
                        )
                    source_attempts = [
                        attempt for attempt in chunk.attempts
                        if attempt.id == checkpoint.source_attempt_id
                        and attempt.state is Lifecycle.SUCCEEDED
                        and attempt.output is not None
                        and attempt.evidence is not None
                        and attempt.output == checkpoint.source_output
                    ]
                    if len(source_attempts) != 1:
                        return ChainExecutionResult(
                            ChainOutcome.BLOCKED, str(execution.id), index,
                            'source continuity checkpoint attempt/output mismatch',
                        )
                    source_attempt = source_attempts[0]
                    if checkpoint.target_chunk_id is None:
                        # A recovery completion may have persisted the F5
                        # provisional NULL-target transition before the chain
                        # process was interrupted.  Require the matching
                        # durable output artifact before promoting it.
                        artifacts = [
                            artifact for artifact in (getattr(execution, 'artifacts', None) or ())
                            if str(getattr(artifact, 'project_id', None)) == str(project.id)
                            and str(getattr(artifact, 'execution_id', None)) == str(execution.id)
                            and str(getattr(artifact, 'chunk_id', None)) == str(chunk.id)
                            and str(getattr(artifact, 'attempt_id', None)) == str(source_attempt.id)
                            and getattr(artifact, 'phase', None) is Phase.OUTPUT
                            and getattr(artifact, 'output', None) == checkpoint.source_output
                        ]
                        if len(artifacts) != 1:
                            return ChainExecutionResult(
                                ChainOutcome.BLOCKED, str(execution.id), index,
                                'source continuity checkpoint artifact is missing or ambiguous',
                            )
                        try:
                            linked = replace(checkpoint, target_chunk_id=next_chunk.id)
                        except Exception as exc:
                            return ChainExecutionResult(
                                ChainOutcome.BLOCKED, str(execution.id), index,
                                f'provisional continuity checkpoint is invalid: {exc}',
                            )
                        try:
                            execution.link_transition(next_chunk, linked)
                        except Exception as exc:
                            return ChainExecutionResult(
                                ChainOutcome.BLOCKED, str(execution.id), index,
                                f'provisional continuity checkpoint binding failed: {exc}',
                            )
                        try:
                            self.repository.save(project, [execution], transitions=(linked,))
                        except Exception as exc:
                            return ChainExecutionResult(
                                ChainOutcome.BLOCKED, str(execution.id), index,
                                f'provisional continuity checkpoint save failed: {exc}',
                            )
                        try:
                            durable = tuple(self.repository.load_transitions(execution.id))
                        except Exception as exc:
                            return ChainExecutionResult(
                                ChainOutcome.BLOCKED, str(execution.id), index,
                                f'provisional continuity checkpoint reload failed: {exc}',
                            )
                        verified = [
                            transition for transition in durable
                            if transition.target_chunk_id == next_chunk.id
                            and transition.source_chunk_id == chunk.id
                            and transition.source_attempt_id == source_attempt.id
                            and transition.source_output == source_attempt.output
                            and str(transition.project_id) == str(project.id)
                            and str(transition.execution_id) == str(execution.id)
                        ]
                        remaining_source = [
                            transition for transition in durable
                            if transition.source_chunk_id == chunk.id
                        ]
                        if len(verified) != 1 or len(remaining_source) != 1:
                            return ChainExecutionResult(
                                ChainOutcome.BLOCKED, str(execution.id), index,
                                'provisional continuity checkpoint verification failed',
                            )
                        checkpoint = verified[0]
                    elif checkpoint.target_chunk_id != next_chunk.id:
                        return ChainExecutionResult(
                            ChainOutcome.BLOCKED, str(execution.id), index,
                            'source continuity checkpoint target mismatch',
                        )
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
                except Exception as exc:
                    # Preserve the fail-closed boundary while exposing the
                    # safe actionable cause (missing frame/upload or invalid
                    # LoadImage descriptor) to the chain outcome.
                    detail = str(exc).strip() or exc.__class__.__name__
                    return ChainExecutionResult(
                        ChainOutcome.BLOCKED, str(execution.id), index,
                        f'invalid prompt binding: {detail}'
                    )
            route = self.orchestrator.route_chain_chunk(chunk) if self.orchestrator is not None else None
            use_recovery = route is not None and route.action.value == 'recover_resume'
            if chunk.state in (Lifecycle.FAILED, Lifecycle.RUNNING) and self.recovery is None:
                return ChainExecutionResult(ChainOutcome.BLOCKED,str(execution.id),index,'recovery required')
            runner = self.recovery if use_recovery or (route is None and chunk.state in (Lifecycle.FAILED, Lifecycle.RUNNING)) else self.coordinator
            if hasattr(runner, 'resume'):
                rr = runner.resume(project.id, execution.id, prompt=prompt, project=project)
                result = getattr(rr, 'completion', None)
                if result is None:
                    return ChainExecutionResult(ChainOutcome.BLOCKED, str(execution.id), index, getattr(rr, 'reason', 'recovery did not complete'))
            else:
                if self.orchestrator is not None and runner is self.coordinator:
                    result = self.orchestrator.execute_chunk_with_policy(
                        project, execution, chunk.id, prompt)
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
                # F5 creates a source transition with a nullable target. Read
                # that durable checkpoint back before advancing: the transient
                # completion object is allowed to lose the transition while
                # the artifact/frame have already been persisted.
                next_chunk = execution.chunks[index + 1]
                returned = getattr(result, 'transition', None)
                source_chunk_id = getattr(returned, 'source_chunk_id', None)
                source_attempt_id = getattr(returned, 'source_attempt_id', None)
                source_output = getattr(returned, 'source_output', None)
                artifact = getattr(result, 'artifact', None)
                if returned is None and artifact is not None:
                    source_chunk_id = artifact.chunk_id
                    source_attempt_id = artifact.attempt_id
                    source_output = artifact.output
                returned_target = getattr(returned, 'target_chunk_id', None)
                if returned is not None and returned_target not in (None, next_chunk.id):
                    return ChainExecutionResult(
                        ChainOutcome.BLOCKED, str(execution.id), index,
                        'completed chunk has an invalid continuity target', result,
                    )
                try:
                    after_completion = tuple(self.repository.load_transitions(execution.id))
                except Exception as exc:
                    return ChainExecutionResult(
                        ChainOutcome.BLOCKED, str(execution.id), index,
                        f'transition checkpoint load failed: {exc}', result,
                    )
                candidates = [
                    transition for transition in after_completion
                    if transition.source_chunk_id == source_chunk_id
                    and transition.source_attempt_id == source_attempt_id
                    and transition.source_output == source_output
                ]
                linked_candidates = [
                    transition for transition in candidates
                    if transition.target_chunk_id == next_chunk.id
                ]
                provisional = [
                    transition for transition in candidates
                    if transition.target_chunk_id is None
                ]
                unexpected = [
                    transition for transition in candidates
                    if transition.target_chunk_id not in (None, next_chunk.id)
                ]
                if (
                    len(linked_candidates) > 1
                    or len(provisional) > 1
                    or unexpected
                ):
                    return ChainExecutionResult(
                        ChainOutcome.BLOCKED, str(execution.id), index,
                        'ambiguous continuity checkpoint', result,
                    )
                linked = linked_candidates[0] if linked_candidates else None
                if linked is None:
                    checkpoint = provisional[0] if provisional else returned
                    if checkpoint is None:
                        return ChainExecutionResult(
                            ChainOutcome.BLOCKED, str(execution.id), index,
                            'completed chunk has no durable continuity checkpoint', result,
                        )
                    try:
                        linked = replace(checkpoint, target_chunk_id=next_chunk.id)
                    except Exception as exc:
                        return ChainExecutionResult(
                            ChainOutcome.BLOCKED, str(execution.id), index,
                            f'invalid continuity checkpoint: {exc}', result,
                        )
                try:
                    execution.link_transition(next_chunk, linked)
                    artifacts = (artifact,) if artifact is not None else ()
                    self.repository.save(
                        project, [execution], artifacts=artifacts,
                        transitions=(linked,),
                    )
                    durable = tuple(self.repository.load_transitions(execution.id))
                except Exception as exc:
                    return ChainExecutionResult(
                        ChainOutcome.BLOCKED, str(execution.id), index,
                        f'continuity checkpoint persistence failed: {exc}', result,
                    )
                verified = [
                    transition for transition in durable
                    if transition.target_chunk_id == next_chunk.id
                    and transition.source_chunk_id == chunk.id
                    and transition.source_attempt_id == source_attempt_id
                    and transition.source_output == source_output
                ]
                if len(verified) != 1:
                    return ChainExecutionResult(
                        ChainOutcome.BLOCKED, str(execution.id), index,
                        'continuity checkpoint is missing or inconsistent', result,
                    )
        if execution.state is not Lifecycle.SUCCEEDED:
            execution.transition(Lifecycle.SUCCEEDED)
            self.repository.save(project, [execution])
        return ChainExecutionResult(ChainOutcome.COMPLETE, str(execution.id))
