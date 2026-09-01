"""UI-facing application facade.  Infrastructure is supplied by injection."""
from dataclasses import dataclass, field
from typing import Any, Callable

@dataclass(frozen=True)
class ChunkSnapshot:
    order: int; state: str; attempt_ref: str|None=None; error: str|None=None; output: str|None=None; transition: str|None=None

@dataclass(frozen=True)
class ExecutionSnapshot:
    project_id: str|None=None; execution_id: str|None=None; state: str="unavailable"; chunks: tuple[ChunkSnapshot,...]=(); errors: tuple[str,...]=(); artifacts: tuple[str,...]=(); final_output: str|None=None
    can_cancel: bool=False; cancel_reason: str=""; can_retry: bool=False; can_start: bool=False; can_resume: bool=False; can_recover: bool=False; can_assemble: bool=False; busy: bool=False
    supported_parameters: tuple[str,...]=()
    reference_slots: tuple[str,...]=()

@dataclass(frozen=True)
class OperationResult:
    success: bool; snapshot: ExecutionSnapshot; message: str=""; detail: Any=None

class GuiFacade:
    def __init__(self, *, prepare=None, preflight=None, chain=None, resume=None, recover=None, retry=None, assemble=None, cancel=None, snapshot=None):
        self._ops = locals()
        self._snapshot = snapshot
    def refresh(self, project_id=None, execution_id=None):
        if self._snapshot is None: return ExecutionSnapshot(project_id=str(project_id) if project_id else None, execution_id=str(execution_id) if execution_id else None)
        try: return self._to_snapshot(self._snapshot(project_id, execution_id))
        except Exception as exc: return ExecutionSnapshot(project_id=str(project_id) if project_id else None, execution_id=str(execution_id) if execution_id else None, state="error", errors=(str(exc),))
    def _call(self, name, *args, **kwargs):
        fn=self._ops.get(name)
        if not callable(fn): return OperationResult(False, self.refresh(), f"{name} unavailable")
        try:
            value=fn(*args, **kwargs); snap=self._to_snapshot(value)
            ok=getattr(value,"success",True) is not False
            return OperationResult(ok,snap,"" if ok else getattr(value,"reason","operation failed"),value)
        except Exception as exc: return OperationResult(False, self.refresh(), str(exc), exc)
    def prepare(self,*a,**k): return self._call("prepare",*a,**k)
    def preflight(self,*a,**k): return self._call("preflight",*a,**k)
    def start_chain(self,*a,**k): return self._call("chain",*a,**k)
    def resume_execution(self,*a,**k): return self._call("resume",*a,**k)
    def recover_execution(self,*a,**k): return self._call("recover",*a,**k)
    def retry_execution(self,*a,**k): return self._call("retry",*a,**k)
    def assemble(self,*a,**k): return self._call("assemble",*a,**k)
    def cancel_pending(self,*a,**k):
        snap=self.refresh(*a[:2])
        if not snap.can_cancel: return OperationResult(False,snap,snap.cancel_reason or "cancellation unavailable")
        return self._call("cancel",*a,**k)
    def _to_snapshot(self,v):
        if isinstance(v,ExecutionSnapshot): return v
        if v is None: return self.refresh()
        if isinstance(v,dict):
            chunks=tuple(ChunkSnapshot(**c) if isinstance(c,dict) else c for c in v.get("chunks",()))
            return ExecutionSnapshot(project_id=v.get("project_id"), execution_id=v.get("execution_id"), state=str(v.get("state","unknown")), chunks=chunks, errors=tuple(map(str,v.get("errors",()))), artifacts=tuple(map(str,v.get("artifacts",()))), final_output=v.get("final_output"), can_cancel=bool(v.get("can_cancel",False)), cancel_reason=str(v.get("cancel_reason","")), can_retry=bool(v.get("can_retry",False)), can_start=bool(v.get("can_start",False)), can_resume=bool(v.get("can_resume",False)), can_recover=bool(v.get("can_recover",False)), can_assemble=bool(v.get("can_assemble",False)), busy=bool(v.get("busy",False)), supported_parameters=tuple(map(str,v.get("supported_parameters",()))), reference_slots=tuple(map(str,v.get("reference_slots",()))))
        chunks=[]
        for i,c in enumerate(getattr(v,"chunks",()) or ()):
            attempts=getattr(c,"attempts",()) or (); a=attempts[-1] if attempts else None
            chunks.append(ChunkSnapshot(getattr(c,"order",i),str(getattr(getattr(c,"state",None),"value",getattr(c,"state","unknown"))),str(getattr(a,"id",None)) if a else None, None, str(getattr(getattr(a,"output",None),"uri",None)) if getattr(a,"output",None) else None))
        return ExecutionSnapshot(execution_id=str(getattr(v,"execution_id",getattr(v,"id",""))) or None,state=str(getattr(getattr(v,"state",None),"value",getattr(v,"outcome","unknown"))),chunks=tuple(chunks),errors=tuple(str(x) for x in getattr(v,"errors",()) or ()))
