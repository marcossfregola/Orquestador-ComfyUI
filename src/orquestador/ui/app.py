"""Composition root and conservative desktop launcher for F9."""
from __future__ import annotations
import argparse
import hashlib
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ..adapters.http import ComfyUIClient
from ..adapters.cancellation import ComfyUICancellationAdapter
from ..adapters.assembly import FFmpegAssemblyAdapter
from ..application.gui_facade import GuiFacade
from ..application.bridge import SubmitAttemptUseCase
from ..application.chunk_execution import ChunkExecutionCoordinator
from ..application.f11_1b import validate_configured_output_root, F11_1BOrchestrator, SubmitBoundary, derive_capabilities, select_active_cancellation_target
from ..application.submit_boundary import ComfyUISubmitTransport
from ..application.robust_chunk_execution import RobustChunkExecutionCoordinator
from ..application.recover_execution import ResumeExecutionUseCase, RecoverExecutionUseCase, RetryExecutionUseCase
from ..application.chain_execution import ChainExecutionUseCase
from ..application.assembly import AssembleExecutionUseCase, AssemblySource, AssemblySourceRoot
from ..adapters.video import FFmpegVideoAdapter
from ..domain.core import Lifecycle, MaterializedInputRef
from ..application.prepare_gui import PrepareGuiUseCase, PreflightGuiUseCase
from ..application.start_gui_chain import StartGuiChainUseCase
from ..application.f11_1b import InputMaterializationService
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
        # ComfyUI's output tree is a separate trust boundary.  Never infer it
        # from the project root: an omitted value remains unavailable and the
        # execution boundary will fail closed before observing/importing an
        # output.  When supplied, validate it once at composition time.
        output_root = self.comfyui_output_root.expanduser() if self.comfyui_output_root is not None else None
        if output_root is not None:
            if not output_root.is_absolute():
                raise StartupConfigurationError("--comfyui-output-root must be an absolute existing directory")
            try: output_root = validate_configured_output_root(output_root)
            except ValueError as exc: raise StartupConfigurationError(str(exc)) from exc
        return AppConfig(root, self.comfyui_endpoint.strip(), template, self.ffmpeg, self.ffprobe, output_root)

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
    injected_chain = chain_usecase is not None
    injected_resume = resume_usecase is not None
    injected_recover = recover_usecase is not None
    injected_retry = retry_usecase is not None
    repository = repository_factory(cfg.project_root)
    client = client_factory(cfg.comfyui_endpoint)
    cancellation = cancellation_factory(client)
    assembler = assembler_factory(cfg.ffprobe, cfg.ffmpeg) if assembler_factory is FFmpegAssemblyAdapter else assembler_factory()
    extractor = extractor_factory(cfg.ffprobe, cfg.ffmpeg) if extractor_factory is FFmpegVideoAdapter else extractor_factory()
    submitter = ComfyUISubmitTransport(client)
    monitor = lambda ref, **_: client.history(ref)
    class BackendObservationAdapter:
        def observe(self, ref): return client.history(ref)
        def history(self, ref): return client.history(ref)
    backend = BackendObservationAdapter()
    submit_boundary = SubmitBoundary(submitter, repository=repository)
    coordinator = __import__('orquestador.application.chunk_execution', fromlist=['ChunkExecutionCoordinator']).ChunkExecutionCoordinator(
        repository, submit_boundary, monitor, extractor=extractor, trusted_root=cfg.project_root, comfyui_output_root=cfg.comfyui_output_root)
    # Production chain execution must keep the accepted attempt while
    # observing transient queue/history states until terminal evidence.  Keep
    # the plain coordinator for recovery/completion services, and wrap it only
    # at the chain orchestration boundary where bounded polling belongs.
    chain_coordinator = RobustChunkExecutionCoordinator(coordinator)
    resume_real = ResumeExecutionUseCase(repository, backend, coordinator, submit_boundary, cfg.comfyui_output_root)
    recover_real = RecoverExecutionUseCase(repository, backend)
    materializer_real = InputMaterializationService(client, cfg.project_root)
    orchestrator_real = F11_1BOrchestrator(materializer=materializer_real,
        submit_boundary=submit_boundary, recovery=recover_real, resume=resume_real,
        retry=None, robust=chain_coordinator)
    chain_kwargs = {'recovery': resume_real, 'orchestrator': orchestrator_real}
    if 'orchestrator' not in inspect.signature(ChainExecutionUseCase).parameters:
        chain_kwargs.pop('orchestrator')
    chain_real = (ChainExecutionUseCase(repository, chain_coordinator, **chain_kwargs)
        if chain_usecase is None else chain_usecase)
    assembly_roots = (cfg.project_root,) if cfg.comfyui_output_root is None else (cfg.project_root, cfg.comfyui_output_root)
    assembly_real = AssembleExecutionUseCase(
        assembler, cfg.project_root,
        source_roots=assembly_roots)
    retry_real = RetryExecutionUseCase(repository, resume_real)
    chain_usecase = chain_real
    resume_usecase = resume_usecase or resume_real
    recover_usecase = recover_usecase or recover_real
    retry_usecase = retry_usecase or retry_real
    assembly_usecase = assembly_usecase or assembly_real
    def _snapshot_for_repo(repo, project_id=None, execution_id=None):
        if not project_id: return {"state":"unavailable","errors":("select a project",)}
        project, executions = repo.load(project_id)
        matches=[e for e in executions if execution_id is None or str(e.id)==str(execution_id)]
        if len(matches)!=1: return {"project_id":str(project_id),"state":"unavailable","errors":("execution selection is ambiguous or missing",)}
        e=matches[0]; chunks=[]; outputs=[]
        for c in e.chunks:
            a=c.attempts[-1] if c.attempts else None
            transition = c.first_frame
            materialized = getattr(transition, "materialized_ref", None) if transition else None
            transition_uri = "/".join(x for x in (materialized.subfolder, materialized.name) if x) if materialized else (transition.source_output.uri if transition else None)
            chunks.append({"order":c.order,"chunk_id":str(c.id),"state":c.state.value,"attempt_ref":str(a.id) if a else None,"error":a.error.message if a and a.error else None,"output":a.output.uri if a and a.output else None,"transition":transition_uri,"prompt":str(dict(c.defaults).get("prompt", "")),"overrides":tuple((str(k),v) for k,v in dict(c.defaults).items() if k != "prompt")})
            if a and a.output and a.state is Lifecycle.SUCCEEDED: outputs.append(a.output.uri)
        target=select_active_cancellation_target(e)
        retryable = (retry_usecase is not None and e.state is Lifecycle.FAILED and
                     any(c.state is Lifecycle.FAILED and len(c.attempts) == 1 and
                         c.attempts[0].state is Lifecycle.FAILED for c in e.chunks))
        caps=derive_capabilities(e, can_cancel_candidate=(target is not None), retryable=retryable,
            startable=True, assemble=(len(outputs)==len(e.chunks) and len(outputs)>=2))
        snapshot = {"project_id":str(project_id),"execution_id":str(e.id),"state":e.state.value,"chunks":chunks,"artifacts":[a.output.uri for a in e.artifacts],**caps.__dict__,"cancel_reason":"no unique safe pending target" if not caps.can_cancel else ""}
        snapshot["reference_slots"] = tuple(map(str, dict(e.defaults).get("references", ())))
        durable_defaults = dict(e.defaults)
        config_keys = ("profile_ref", "chunk_count", "megapixels", "length", "steps",
                       "fps", "ref_image_size", "also_ref_first_frame",
                       "orchestration_timeout_seconds")
        snapshot["configuration"] = tuple(
            (key, durable_defaults[key]) for key in config_keys if key in durable_defaults
        )
        return snapshot
    def snapshot(project_id=None, execution_id=None):
        # Snapshot reads can be requested from MainWindow's worker thread.
        # Use a short-lived repository there (and on the GUI thread as well)
        # instead of crossing SQLite's thread-affine connection boundary.
        op_repo = repository_factory(cfg.project_root)
        try:
            return _snapshot_for_repo(op_repo, project_id, execution_id)
        finally:
            if op_repo is not repository:
                op_repo.close()
    def cancel(project_id, execution_id):
        s=snapshot(project_id,execution_id)
        if not s["can_cancel"]: raise ValueError(s.get("cancel_reason","cancellation unavailable"))
        op_repo = _operation_repository()
        try:
            _, es=op_repo.load(project_id); e=next(x for x in es if str(x.id)==str(execution_id)); ref=select_active_cancellation_target(e)
        finally: op_repo.close()
        if ref is None: return {**s,"can_cancel":False,"state":"error","errors":("no unique safe pending target",)}
        op_client=client_factory(cfg.comfyui_endpoint); op_cancel=cancellation_factory(op_client)
        result=op_cancel.cancel(ref)
        state=getattr(result.state,'value',str(result.state))
        if state=='confirmed':
            op_repo=_operation_repository()
            try:
                project, es=op_repo.load(project_id); cur=next(x for x in es if str(x.id)==str(execution_id))
                target=select_active_cancellation_target(cur)
                if target is not None and target==ref:
                    chunk=next(c for c in cur.chunks if any(a.external_job_ref==ref for a in c.attempts)); att=next(a for a in chunk.attempts if a.external_job_ref==ref)
                    att.transition(Lifecycle.CANCELLED); chunk.transition(Lifecycle.CANCELLED); cur.transition(Lifecycle.CANCELLED)
                    op_repo.save(project,[cur]); return {**s,"state":"cancelled","can_cancel":False,"message":"cancellation confirmed"}
            except Exception as exc: return {**s,"state":"reconciliation_required","can_cancel":False,"errors":(str(exc),),"message":"backend cancelled; durable reconciliation required"}
            finally: op_repo.close()
        return {**s,"state":("cancellation_requested" if state=='requested' else state),"can_cancel":False,"message":result.issue or state}
    def _operation_repository():
        return repository_factory(cfg.project_root)

    def _worker_services(op_repo):
        # Every operation owns its backend transport and observation adapter;
        # no GUI-thread client is captured by worker execution.
        op_client = client_factory(cfg.comfyui_endpoint)
        op_transport = ComfyUISubmitTransport(op_client)
        op_transport.repository = op_repo
        op_boundary = SubmitBoundary(op_transport)
        op_monitor = lambda ref, **_: op_client.history(ref)
        class OpBackend:
            def observe(self, ref): return op_client.history(ref)
            def history(self, ref): return op_client.history(ref)
        op_backend = OpBackend()
        op_coordinator = ChunkExecutionCoordinator(
            op_repo, op_boundary, op_monitor, extractor=extractor,
            trusted_root=cfg.project_root, comfyui_output_root=cfg.comfyui_output_root)
        op_chain_coordinator = RobustChunkExecutionCoordinator(op_coordinator)
        op_resume = ResumeExecutionUseCase(op_repo, op_backend, op_coordinator, op_boundary, cfg.comfyui_output_root)
        op_recover = RecoverExecutionUseCase(op_repo, op_backend)
        op_retry = RetryExecutionUseCase(op_repo, op_resume)
        op_materializer = InputMaterializationService(op_client, cfg.project_root)
        orchestrator = F11_1BOrchestrator(materializer=op_materializer, submit_boundary=op_boundary,
            recovery=op_recover, resume=op_resume, retry=op_retry, robust=op_chain_coordinator)
        op_chain = ChainExecutionUseCase(op_repo, op_chain_coordinator, recovery=op_resume, orchestrator=orchestrator)
        return op_chain, op_resume, op_recover, op_retry, orchestrator
    def _prepare_operation(**kwargs):
        op_repo = _operation_repository()
        try:
            def op_snapshot(project_id=None, execution_id=None):
                if not project_id: return {"state":"unavailable","errors":("select a project",)}
                project, executions = op_repo.load(project_id)
                matches=[e for e in executions if execution_id is None or str(e.id)==str(execution_id)]
                if len(matches)!=1: return {"project_id":str(project_id),"state":"unavailable","errors":("execution selection is ambiguous or missing",)}
                e=matches[0]
                target = select_active_cancellation_target(e)
                caps = derive_capabilities(
                    e,
                    can_cancel_candidate=(target is not None),
                    retryable=False,
                    startable=True,
                    assemble=False,
                )
                snapshot = {"project_id":str(project_id),"execution_id":str(execution_id),"state":e.state.value,"chunks":[],"artifacts":[],**caps.__dict__}
                snapshot["reference_slots"] = tuple(map(str, dict(e.defaults).get("references", ())))
                return snapshot
            return PrepareGuiUseCase(op_repo, cfg.project_root, op_snapshot)(**kwargs)
        finally:
            op_repo.close()
    def _preflight_operation(**kwargs):
        op_repo = _operation_repository()
        try: return PreflightGuiUseCase(op_repo, cfg.project_root)(**kwargs)
        finally: op_repo.close()
    def preflight(**kwargs):
        result = _preflight_operation(**kwargs)
        # Backend readiness is observed only after all local checks pass.
        try:
            health = client.health()
        except Exception as exc:
            raise RuntimeError(f"backend health check failed: {exc}") from exc
        if health is False or (isinstance(health, dict) and health.get("healthy") is False):
            raise RuntimeError("backend health check reported unhealthy")
        return result

    def _require_output_root():
        """Return the explicit ComfyUI output root or fail before any I/O."""
        if cfg.comfyui_output_root is None:
            raise ValueError("configured ComfyUI output root is required")
        try:
            return validate_configured_output_root(cfg.comfyui_output_root)
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc

    def _run_durable_chain(project_id, execution_id, *, require_output_root=False, **kwargs):
        """Continue a prepared chain from its durable snapshot.

        This is shared by Start and the ID-first Resume/Recover routes.  The
        latter call it only after their fresh capability check, and therefore
        never reconstruct a transient GUI form or create a second recovery
        implementation.
        """
        if chain_usecase is None:
            raise RuntimeError("chain unavailable")
        if require_output_root:
            _require_output_root()
        op_repo = _operation_repository()
        try:
            # Every invocation owns its repository and backend/materialization
            # services.  Nothing SQLite-bound or network-bound from the GUI
            # composition crosses into the operation worker.
            worker = _worker_services(op_repo) if not injected_chain else None
            op_chain = chain_usecase if injected_chain else worker[0]
            if op_chain is None:
                raise RuntimeError("chain unavailable")
            if worker is not None:
                op_materializer = worker[4].materializer
            else:
                op_client = client_factory(cfg.comfyui_endpoint)
                op_materializer = InputMaterializationService(op_client, cfg.project_root)

            def materialize_transition(transition):
                ref = transition.materialized_ref if hasattr(transition, 'materialized_ref') else None
                if ref is not None:
                    return ref
                # The N-1 extractor writes the continuity frame to the
                # project transition namespace, keyed by the successful
                # source attempt.  The video output URI is not that PNG path.
                attempt = getattr(transition, 'source_attempt_id', None)
                attempt_id = getattr(attempt, 'value', attempt)
                if not isinstance(attempt_id, str) or not attempt_id.strip():
                    raise ValueError('transition source attempt is invalid')
                source_path = (cfg.project_root / 'transitions' / f'{attempt_id}.png').resolve()
                if not source_path.is_relative_to(cfg.project_root.resolve()):
                    raise ValueError('transition path escapes project root')
                return op_materializer.materialize_transition(source_path)

            op_start = StartGuiChainUseCase(
                op_repo,
                cfg.project_root,
                op_chain,
                cfg.workflow_template,
                op_materializer,
                materialize_transition,
            )
            return op_start(project_id, execution_id, **kwargs)
        finally:
            op_repo.close()

    def resume_route(project_id, execution_id=None, **kwargs):
        if resume_usecase is None: raise RuntimeError("resume unavailable")
        op_repo = _operation_repository()
        try:
            fresh = _snapshot_for_repo(op_repo, project_id, execution_id)
            if fresh.get("state") in {"error", "unavailable"}:
                raise ValueError("authoritative execution snapshot is missing or invalid")
            if not fresh.get("can_resume", False):
                raise ValueError("no safe resume capability is available")
        finally: op_repo.close()
        # Preserve explicit injected seams used by focused unit tests.  The
        # concrete production path continues all chunks through the existing
        # StartGuiChainUseCase -> ChainExecutionUseCase orchestration.
        if injected_resume:
            return resume_usecase.resume(project_id, execution_id, **kwargs)
        return _run_durable_chain(project_id, execution_id, require_output_root=True)

    def recover_route(project_id, execution_id=None, **_):
        if recover_usecase is None: raise RuntimeError("recover unavailable")
        op_repo = _operation_repository()
        try:
            fresh = _snapshot_for_repo(op_repo, project_id, execution_id)
            if fresh.get("state") in {"error", "unavailable"}:
                raise ValueError("authoritative execution snapshot is missing or invalid")
            if not fresh.get("can_recover", False):
                raise ValueError("no safe recover capability is available")
        finally: op_repo.close()
        if injected_recover:
            return recover_usecase.recover(project_id, execution_id)
        return _run_durable_chain(project_id, execution_id, require_output_root=True)

    def retry_route(project_id, execution_id=None, **kwargs):
        if retry_usecase is None: raise RuntimeError("retry unavailable")
        op_repo = _operation_repository()
        try:
            if injected_retry: return retry_usecase.retry(project_id, execution_id, **kwargs)
            return _worker_services(op_repo)[4].retry(project_id, execution_id, **kwargs)
        finally: op_repo.close()
    def assemble_route(project_id, execution_id=None, destination=None, **_):
        op_repo = _operation_repository()
        try:
            project, executions = op_repo.load(project_id); e=next(x for x in executions if str(x.id)==str(execution_id))
            outputs=[AssemblySource(a.output.uri, AssemblySourceRoot.PROJECT_DURABLE)
                     for c in e.chunks for a in reversed(c.attempts)
                     if a.output and a.state is Lifecycle.SUCCEEDED]
            return assembly_usecase.execute(outputs, destination or f"assembled-{e.id}.mp4")
        finally: op_repo.close()
    # Keep the composition route as a thin closure; all validation/binding remains
    # owned by the application-layer use case.  Start and ID-first recovery use
    # the same durable chain path; only the latter require an explicit output
    # trust root before any recovery I/O.
    def start_chain(project_id, execution_id, **kwargs):
        return _run_durable_chain(project_id, execution_id, **kwargs)
    from ..application.edit_chunk_sequence import EditChunkSequenceUseCase
    sequence_edit = EditChunkSequenceUseCase(repository_factory=lambda: repository_factory(cfg.project_root))
    facade = GuiFacade(prepare=_prepare_operation, preflight=preflight, retry=retry_route, chain=start_chain,
                       resume=resume_route, recover=recover_route, assemble=assemble_route,
                       cancel=cancel, snapshot=snapshot, sequence_edit=sequence_edit)
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
    app.setOrganizationName("OrquestadorComfyUI")
    app.setApplicationName("Orquestador")
    facade, resources = compose(config)
    window = MainWindow(facade, config.project_root); window.show()
    try:
        return int(app.exec())
    finally:
        resources["repository"].close()

def main(argv: Sequence[str] | None = None) -> int:
    return launch(parse_config(argv))
