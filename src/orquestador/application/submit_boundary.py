"""Neutral submit boundary shared by orchestration primitives.

This module deliberately has no dependency on the F11.1B orchestrator; it is
the transport-to-durable-attempt port used by the policy owner and primitives.
"""
from pathlib import Path

def validate_configured_output_root(root):
    if root is None:
        raise ValueError("configured ComfyUI output root is required")
    p = Path(root).expanduser().resolve()
    if not p.exists() or not p.is_dir():
        raise ValueError("configured output root must be an existing directory")
    return p

class SubmitBoundary:
    """Exactly one provisional-attempt -> transport -> durable-binding boundary."""
    def __init__(self, submitter, bridge=None, repository=None):
        self.submitter = submitter; self.bridge = bridge
        self.repository = repository or getattr(bridge, 'repository', None) or getattr(submitter, 'repository', None)

    def _bridge(self):
        from .bridge import ComfyUIJobBridge
        repository = self.repository
        if repository is None:
            raise ValueError('submit boundary repository is required for durable binding')
        return self.bridge or ComfyUIJobBridge(repository)

    def submit(self, project, execution, chunk_id, prompt, **kwargs):
        # All NEW-submit lifecycle policy lives here.  The injected object is
        # transport-only (its submit method returns a raw prompt id).
        from .bridge import (SubmitAttemptResult, SubmitOutcome, ComfyUIJobBridge)
        from ..domain.core import BackendJobRef, Lifecycle, ErrorRecord
        from ..adapters.http import ComfyUIRejectedError, ComfyUIProtocolError, ComfyUITransportError
        chunk = next((c for c in execution.chunks if str(c.id) == str(chunk_id)), None)
        if chunk is None: raise ValueError('chunk identity mismatch')
        attempt = chunk.new_attempt(); self.repository.save(project, [execution])
        try:
            raw = self.submitter.submit(prompt, **kwargs)
        except ComfyUIRejectedError as exc:
            detail = f"rejected status={exc.status} body={(getattr(exc,'body',None) or str(exc))[:4096]}"
            attempt.transition(Lifecycle.RUNNING); attempt.transition(Lifecycle.FAILED, error=ErrorRecord('submit_rejected', detail))
            self.repository.save(project, [execution])
            return SubmitAttemptResult(SubmitOutcome.REJECTED, str(attempt.id), error=detail)
        except ComfyUIProtocolError as exc:
            return SubmitAttemptResult(SubmitOutcome.PROTOCOL_FAILED, str(attempt.id), error=f'protocol_failure type={type(exc).__name__} message={str(exc)[:4096]}')
        except ComfyUITransportError as exc:
            return SubmitAttemptResult(SubmitOutcome.AMBIGUOUS, str(attempt.id), error=f'ambiguous_transport {str(exc)[:4096]}')
        ref = raw if isinstance(raw, BackendJobRef) else None
        if ref is None or not ref.value.strip(): return SubmitAttemptResult(SubmitOutcome.INVALID_REF, str(attempt.id), error='invalid backend job reference')
        try:
            self._bridge().bind(project, execution, chunk_id, str(attempt.id), ref, execution_id=execution.id)
        except Exception as exc: return SubmitAttemptResult(SubmitOutcome.BIND_FAILED, str(attempt.id), ref, str(exc))
        return SubmitAttemptResult(SubmitOutcome.SUCCEEDED, str(attempt.id), ref)

    def submit_existing_pending_attempt(self, project, execution, chunk_id, attempt_id, prompt, **kwargs):
        """Explicit retry-only submission for a pre-existing unbound Attempt."""
        from .bridge import SubmitAttemptResult, SubmitOutcome, ComfyUIJobBridge
        from ..domain.core import BackendJobRef
        from ..adapters.http import ComfyUIRejectedError, ComfyUIProtocolError, ComfyUITransportError
        chunk = next((c for c in execution.chunks if str(c.id) == str(chunk_id)), None)
        attempt = next((a for a in chunk.attempts if str(a.id) == str(attempt_id)), None) if chunk else None
        if attempt is None or attempt.state.value != 'pending' or attempt.external_job_ref is not None:
            raise ValueError('existing retry attempt must be pending and unbound')
        try:
            raw = self.submitter.submit(prompt, **kwargs)
        except ComfyUIRejectedError as exc:
            return SubmitAttemptResult(SubmitOutcome.REJECTED, str(attempt.id), error=f'rejected status={exc.status}')
        except ComfyUIProtocolError as exc:
            return SubmitAttemptResult(SubmitOutcome.PROTOCOL_FAILED, str(attempt.id), error=f'protocol_failure {str(exc)[:4096]}')
        except ComfyUITransportError as exc:
            return SubmitAttemptResult(SubmitOutcome.AMBIGUOUS, str(attempt.id), error=f'ambiguous_transport {str(exc)[:4096]}')
        ref = raw if isinstance(raw, BackendJobRef) else None
        if ref is None or not ref.value.strip():
            return SubmitAttemptResult(SubmitOutcome.INVALID_REF, str(attempt.id), error='invalid backend job reference')
        try:
            self._bridge().bind(project, execution, chunk_id, str(attempt.id), ref, execution_id=execution.id)
        except Exception as exc:
            return SubmitAttemptResult(SubmitOutcome.BIND_FAILED, str(attempt.id), ref, str(exc))
        return SubmitAttemptResult(SubmitOutcome.SUCCEEDED, str(attempt.id), ref)

__all__ = ["SubmitBoundary", "ComfyUISubmitTransport", "validate_configured_output_root"]

class ComfyUISubmitTransport:
    """Transport-only port; it never creates attempts or applies policy."""
    def __init__(self, client): self.client = client
    def submit(self, prompt, **kwargs): return self.client.submit(prompt, **kwargs)
