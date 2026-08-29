"""Small, conservative HTTP adapter for the native ComfyUI API."""
from __future__ import annotations
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
import socket
from urllib.request import Request, urlopen
from urllib.parse import quote, urlsplit

from ..domain.core import BackendJobRef

class ComfyUIError(RuntimeError): pass
class ComfyUITransportError(ComfyUIError): pass
class ComfyUITimeoutError(ComfyUITransportError): pass
class ComfyUIProtocolError(ComfyUIError): pass
class ComfyUIServerError(ComfyUIError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message); self.status = status
class ComfyUIRejectedError(ComfyUIServerError): pass

class QueueState(str, Enum): RUNNING='running'; PENDING='pending'; EMPTY='empty'; UNKNOWN='unknown'
class HistoryState(str, Enum): RUNNING='running'; QUEUED='queued'; SUCCEEDED='succeeded'; FAILED='failed'; NOT_FOUND='not_found'; UNKNOWN='unknown'

@dataclass(frozen=True)
class HealthResult:
    healthy: bool; details: Mapping[str, Any] | None = None
@dataclass(frozen=True)
class QueueSnapshot:
    running: tuple[BackendJobRef, ...] = (); pending: tuple[BackendJobRef, ...] = (); state: QueueState = QueueState.UNKNOWN
@dataclass(frozen=True)
class HistoryResult:
    prompt_id: BackendJobRef; state: HistoryState; raw: Mapping[str, Any] | None = None; error: str | None = None

