"""Generic, conservative observation of ComfyUI WebSocket events."""
from __future__ import annotations
import json, time, importlib
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Protocol
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from ..domain.core import BackendJobRef
from .http import ComfyUIClient, ComfyUIError, ComfyUIProtocolError, ComfyUITransportError, ComfyUITimeoutError

class ObservationKind(str, Enum):
    QUEUED='queued'; RUNNING='running'; PROGRESS='progress'; COMPLETED='completed'; FAILED='failed'; CANCELLED='cancelled'; UNKNOWN='unknown'

class ObservationIssueKind(str, Enum):
    TIMEOUT='timeout'; TRANSPORT='transport'; PROTOCOL='protocol'

@dataclass(frozen=True)
class ObservationEvent:
    job_ref: BackendJobRef
    kind: ObservationKind
    progress: float | None = None
    payload: Mapping[str, Any] | None = None
    error: str | None = None
    issue_kind: ObservationIssueKind | None = None

class WebSocketTransport(Protocol):
    def connect(self, url: str, *, client_id: str) -> None: ...
    def receive(self, timeout: float) -> str | bytes: ...
    def close(self) -> None: ...

class WebSocketClientTransport:
    """Production transport; ``connect`` consumes an already-final ws(s) URL."""
    def __init__(self) -> None: self._socket = None
    def connect(self, url: str, *, client_id: str) -> None:
        try:
            websocket = importlib.import_module('websocket')
        except ImportError as exc:
            raise ComfyUITransportError('websocket-client is required for live observation') from exc
        # URL conversion/normalization is performed exactly once by observe().
        self._socket = websocket.create_connection(url)
    def receive(self, timeout: float) -> str | bytes:
        if self._socket is None: raise ComfyUITransportError('transport is not connected')
        self._socket.settimeout(timeout)
        return self._socket.recv()
    def close(self) -> None:
        if self._socket is not None: self._socket.close()

