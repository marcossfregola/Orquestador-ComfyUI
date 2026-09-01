"""Composition root and conservative desktop launcher for F9."""
from __future__ import annotations
import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ..adapters.http import ComfyUIClient
from ..adapters.cancellation import ComfyUICancellationAdapter
from ..adapters.assembly import FFmpegAssemblyAdapter
from ..application.gui_facade import GuiFacade
from ..application.bridge import SubmitAttemptUseCase
from ..application.chunk_execution import ChunkExecutionCoordinator
from ..application.robust_chunk_execution import RobustChunkExecutionCoordinator
from ..application.recover_execution import ResumeExecutionUseCase, RecoverExecutionUseCase, RetryExecutionUseCase
from ..application.chain_execution import ChainExecutionUseCase
from ..application.assembly import AssembleExecutionUseCase
from ..adapters.video import FFmpegVideoAdapter
from ..domain.core import Lifecycle, MaterializedInputRef
from ..application.prepare_gui import PrepareGuiUseCase
from ..application.start_gui_chain import StartGuiChainUseCase, StaticInputMaterializer
from ..persistence.sqlite import SQLiteProjectRepository

class StartupConfigurationError(ValueError):
    """Actionable configuration error raised before external service calls."""

@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    comfyui_endpoint: str = "http://127.0.0.1:8188"
    workflow_template: Path | None = None
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    comfyui_output_root: Path | None = None

    def check(self) -> "AppConfig":
        root = self.project_root.expanduser()
        if not root.is_absolute():
            raise StartupConfigurationError("--project-root must be an absolute writable directory")
        if root.exists() and not root.is_dir():
            raise StartupConfigurationError("--project-root must name a directory")
        if not self.comfyui_endpoint.strip():
            raise StartupConfigurationError("--comfyui-endpoint must be non-empty")
        template = self.workflow_template
        if template is not None and (not template.is_absolute() or not template.is_file()):
            raise StartupConfigurationError("--workflow-template must be an existing absolute file")
        output_root = (self.comfyui_output_root or root).expanduser()
        if not output_root.is_absolute() or not output_root.is_dir():
            raise StartupConfigurationError("--comfyui-output-root must be an existing absolute directory")
        return AppConfig(root, self.comfyui_endpoint.strip(), template, self.ffmpeg, self.ffprobe, output_root.resolve())

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m orquestador", description="Launch Orquestador desktop UI")
    p.add_argument("--project-root", required=True, type=Path, help="absolute project data directory")
    p.add_argument("--comfyui-endpoint", default="http://127.0.0.1:8188")
    p.add_argument("--workflow-template", type=Path)
    p.add_argument("--ffmpeg", default="ffmpeg")
    p.add_argument("--ffprobe", default="ffprobe")
    p.add_argument("--comfyui-output-root", type=Path, help="existing absolute ComfyUI output directory")
    return p

def parse_config(argv: Sequence[str] | None = None) -> AppConfig:
    ns = build_parser().parse_args(argv)
    return AppConfig(ns.project_root, ns.comfyui_endpoint, ns.workflow_template, ns.ffmpeg, ns.ffprobe, ns.comfyui_output_root).check()

