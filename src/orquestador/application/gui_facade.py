"""UI-facing application facade.  Infrastructure is supplied by injection."""
from dataclasses import dataclass, field
from typing import Any, Callable

@dataclass(frozen=True)
class ChunkSnapshot:
    order: int; state: str; attempt_ref: str|None=None; error: str|None=None; output: str|None=None; transition: str|None=None; chunk_id: str|None=None; prompt: str = ""; overrides: tuple[tuple[str, object], ...] = ()

@dataclass(frozen=True)
class ExecutionSnapshot:
    project_id: str|None=None; execution_id: str|None=None; state: str="unavailable"; chunks: tuple[ChunkSnapshot,...]=(); errors: tuple[str,...]=(); artifacts: tuple[str,...]=(); final_output: str|None=None
    can_cancel: bool=False; cancel_reason: str=""; can_retry: bool=False; can_start: bool=False; can_resume: bool=False; can_recover: bool=False; can_assemble: bool=False; busy: bool=False
    supported_parameters: tuple[str,...]=()
    # None means that the source did not authorize changing references;
    # an empty tuple is an explicit instruction to clear them.
    reference_slots: tuple[str,...] | None = None
    # None means that the source did not authorize changing global generation
    # controls; a tuple is an authoritative durable configuration snapshot.
    configuration: tuple[tuple[str, object], ...] | None = None

@dataclass(frozen=True)
class OperationResult:
    success: bool; snapshot: ExecutionSnapshot; message: str=""; detail: Any=None

class GuiFacade:
    def __init__(self, *, prepare=None, preflight=None, chain=None, resume=None, recover=None, retry=None, assemble=None, cancel=None, snapshot=None, sequence_edit=None):
        self._ops = locals()
        self._snapshot = snapshot
        self._sequence_edit = sequence_edit
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
            outcome=getattr(value,"outcome",None)
            if outcome is not None:
                outcome_value=getattr(outcome,"value",outcome)
                ok = ok and (
                    outcome_value in {"complete", "completed"}
                    or (
                        outcome_value == "retried_complete"
                        and getattr(getattr(value, "completion", None), "success", False)
                    )
                )
            # Chain/recovery use cases return outcome records rather than a UI
            # snapshot. Re-read the durable aggregate so MainWindow renders
            # authoritative chunks/artifacts/capabilities instead of an empty
            # synthetic ``unknown`` snapshot.
            if (outcome is not None or hasattr(value, "result")) and callable(self._snapshot):
                selected = list(args[:2])
                while len(selected) < 2:
                    selected.append(kwargs.get(("project_id", "execution_id")[len(selected)]))
                snap = self.refresh(selected[0], selected[1])
            return OperationResult(ok,snap,"" if ok else getattr(value,"reason","operation failed"),value)
        except Exception as exc:
            # Preserve the selected durable context when an operation fails.  In
            # particular, Start validation errors must not degrade the UI to the
            # generic "select a project" state.
            selection = list(args[:2])
            for key in ("project_id", "execution_id"):
                if len(selection) >= 2:
                    break
                selection.append(kwargs.get(key))
            project_id = selection[0] if selection else None
            execution_id = selection[1] if len(selection) > 1 else None
            return OperationResult(
                False,
                ExecutionSnapshot(
                    project_id=str(project_id) if project_id else None,
                    execution_id=str(execution_id) if execution_id else None,
                    state="error",
                    errors=(str(exc),),
                ),
                str(exc),
                exc,
            )
    def prepare(self,*a,**k): return self._call("prepare",*a,**k)
    def preflight(self,*a,**k): return self._call("preflight",*a,**k)
    def start_chain(self,*a,**k): return self._call("chain",*a,**k)
    def resume_execution(self,*a,**k): return self._call("resume",*a,**k)
    def recover_execution(self,*a,**k): return self._call("recover",*a,**k)
    def retry_execution(self,*a,**k): return self._call("retry",*a,**k)
    def assemble(self, project_id, execution_id, destination):
        return self._call("assemble", project_id, execution_id, destination)
    def cancel_pending(self,*a,**k):
        snap=self.refresh(*a[:2])
        if not snap.can_cancel: return OperationResult(False,snap,snap.cancel_reason or "cancellation unavailable")
        return self._call("cancel",*a,**k)
    def edit_sequence(self, *args, **kwargs):
        if not callable(self._sequence_edit):
            return OperationResult(False, self.refresh(), "sequence editing unavailable")
        return self._call("sequence_edit", *args, **kwargs)
    def _to_snapshot(self,v):
        if isinstance(v,ExecutionSnapshot): return v
        if v is None: return self.refresh()
        if isinstance(v,dict):
            chunks=tuple(ChunkSnapshot(**c) if isinstance(c,dict) else c for c in v.get("chunks",()))
            raw_reference_slots = v.get("reference_slots")
            reference_slots = (None if raw_reference_slots is None
                               else tuple(map(str, raw_reference_slots)))
            raw_configuration = v.get("configuration")
            configuration = (None if raw_configuration is None else
                             tuple((str(k), value) for k, value in dict(raw_configuration).items()))
            return ExecutionSnapshot(project_id=v.get("project_id"), execution_id=v.get("execution_id"), state=str(v.get("state","unknown")), chunks=chunks, errors=tuple(map(str,v.get("errors",()))), artifacts=tuple(map(str,v.get("artifacts",()))), final_output=v.get("final_output"), can_cancel=bool(v.get("can_cancel",False)), cancel_reason=str(v.get("cancel_reason","")), can_retry=bool(v.get("can_retry",False)), can_start=bool(v.get("can_start",False)), can_resume=bool(v.get("can_resume",False)), can_recover=bool(v.get("can_recover",False)), can_assemble=bool(v.get("can_assemble",False)), busy=bool(v.get("busy",False)), supported_parameters=tuple(map(str,v.get("supported_parameters",()))), reference_slots=reference_slots, configuration=configuration)
        chunks=[]
        for i,c in enumerate(getattr(v,"chunks",()) or ()):
            attempts=getattr(c,"attempts",()) or (); a=attempts[-1] if attempts else None
            transition = getattr(getattr(c, "first_frame", None), "materialized_ref", None)
            transition_uri = getattr(transition, "load_image_value", None) if transition else None
            defaults = dict(getattr(c, "defaults", {}) or {})
            chunks.append(ChunkSnapshot(getattr(c,"order",i),str(getattr(getattr(c,"state",None),"value",getattr(c,"state","unknown"))),str(getattr(a,"id",None)) if a else None, None, str(getattr(getattr(a,"output",None),"uri",None)) if getattr(a,"output",None) else None, transition=transition_uri, chunk_id=str(getattr(getattr(c,"id",None),"value",getattr(c,"id", ""))) or None, prompt=str(defaults.get("prompt", "")), overrides=tuple((str(k), v) for k,v in defaults.items() if k != "prompt")))
        raw_reference_slots = getattr(v, "reference_slots", None)
        reference_slots = (None if raw_reference_slots is None
                           else tuple(map(str, raw_reference_slots)))
        raw_configuration = getattr(v, "configuration", None)
        configuration = (None if raw_configuration is None else
                         tuple((str(k), value) for k, value in dict(raw_configuration).items()))
        return ExecutionSnapshot(execution_id=str(getattr(v,"execution_id",getattr(v,"id",""))) or None,state=str(getattr(getattr(v,"state",None),"value",getattr(v,"outcome","unknown"))),chunks=tuple(chunks),errors=tuple(str(x) for x in getattr(v,"errors",()) or ()), reference_slots=reference_slots, configuration=configuration)