class ComfyUIObservation:
    def __init__(self, client: ComfyUIClient, *, transport: WebSocketTransport | None = None, client_id: str = 'orquestador', timeout: float = 5.0, reconnects: int = 2, backoff: float = 0.1):
        if not client_id.strip() or timeout <= 0 or reconnects < 0 or backoff < 0: raise ValueError('invalid observation configuration')
        self.client, self.transport, self.client_id = client, transport or WebSocketClientTransport(), client_id.strip()
        self.timeout, self.reconnects, self.backoff = timeout, reconnects, backoff

    @staticmethod
    def websocket_url(endpoint: str, client_id: str) -> str:
        if not isinstance(endpoint, str) or not isinstance(client_id, str) or not client_id.strip():
            raise ValueError('invalid endpoint or client_id')
        p = urlsplit(endpoint)
        try: port = p.port
        except ValueError as exc: raise ValueError('endpoint has invalid port') from exc
        if p.scheme not in {'http', 'https'} or not p.hostname or p.username is not None or p.password is not None or p.fragment:
            raise ValueError('endpoint must be unambiguous http(s) URL')
        if p.netloc != p.hostname and port is None and ':' in p.netloc:
            raise ValueError('endpoint has ambiguous authority')
        scheme = 'ws' if p.scheme == 'http' else 'wss'
        base = p.path or ''
        path = base.rstrip('/')
        if not path.endswith('/ws'): path += '/ws'
        query = parse_qsl(p.query, keep_blank_values=True, strict_parsing=False)
        query.append(('clientId', client_id.strip()))
        return urlunsplit((scheme, p.netloc, path or '/ws', urlencode(query, doseq=True), ''))

    @staticmethod
    def _event(ref: BackendJobRef, message: Mapping[str, Any]) -> ObservationEvent | None:
        if not isinstance(message, dict): return None
        typ, data = message.get('type'), message.get('data')
        if not isinstance(data, dict):
            # An event-looking object with non-object data is protocol
            # corruption.  There is no reliable prompt identity to use for
            # correlation, so fail closed for the current observation stream.
            if 'type' in message:
                return ObservationEvent(ref, ObservationKind.UNKNOWN, error='malformed event data', issue_kind=ObservationIssueKind.PROTOCOL)
            return None
        prompt_id = data.get('prompt_id')
        if not isinstance(prompt_id, str) or not prompt_id.strip() or prompt_id != ref.value: return None
        if not isinstance(typ, str): return ObservationEvent(ref, ObservationKind.UNKNOWN, payload=data, error='malformed event type', issue_kind=ObservationIssueKind.PROTOCOL)
        kind = {'execution_start': ObservationKind.RUNNING, 'progress': ObservationKind.PROGRESS, 'execution_success': ObservationKind.COMPLETED, 'execution_error': ObservationKind.FAILED}.get(typ)
        if kind is None: return ObservationEvent(ref, ObservationKind.UNKNOWN, payload=data, error='unsupported event type', issue_kind=ObservationIssueKind.PROTOCOL)
        if typ == 'execution_error':
            err = data.get('exception_message', data.get('error'))
            if not isinstance(err, str) or not err.strip(): return ObservationEvent(ref, ObservationKind.UNKNOWN, payload=data, error='malformed execution_error')
        value = data.get('value') if isinstance(data.get('value'), (int,float)) and not isinstance(data.get('value'), bool) else None
        maximum = data.get('max') if isinstance(data.get('max'), (int,float)) and not isinstance(data.get('max'), bool) else None
        progress = value / maximum if kind is ObservationKind.PROGRESS and value is not None and maximum is not None and maximum > 0 else None
        return ObservationEvent(ref, kind, progress, data, (data.get('exception_message') or data.get('error')) if kind is ObservationKind.FAILED else None)

    def observe(self, job_ref: BackendJobRef) -> Iterable[ObservationEvent]:
        ref = job_ref if isinstance(job_ref, BackendJobRef) else BackendJobRef(job_ref)
        terminal = False; attempts = 0; seen_terminal: set[ObservationKind] = set(); issue_kind: ObservationIssueKind | None = None
        url = self.websocket_url(self.client.endpoint, self.client_id)
        while not terminal and attempts <= self.reconnects:
            try:
                self.transport.connect(url, client_id=self.client_id)
                while not terminal:
                    raw = self.transport.receive(self.timeout)
                    try: msg = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                    except (ValueError, UnicodeDecodeError, AttributeError):
                        issue_kind = ObservationIssueKind.PROTOCOL
                        attempts = self.reconnects + 1
                        yield ObservationEvent(ref, ObservationKind.UNKNOWN, error='malformed WebSocket frame', issue_kind=issue_kind); break
                    if not isinstance(msg, dict):
                        issue_kind = ObservationIssueKind.PROTOCOL
                        attempts = self.reconnects + 1
                        yield ObservationEvent(ref, ObservationKind.UNKNOWN, error='unsupported WebSocket frame', issue_kind=issue_kind); break
                    event = self._event(ref, msg)
                    if event:
                        if event.kind in seen_terminal: continue
                        yield event
                        if event.kind in {ObservationKind.COMPLETED, ObservationKind.FAILED}: seen_terminal.add(event.kind)
                        terminal = event.kind in {ObservationKind.COMPLETED, ObservationKind.FAILED, ObservationKind.CANCELLED}
                        if event.issue_kind is ObservationIssueKind.PROTOCOL:
                            issue_kind = ObservationIssueKind.PROTOCOL
                            attempts = self.reconnects + 1
                            break
            except ComfyUIProtocolError as exc:
                issue_kind = ObservationIssueKind.PROTOCOL
                yield ObservationEvent(ref, ObservationKind.UNKNOWN, error=f'protocol error: {exc}', issue_kind=issue_kind); break
            except (ComfyUITimeoutError, TimeoutError) as exc:
                issue_kind = ObservationIssueKind.TIMEOUT
                attempts += 1
                if attempts > self.reconnects: break
                time.sleep(self.backoff * attempts)
            except (ComfyUITransportError, OSError) as exc:
                issue_kind = ObservationIssueKind.TRANSPORT
                attempts += 1
                if attempts > self.reconnects: break
                time.sleep(self.backoff * attempts)
            finally:
                self.transport.close()
        if terminal: return
        try:
            h = self.client.history(ref)
            mapping = {'succeeded': ObservationKind.COMPLETED, 'failed': ObservationKind.FAILED, 'running': ObservationKind.RUNNING, 'queued': ObservationKind.QUEUED}
            kind = mapping.get(h.state.value)
            if kind: yield ObservationEvent(ref, kind, payload=h.raw, error=h.error, issue_kind=issue_kind)
            else:
                q = self.client.queue()
                if ref in q.running and ref in q.pending: yield ObservationEvent(ref, ObservationKind.UNKNOWN, error='ambiguous queue evidence', issue_kind=issue_kind)
                elif ref in q.running: yield ObservationEvent(ref, ObservationKind.RUNNING, issue_kind=issue_kind)
                elif ref in q.pending: yield ObservationEvent(ref, ObservationKind.QUEUED, issue_kind=issue_kind)
                else: yield ObservationEvent(ref, ObservationKind.UNKNOWN, error='observation inconclusive', issue_kind=issue_kind)
        except (ComfyUIError, OSError) as exc:
            if isinstance(exc, ComfyUITimeoutError): issue_kind = ObservationIssueKind.TIMEOUT
            elif isinstance(exc, (ComfyUITransportError, OSError)): issue_kind = ObservationIssueKind.TRANSPORT
            elif isinstance(exc, ComfyUIProtocolError): issue_kind = ObservationIssueKind.PROTOCOL
            yield ObservationEvent(ref, ObservationKind.UNKNOWN, error=str(exc), issue_kind=issue_kind)

__all__ = ['ObservationKind','ObservationIssueKind','ObservationEvent','WebSocketTransport','WebSocketClientTransport','ComfyUIObservation']
