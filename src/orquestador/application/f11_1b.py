"""F11.1B orchestration boundary.

This module is intentionally the sole composition point for preparation,
materialization, submission and recovery.  UI callers exchange identifiers;
repositories are created per worker/thread by the caller.
"""
from pathlib import Path
import hashlib
from ..domain.core import MaterializedInputRef
from typing import Any, Sequence
from enum import Enum
from dataclasses import dataclass
from .submit_boundary import SubmitBoundary, validate_configured_output_root
from .robust_chunk_execution import RobustOutcome, RobustChunkExecutionResult

@dataclass(frozen=True)
class MaterializedInputs:
    initial: Path
    references: tuple[Path, ...]
    transition: Path | None = None

@dataclass(frozen=True)
class RobustExecutionPlan:
    max_attempts: int = 2
    timeout_seconds: float | None = None

class ChainRoutingAction(str, Enum):
    FRESH_EXECUTE='fresh_execute'; RECOVER_RESUME='recover_resume'; BLOCK='block'; COMPLETE='complete'

@dataclass(frozen=True)
class ChainRoutingDecision:
    action: ChainRoutingAction
    reason: str = ''

@dataclass(frozen=True)
class UiCapabilities:
    can_start: bool=False; can_resume: bool=False; can_recover: bool=False
    can_retry: bool=False; can_cancel: bool=False; can_assemble: bool=False

def select_active_cancellation_target(execution):
    """Return exactly one current actionable pending external reference."""
    candidates=[]
    for chunk in getattr(execution, 'chunks', ()):
        if getattr(chunk, 'state', None) not in (None,):
            if getattr(chunk.state, 'value', chunk.state) not in ('pending','running','failed'): continue
        attempts=getattr(chunk,'attempts',()) or ()
        active=[a for a in attempts if getattr(a,'state',None) and getattr(a.state,'value',a.state) in ('pending','running') and getattr(a,'external_job_ref',None)]
        candidates.extend(a.external_job_ref for a in active)
    unique={r.value:r for r in candidates}
    return next(iter(unique.values())) if len(unique)==1 else None

def derive_capabilities(execution, *, can_cancel_candidate=False, retryable=False, startable=True, assemble=False):
    state=getattr(getattr(execution,'state',None),'value',getattr(execution,'state','unknown'))
    state=str(state).lower()
    return UiCapabilities(
        can_start=state=='pending' and bool(startable),
        can_resume=state in ('running','failed'), can_recover=state in ('running','failed'),
        can_retry=state=='failed' and bool(retryable),
        can_cancel=state in ('pending','running','failed') and bool(can_cancel_candidate),
        can_assemble=state=='succeeded' and bool(assemble))

class InputMaterializationService:
    """Single authority for static inputs and exact N-1 transition frames."""
    def __init__(self, client=None, root=None):
        self.client = client
        self.root = Path(root).resolve() if root is not None else None

    def _one(self, path, *, subfolder, label, extension=None):
        path = Path(path).resolve()
        if self.root is not None and not path.is_relative_to(self.root):
            raise ValueError("input escapes configured root")
        if not path.is_file():
            raise ValueError("all inputs must be files")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        name = f"{label}-{digest[:16]}{extension or path.suffix.lower() or '.png'}"
        if self.client is None:
            return MaterializedInputRef("input", subfolder, name, digest)
        value = self.client.upload_image(path, subfolder=subfolder, overwrite=False, requested_filename=name)
        if not isinstance(value, dict) or value.get("type") != "input" or value.get("name") != name:
            raise ValueError("upload descriptor mismatch")
        returned = value.get("sha256") or value.get("source_sha256")
        if returned is not None and str(returned).lower() != digest:
            raise ValueError("upload provenance mismatch")
        return MaterializedInputRef("input", str(value.get("subfolder", subfolder)), name, digest)

    def materialize(self, initial: Path, references: Sequence[Path], *, transition: Path | None = None) -> MaterializedInputs:
        initial = Path(initial)
        refs = tuple(Path(p) for p in references)
        if self.client is None:
            if not initial.is_file() or any(not p.is_file() for p in refs): raise ValueError("all inputs must be files")
            return MaterializedInputs(initial, refs, Path(transition) if transition else None)
        i = self._one(initial, subfolder="orquestador/static", label="initial")
        r = tuple(self._one(p, subfolder="orquestador/static", label=f"ref-{n}") for n,p in enumerate(refs, 1))
        t = self._one(transition, subfolder="orquestador/transitions", label="transition") if transition else None
        return MaterializedInputs(i, r, t)

    def materialize_transition(self, path: Path) -> MaterializedInputRef:
        """Materialize one transition frame through the same upload authority."""
        return self._one(path, subfolder="orquestador/transitions", label="transition", extension=".png")

    def __call__(self, paths):
        values = list(paths)
        # StartGuiChainUseCase passes durable paths relative to the configured
        # project root.  Resolve them here (inside the worker-local service)
        # rather than against the process cwd, which is both incorrect for
        # external project roots and can make a valid input look like it
        # escapes the configured root.
        def resolve(value):
            p = Path(value)
            if not p.is_absolute() and self.root is not None:
                p = self.root / p
            return p
        result = self.materialize(resolve(values[0]), [resolve(v) for v in values[1:]])
        def ref(v):
            return f"{v.subfolder}/{v.name}" if hasattr(v, "name") else str(v)
        return [ref(result.initial), *(ref(v) for v in result.references)]