class ComfyUIClient:
    def __init__(self, endpoint: str = 'http://127.0.0.1:8188', timeout: float = 10.0):
        if not isinstance(endpoint, str): raise ValueError('endpoint must be a string')
        parts = urlsplit(endpoint)
        if parts.scheme not in {'http','https'} or not parts.hostname or parts.query or parts.fragment or parts.username is not None or parts.password is not None: raise ValueError('endpoint must be http(s), with hostname, no query/fragment/userinfo')
        self.endpoint = endpoint.rstrip('/') or f'{parts.scheme}://{parts.hostname}'; self.timeout = float(timeout)
        if self.timeout <= 0: raise ValueError('timeout must be positive')

    def _request(self, method: str, path: str, payload: Any = None, *, allow_empty: bool = False) -> Any:
        data = None if payload is None else json.dumps(payload).encode('utf-8')
        req = Request(self.endpoint + path, data=data, method=method, headers={'Accept':'application/json', **({'Content-Type':'application/json'} if data else {})})
        try:
            with urlopen(req, timeout=self.timeout) as response:
                body = response.read()
        except (TimeoutError, socket.timeout) as exc: raise ComfyUITimeoutError(str(exc)) from exc
        except HTTPError as exc:
            try: detail = exc.read().decode('utf-8', 'replace')
            except Exception: detail = str(exc)
            if 400 <= exc.code < 500: raise ComfyUIRejectedError(f'ComfyUI rejected request ({exc.code}): {detail}', exc.code) from exc
            raise ComfyUIServerError(f'ComfyUI server error ({exc.code}): {detail}', exc.code) from exc
        except URLError as exc:
            reason = getattr(exc, 'reason', None)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise ComfyUITimeoutError(str(exc)) from exc
            raise ComfyUITransportError(str(exc)) from exc
        except OSError as exc: raise ComfyUITransportError(str(exc)) from exc
        if not body and allow_empty: return None
        try: return json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise ComfyUIProtocolError('response was not valid JSON') from exc

    def health(self) -> HealthResult:
        value = self._request('GET', '/system_stats')
        system = value.get('system') if isinstance(value, dict) else None
        if not isinstance(system, dict) or not system or not isinstance(system.get('os'), str) or not system.get('os').strip(): raise ComfyUIProtocolError('/system_stats response lacks credible system fields')
        return HealthResult(True, value)
    preflight = health

    def submit(self, prompt: Mapping[str, Any], client_id: str | None = None) -> BackendJobRef:
        if client_id is not None and (not isinstance(client_id, str) or not client_id.strip()): raise ComfyUIProtocolError('client_id must be a nonblank string')
        payload = dict(prompt)
        if client_id is not None: payload['client_id'] = client_id.strip()
        value = self._request('POST', '/prompt', payload)
        if not isinstance(value, dict) or not isinstance(value.get('prompt_id'), str) or not value['prompt_id'].strip():
            raise ComfyUIProtocolError('submit response missing nonblank prompt_id')
        return BackendJobRef(value['prompt_id'])

    @staticmethod
    def _ids(items: Any) -> tuple[BackendJobRef, ...] | None:
        if not isinstance(items, list): return None
        out=[]
        for item in items:
            if not isinstance(item, list) or len(item) != 5 or isinstance(item[0], bool) or not isinstance(item[0], int): return None
            raw = item[1]
            if not isinstance(raw, str) or not raw.strip(): return None
            out.append(BackendJobRef(raw))
        return tuple(out)

    def queue(self) -> QueueSnapshot:
        value = self._request('GET', '/queue')
        if not isinstance(value, dict): raise ComfyUIProtocolError('/queue response must be an object')
        running, pending = self._ids(value.get('queue_running')), self._ids(value.get('queue_pending'))
        if running is None or pending is None: return QueueSnapshot(state=QueueState.UNKNOWN)
        state = QueueState.RUNNING if running else QueueState.PENDING if pending else QueueState.EMPTY
        return QueueSnapshot(running, pending, state)
    queue_snapshot = queue

    def history(self, prompt_id: BackendJobRef | str) -> HistoryResult:
        if isinstance(prompt_id, BackendJobRef): ref = prompt_id
        elif isinstance(prompt_id, str) and prompt_id.strip(): ref = BackendJobRef(prompt_id)
        else: raise ComfyUIProtocolError('prompt_id must be a nonblank string or BackendJobRef')
        try: value = self._request('GET', '/history/' + quote(ref.value, safe=''))
        except ComfyUIRejectedError as exc:
            if exc.status == 404: return HistoryResult(ref, HistoryState.NOT_FOUND, error=str(exc))
            raise
        if not isinstance(value, dict): raise ComfyUIProtocolError('history response must be an object')
        entry = value.get(ref.value, value if 'status' in value else None)
        if entry is None: return HistoryResult(ref, HistoryState.NOT_FOUND, value)
        if not isinstance(entry, dict): return HistoryResult(ref, HistoryState.UNKNOWN, error='malformed history entry')
        status = entry.get('status')
        if not isinstance(status, dict): return HistoryResult(ref, HistoryState.UNKNOWN, entry, 'missing status')
        text = status.get('status_str') if isinstance(status.get('status_str'), str) else ''
        text = text.lower()
        failure = any(k in status for k in ('exception_message','error','errors'))
        if failure: return HistoryResult(ref, HistoryState.FAILED, entry, str(status.get('exception_message') or status.get('error') or status.get('errors')))
        if text in {'success','completed'}:
            outputs = entry.get('outputs')
            complete = status.get('completed') is True or status.get('completed') is not None and isinstance(status.get('completed'), (int,float)) and not isinstance(status.get('completed'), bool)
            if complete and (outputs is not None and isinstance(outputs, dict)): return HistoryResult(ref, HistoryState.SUCCEEDED, entry)
            return HistoryResult(ref, HistoryState.UNKNOWN, entry, 'ambiguous success evidence')
        if text in {'error','failed','failure'}: return HistoryResult(ref, HistoryState.FAILED, entry, text)
        if text in {'running','executing'}: return HistoryResult(ref, HistoryState.RUNNING, entry)
        if text in {'queued','pending'}: return HistoryResult(ref, HistoryState.QUEUED, entry)
        return HistoryResult(ref, HistoryState.UNKNOWN, entry, 'unrecognized terminal status')
    history_lookup = history

    @staticmethod
    def _mutation_ids(prompt_ids: Any) -> list[str]:
        if not isinstance(prompt_ids, (list, tuple)) or not prompt_ids:
            raise ComfyUIProtocolError('prompt_ids must be a non-empty sequence')
        out=[]
        for item in prompt_ids:
            if isinstance(item, BackendJobRef): value=item.value
            elif isinstance(item, str) and item.strip(): value=item.strip()
            else: raise ComfyUIProtocolError('prompt_ids must contain BackendJobRef or nonblank strings')
            out.append(value)
        return out

    def delete_pending(self, prompt_ids: list[BackendJobRef | str] | tuple[BackendJobRef | str, ...]) -> None:
        """Delete only the supplied pending IDs; ComfyUI may return no body."""
        self._request('POST', '/queue', {'delete': self._mutation_ids(prompt_ids)}, allow_empty=True)

    def interrupt_running_native_non_atomic(self, prompt_id: BackendJobRef | str) -> None:
        """Expose native ``/interrupt`` for low-level callers only.

        ComfyUI 0.33.0 does not make this route an atomic, target-safe
        running cancellation. The F3-4 safe adapter deliberately never calls
        this method.
        """
        ids = self._mutation_ids((prompt_id,))
        self._request('POST', '/interrupt', {'prompt_id': ids[0]}, allow_empty=True)
