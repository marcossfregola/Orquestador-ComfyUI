"""Neutral submit boundary shared by orchestration primitives.

This module deliberately has no dependency on the F11.1B orchestrator; it is
the transport-to-durable-attempt port used by the policy owner and primitives.
"""
import json
from collections.abc import Mapping
from pathlib import Path


_MAX_REJECTION_DETAIL = 768


def _compact_text(value, limit=_MAX_REJECTION_DETAIL):
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _rejection_body_detail(body):
    """Extract a bounded human-readable description from a ComfyUI 4xx body."""
    if body is None:
        return ""
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", "replace")
    parsed = body
    if isinstance(body, str):
        raw = body.strip()
        if not raw:
            return ""
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return _compact_text(raw)

    if isinstance(parsed, Mapping):
        node_errors = parsed.get("node_errors")
        descriptions = []
        if isinstance(node_errors, Mapping):
            for node_id, node_error in node_errors.items():
                if not isinstance(node_error, Mapping):
                    continue
                class_type = str(node_error.get("class_type") or "node").strip()
                errors = node_error.get("errors")
                if not isinstance(errors, (list, tuple)):
                    errors = [errors]
                for error in errors:
                    if isinstance(error, Mapping):
                        detail = error.get("details") or error.get("message")
                    else:
                        detail = error
                    if detail:
                        descriptions.append(f"{class_type} {node_id}: {_compact_text(detail, 220)}")
                    if len(descriptions) >= 6:
                        break
                if len(descriptions) >= 6:
                    break
        if descriptions:
            return _compact_text("; ".join(descriptions))

        error = parsed.get("error")
        if isinstance(error, Mapping):
            detail = error.get("details") or error.get("message") or error.get("type")
        else:
            detail = error or parsed.get("message") or parsed.get("details")
        if detail:
            return _compact_text(detail)
        try:
            return _compact_text(json.dumps(parsed, ensure_ascii=False, separators=(",", ":")))
        except (TypeError, ValueError):
            return _compact_text(parsed)
    return _compact_text(parsed)


def _format_rejection(exc):
    status = getattr(exc, "status", None)
    detail = _rejection_body_detail(getattr(exc, "body", None))
    if not detail:
        detail = _compact_text(str(exc)) or "sin detalle de ComfyUI"
    status_text = f"status={status}" if status is not None else "status=unknown"
    return f"ComfyUI rejected prompt ({status_text}): {detail}"

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
            detail = _format_rejection(exc)
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
            return SubmitAttemptResult(SubmitOutcome.REJECTED, str(attempt.id), error=_format_rejection(exc))
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