class F11_1BOrchestrator:
    def __init__(self, *, materializer: InputMaterializationService, submit_boundary: SubmitBoundary, recovery=None, start=None, resume=None, retry=None, robust=None):
        self.materializer, self.submit_boundary = materializer, submit_boundary
        self.recovery, self.start_usecase, self.resume_usecase, self.retry_usecase, self.robust = recovery, start, resume, retry, robust

    def execute_chunk_with_policy(self, project, execution, chunk_id, prompt, *, submit_kwargs=None):
        """Bounded fresh execution policy: at most two robust single attempts."""
        if self.robust is None:
            raise RuntimeError("robust coordinator unavailable")
        kwargs = dict(submit_kwargs or {})
        first = self.robust.attempt_once(project, execution, chunk_id, prompt, **kwargs)
        if getattr(first, "outcome", None) is not RobustOutcome.FAILED:
            return first
        chunk = next((c for c in execution.chunks if str(c.id) == str(chunk_id)), None)
        if chunk is None or chunk.state.value == "cancelled" or len(chunk.attempts) >= 2:
            return first
        # Attempt 1 is durably terminal FAILED at this point.  The submit
        # boundary owns creation/binding of Attempt 2; reopening is only a
        # post-submit primitive and therefore cannot be used as preparation.
        second = self.robust.attempt_once(project, execution, chunk_id, prompt, **kwargs)
        return RobustChunkExecutionResult(second.outcome, second.reason,
                                          first.attempt_ids + second.attempt_ids,
                                          second.completion)
    def prepare(self, initial, references=(), **kwargs):
        return self.materializer.materialize(initial, references, **kwargs)
    def submit(self, project, execution, chunk_id, prompt, **kwargs):
        return self.submit_boundary.submit(project, execution, chunk_id, prompt, **kwargs)
    def recover(self, project_id, execution_id=None):
        if self.recovery is None: raise RuntimeError("recovery service unavailable")
        return self.recovery.recover(project_id, execution_id)
    def start(self, project_id, execution_id, **kwargs):
        if self.start_usecase is None: raise RuntimeError("start service unavailable")
        return self.start_usecase(project_id, execution_id, **kwargs)
    def resume(self, project_id, execution_id=None, **kwargs):
        if self.resume_usecase is None: raise RuntimeError("resume service unavailable")
        return self.resume_usecase.resume(project_id, execution_id, **kwargs)
    def retry(self, project_id, execution_id=None, **kwargs):
        if self.retry_usecase is None: raise RuntimeError("retry service unavailable")
        return self.retry_usecase.retry(project_id, execution_id, **kwargs)

    def authorize_retry(self, execution, chunk, *, observed=None):
        """Single lifecycle policy gate for bounded retry authorization."""
        if chunk is None or len(chunk.attempts) >= 2:
            return False
        if observed is not None and getattr(observed, "state", None) is not None:
            return str(getattr(observed.state, "value", observed.state)).lower() == "failed"
        return True

    def authorize_chunk_execution(self, execution, chunk, *, observed=None):
        return len(chunk.attempts) < 2 and (observed is None or getattr(observed, 'state', None) is None or str(getattr(observed.state, 'value', observed.state)).lower() == 'failed')

    def route_chain_chunk(self, chunk):
        if chunk.state.value == 'succeeded': return ChainRoutingDecision(ChainRoutingAction.COMPLETE)
        if chunk.state.value == 'cancelled': return ChainRoutingDecision(ChainRoutingAction.BLOCK, 'cancelled')
        if chunk.state.value in {'failed','running'}: return ChainRoutingDecision(ChainRoutingAction.RECOVER_RESUME)
        return ChainRoutingDecision(ChainRoutingAction.FRESH_EXECUTE)

    def apply_retry_policy(self, execution, result, jobs=()):
        """Apply the bounded F6 retry policy to an observational reconciliation."""
        from ..domain.recovery import Decision, Action, ReconciliationResult, BackendJobState
        if result.decision is not Decision.RETRY_CURRENT_CHUNK or Action.CREATE_NEW_ATTEMPT not in result.proposed_actions:
            return result
        target = next((c for c in execution.chunks if any(str(a.id) == result.attempt_id for a in c.attempts)), None)
        attempts = () if target is None else target.attempts
        cancelled = any(getattr(a, 'state', None).value == 'cancelled' for a in attempts)
        cancelled = cancelled or any(j.attempt_id == result.attempt_id and j.state is BackendJobState.CANCELLED for j in jobs)
        if cancelled or len(attempts) >= 2:
            return ReconciliationResult(result.execution_id, Decision.NEEDS_MANUAL_REVIEW,
                result.last_safe_completed_chunk, result.next_actionable_chunk, result.attempt_id,
                result.evidence_codes, (Action.BLOCK_FOR_REVIEW,), False)
        return result

    def classify_recovery(self, plan):
        """Normalize primitive observations without delegating policy elsewhere."""
        return plan

    @staticmethod
    def authorize_reconciliation(execution, result, jobs=()):
        """Compatibility adapter for old callers; new flows call orchestrator policy."""
        return result

    def derive_ui_capabilities(self, execution, *, can_cancel_candidate=False,
                               retryable=False, startable=True, assemble=False):
        """Compatibility delegate to the single canonical capability authority."""
        return derive_capabilities(
            execution,
            can_cancel_candidate=can_cancel_candidate,
            retryable=retryable,
            startable=startable,
            assemble=assemble,
        ).__dict__.copy()