def compose(config: AppConfig, *, repository_factory=SQLiteProjectRepository,
            client_factory=ComfyUIClient, cancellation_factory=ComfyUICancellationAdapter,
            assembler_factory=FFmpegAssemblyAdapter, chain_usecase=None,
            resume_usecase=None, recover_usecase=None, retry_usecase=None,
            assembly_usecase=None, extractor_factory=FFmpegVideoAdapter):
    """Build concrete production boundaries; no network call is made here."""
    cfg = config.check()
    repository = repository_factory(cfg.project_root)
    client = client_factory(cfg.comfyui_endpoint)
    cancellation = cancellation_factory(client)
    assembler = assembler_factory(cfg.ffprobe, cfg.ffmpeg) if assembler_factory is FFmpegAssemblyAdapter else assembler_factory()
    extractor = extractor_factory(cfg.ffprobe, cfg.ffmpeg) if extractor_factory is FFmpegVideoAdapter else extractor_factory()
    submitter = SubmitAttemptUseCase(repository, client)
    monitor = lambda ref, **_: client.history(ref)
    class BackendObservationAdapter:
        def observe(self, ref): return client.history(ref)
        def history(self, ref): return client.history(ref)
    backend = BackendObservationAdapter()
    coordinator = __import__('orquestador.application.chunk_execution', fromlist=['ChunkExecutionCoordinator']).ChunkExecutionCoordinator(
        repository, submitter, monitor, extractor=extractor, trusted_root=cfg.project_root, comfyui_output_root=cfg.comfyui_output_root)
    # Production chain execution must keep the accepted attempt while
    # observing transient queue/history states until terminal evidence.  Keep
    # the plain coordinator for recovery/completion services, and wrap it only
    # at the chain orchestration boundary where bounded polling belongs.
    chain_coordinator = RobustChunkExecutionCoordinator(coordinator)
    resume_real = ResumeExecutionUseCase(repository, backend, coordinator, submitter)
    recover_real = RecoverExecutionUseCase(repository, backend)
    chain_real = ChainExecutionUseCase(repository, chain_coordinator, recovery=resume_real)
    assembly_real = AssembleExecutionUseCase(assembler, cfg.project_root)
    retry_real = RetryExecutionUseCase(repository, resume_real)
    chain_usecase = chain_usecase or chain_real
    resume_usecase = resume_usecase or resume_real
    recover_usecase = recover_usecase or recover_real
    retry_usecase = retry_usecase or retry_real
    assembly_usecase = assembly_usecase or assembly_real
    def snapshot(project_id=None, execution_id=None):
        if not project_id: return {"state":"unavailable","errors":("select a project",)}
        project, executions = repository.load(project_id)
        matches=[e for e in executions if execution_id is None or str(e.id)==str(execution_id)]
        if len(matches)!=1: return {"project_id":str(project_id),"state":"unavailable","errors":("execution selection is ambiguous or missing",)}
        e=matches[0]; chunks=[]; outputs=[]; target=[]
        for c in e.chunks:
            a=c.attempts[-1] if c.attempts else None
            chunks.append({"order":c.order,"state":c.state.value,"attempt_ref":str(a.id) if a else None,"error":a.error.message if a and a.error else None,"output":a.output.uri if a and a.output else None})
            if a and a.output and a.state is Lifecycle.SUCCEEDED: outputs.append(a.output.uri)
            if a and a.external_job_ref: target.append(a.external_job_ref)
        can_cancel=len(target)==1 and e.state is Lifecycle.RUNNING and any(c.state is Lifecycle.RUNNING for c in e.chunks)
        retryable = (retry_usecase is not None and e.state is Lifecycle.FAILED and
                     any(c.state is Lifecycle.FAILED and len(c.attempts) == 1 and
                         c.attempts[0].state is Lifecycle.FAILED for c in e.chunks))
        return {"project_id":str(project_id),"execution_id":str(e.id),"state":e.state.value,"chunks":chunks,"artifacts":[a.output.uri for a in e.artifacts],"can_start":e.state is Lifecycle.PENDING,"can_resume":e.state in (Lifecycle.RUNNING,Lifecycle.FAILED),"can_recover":e.state in (Lifecycle.RUNNING,Lifecycle.FAILED),"can_retry":retryable,"can_cancel":can_cancel,"cancel_reason":"no unique safe pending target" if not can_cancel else "","can_assemble":e.state is Lifecycle.SUCCEEDED and len(outputs)==len(e.chunks) and len(outputs)>=2}
    def cancel(project_id, execution_id):
        s=snapshot(project_id,execution_id)
        if not s["can_cancel"]: raise ValueError(s.get("cancel_reason","cancellation unavailable"))
        _, es=repository.load(project_id); e=next(x for x in es if str(x.id)==str(execution_id)); refs=[a.external_job_ref for c in e.chunks for a in c.attempts if a.external_job_ref]
        return {**s,"can_cancel":False,"state":"cancellation_requested"} if len(refs)==1 and cancellation.cancel(refs[0]) else s
    def preflight(*_a, **_k):
        health = client.health()
        return {"state": "preflight", "errors": (), "can_cancel": False}
    prepare = PrepareGuiUseCase(repository, cfg.project_root, snapshot)
    def resume_route(project_id, execution_id=None, **kwargs): return resume_usecase.resume(project_id, execution_id, **kwargs)
    def recover_route(project_id, execution_id=None, **_): return recover_usecase.recover(project_id, execution_id)
    def retry_route(project_id, execution_id=None, **kwargs): return retry_usecase.retry(project_id, execution_id, **kwargs)
    def assemble_route(project_id, execution_id=None, destination=None, **_):
        project, executions = repository.load(project_id); e=next(x for x in executions if str(x.id)==str(execution_id))
        outputs=[a.output.uri for c in e.chunks for a in reversed(c.attempts) if a.output and a.state is Lifecycle.SUCCEEDED]
        return assembly_usecase.execute(outputs, destination or f"assembled-{e.id}.mp4")
    def materialize_transition(transition):
        # The transition input is the exact N-1 frame extracted by the F5
        # coordinator, never the source MP4 itself.
        materialized_ref = transition.materialized_ref if hasattr(transition, 'materialized_ref') else None
        if isinstance(materialized_ref, MaterializedInputRef):
            return materialized_ref
        root = cfg.project_root.resolve()
        frame = (root / 'transitions' / f'{transition.source_attempt_id}.png').resolve()
        try:
            frame.relative_to(root)
        except ValueError as exc:
            raise ValueError('transition frame escapes project root') from exc
        if not frame.is_file():
            raise ValueError('transition frame is missing')
        digest=hashlib.sha256(frame.read_bytes()).hexdigest()
        requested=f"transition-{transition.source_attempt_id}-{digest[:16]}.png"
        value=client.upload_image(frame, subfolder='orquestador/transitions', overwrite=False,
                                  requested_filename=requested)
        if (not isinstance(value,dict) or value.get('type')!='input' or
                not isinstance(value.get('name'),str) or not value.get('name') or
                not isinstance(value.get('subfolder',''),str)):
            raise ValueError('invalid materialized upload')
        try:
            return MaterializedInputRef('input', value.get('subfolder',''), value['name'], digest)
        except Exception as exc:
            raise ValueError('unsafe materialized upload reference') from exc
    static_materializer = StaticInputMaterializer(client, cfg.project_root)
    start_usecase = StartGuiChainUseCase(repository, cfg.project_root, chain_usecase, cfg.workflow_template, static_materializer, materialize_transition)
    # Keep the composition route as a thin closure; all validation/binding remains
    # owned by the application-layer use case.
    def start_chain(project_id, execution_id, **kwargs):
        # Keep the concrete chain dependency observable at the composition boundary.
        _chain = chain_usecase
        return start_usecase(project_id, execution_id, **kwargs)
    facade = GuiFacade(prepare=prepare, preflight=preflight, retry=retry_route, chain=start_chain,
                       resume=resume_route, recover=recover_route, assemble=assemble_route,
                       cancel=cancel, snapshot=snapshot)
    return facade, {"repository": repository, "client": client, "cancellation": cancellation,
                    "assembler": assembler, "submitter": submitter, "coordinator": coordinator,
                    "chain": chain_usecase, "resume": resume_usecase, "recover": recover_usecase,
                    "retry": retry_usecase,
                    "assemble": assembly_usecase}

def launch(config: AppConfig) -> int:
    from importlib import import_module
    QApplication = import_module("PySide6.QtWidgets").QApplication
    from .main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    facade, resources = compose(config)
    window = MainWindow(facade); window.show()
    try:
        return int(app.exec())
    finally:
        resources["repository"].close()

def main(argv: Sequence[str] | None = None) -> int:
    return launch(parse_config(argv))
