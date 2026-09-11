import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from orquestador.application.gui_facade import (
    ChunkSnapshot,
    ExecutionSnapshot,
    GuiFacade,
    OperationResult,
)
from orquestador.application.chunk_execution import ChunkExecutionCoordinator
from orquestador.application.recover_execution import (
    RecoveryOutcome,
    ResumeExecutionUseCase,
)
from orquestador.application.submit_boundary import SubmitBoundary
from orquestador.adapters.http import HistoryResult, HistoryState
from orquestador.adapters.outputs import (
    OutputCorrelationResult,
    OutputCorrelationStatus,
    OutputDescriptor,
)
from orquestador.adapters.physical_outputs import (
    PhysicalOutputEvidence,
    PhysicalOutputStatus,
)
from orquestador.domain import (
    Artifact,
    BackendJobRef,
    Chunk,
    Evidence,
    Execution,
    Lifecycle,
    OutputRef,
    Phase,
    Project,
    TransitionFrame,
    WorkflowProfileRef,
)
from orquestador.persistence.sqlite import SQLiteProjectRepository
from orquestador.profiles.minimax_h3 import H3_PROFILE
from orquestador.ui.app import AppConfig, compose

class F115OperationsTests(unittest.TestCase):
    def test_reopen_snapshot_exposes_chunk_transition_and_artifacts(self):
        facade = GuiFacade(snapshot=lambda *_: {"project_id":"p","execution_id":"e","state":"running","chunks":[{"order":0,"state":"succeeded","output":"chunks/0.mp4","transition":"transitions/0.png"}],"artifacts":["chunks/0.mp4"],"can_resume":True,"can_recover":True})
        snap = facade.refresh("p", "e")
        self.assertEqual(snap.chunks[0].transition, "transitions/0.png")
        self.assertTrue(snap.can_resume and snap.can_recover)

    def test_cancel_is_fail_closed_with_actionable_reason(self):
        facade = GuiFacade(snapshot=lambda *_: {"project_id":"p","execution_id":"e","state":"running","cancel_reason":"no unique safe pending target"})
        result = facade.cancel_pending("p", "e")
        self.assertFalse(result.success)
        self.assertIn("no unique safe pending", result.message)

    def test_retry_and_assembly_are_gated_by_durable_capabilities(self):
        facade = GuiFacade(snapshot=lambda *_: {"state":"failed","can_retry":False,"can_assemble":False})
        snap = facade.refresh("p", "e")
        self.assertFalse(snap.can_retry or snap.can_assemble)

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_mainwindow_reopen_is_id_first_and_selects_fresh_capability(self):
        from orquestador.ui.main_window import MainWindow

        calls = []
        resume_snapshot = ExecutionSnapshot(
            "p", "e", "running", can_resume=True,
            chunks=(ChunkSnapshot(0, "pending", chunk_id="c0"),),
        )

        class FakeFacade:
            def refresh(self, project_id=None, execution_id=None):
                calls.append(("refresh", project_id, execution_id))
                return resume_snapshot if project_id else ExecutionSnapshot()

            def resume_execution(self, *args, **kwargs):
                calls.append(("resume", args, kwargs))
                return OperationResult(True, resume_snapshot, "resumed")

            def recover_execution(self, *args, **kwargs):
                calls.append(("recover", args, kwargs))
                return OperationResult(True, resume_snapshot, "recovered")

        window = MainWindow(FakeFacade())
        self.addCleanup(window.close)
        window.project.setText("p")
        window.execution.setText("e")
        # Deliberately populate transient form fields.  Reopen must not read
        # or forward any of them, and must not invoke Prepare/Preflight.
        window.initial.setText("not-a-durable-path")
        window.prompts[0].setPlainText("new GUI prompt")
        window._run = lambda operation, *_args, **_kwargs: setattr(window, "_reopen_result", operation())
        calls.clear()
        window._resume_or_recover()
        self.assertEqual(calls, [
            ("refresh", "p", "e"),
            ("resume", ("p", "e"), {}),
        ])
        self.assertTrue(window._reopen_result.success)

    def test_mainwindow_reopen_uses_recover_only_when_resume_is_unavailable(self):
        from orquestador.ui.main_window import MainWindow

        calls = []
        snapshot = ExecutionSnapshot("p", "e", "running", can_recover=True)

        class FakeFacade:
            def refresh(self, project_id=None, execution_id=None):
                if project_id:
                    calls.append(("refresh", project_id, execution_id))
                    return snapshot
                return ExecutionSnapshot()

            def resume_execution(self, *args, **kwargs):
                calls.append(("resume", args, kwargs))
                return OperationResult(False, snapshot, "must not resume")

            def recover_execution(self, *args, **kwargs):
                calls.append(("recover", args, kwargs))
                return OperationResult(True, snapshot, "recovered")

        window = MainWindow(FakeFacade())
        self.addCleanup(window.close)
        window.project.setText("p")
        window.execution.setText("e")
        window._run = lambda operation, *_args, **_kwargs: setattr(window, "_reopen_result", operation())
        window._resume_or_recover()
        self.assertEqual(calls, [
            ("refresh", "p", "e"),
            ("recover", ("p", "e"), {}),
        ])
        self.assertTrue(window._reopen_result.success)

    def test_mainwindow_reopen_without_authorized_capability_fails_closed(self):
        from orquestador.ui.main_window import MainWindow

        snapshot = ExecutionSnapshot("p", "e", "succeeded")
        calls = []

        class FakeFacade:
            def refresh(self, project_id=None, execution_id=None):
                if project_id:
                    calls.append(("refresh", project_id, execution_id))
                    return snapshot
                return ExecutionSnapshot()

            def resume_execution(self, *args, **kwargs):
                calls.append(("resume", args, kwargs))
                raise AssertionError("resume must be gated")

            def recover_execution(self, *args, **kwargs):
                calls.append(("recover", args, kwargs))
                raise AssertionError("recover must be gated")

        window = MainWindow(FakeFacade())
        self.addCleanup(window.close)
        window.project.setText("p")
        window.execution.setText("e")
        window._run = lambda operation, *_args, **_kwargs: setattr(window, "_reopen_result", operation())
        window._resume_or_recover()
        self.assertFalse(window._reopen_result.success)
        self.assertIn("no safe resume/recover", window._reopen_result.message)
        self.assertEqual(calls, [("refresh", "p", "e")])

    def test_mainwindow_resume_visual_gate_uses_ids_and_busy_not_snapshot(self):
        from orquestador.ui.main_window import MainWindow

        calls = []
        mode = {"authorized": True}
        unavailable = ExecutionSnapshot()
        authorized = ExecutionSnapshot(
            "p", "e", "running", can_resume=True,
        )
        blocked = ExecutionSnapshot("p", "e", "succeeded")

        class FakeFacade:
            def refresh(self, project_id=None, execution_id=None):
                calls.append(("refresh", project_id, execution_id))
                if project_id == "p" and execution_id == "e":
                    return authorized if mode["authorized"] else blocked
                return unavailable

            def resume_execution(self, *args, **kwargs):
                calls.append(("resume", args, kwargs))
                return OperationResult(True, authorized, "resumed")

            def recover_execution(self, *args, **kwargs):
                calls.append(("recover", args, kwargs))
                return OperationResult(True, authorized, "recovered")

        window = MainWindow(FakeFacade())
        self.addCleanup(window.close)
        self.assertFalse(window.resume.isEnabled())

        window.project.setText("p")
        self.assertFalse(window.resume.isEnabled())
        window.execution.setText("e")
        # The previous snapshot is still unavailable; IDs are the visual gate.
        self.assertEqual(window._last_snapshot.state, "unavailable")
        self.assertTrue(window.resume.isEnabled())

        def synchronous_run(operation, *_args, **_kwargs):
            window._busy = True
            window._set_enabled(False)
            try:
                window._reopen_result = operation()
                return window._reopen_result
            finally:
                window._busy = False
                window._set_enabled(True)

        window._run = synchronous_run
        calls.clear()
        window._resume_or_recover()
        self.assertEqual(calls, [
            ("refresh", "p", "e"),
            ("resume", ("p", "e"), {}),
        ])
        self.assertTrue(window._reopen_result.success)

        window._busy = True
        window._update_resume_recover()
        self.assertFalse(window.resume.isEnabled())
        window._busy = False
        window._update_resume_recover()
        self.assertTrue(window.resume.isEnabled())

        window.render(unavailable)
        self.assertTrue(window.resume.isEnabled())

        mode["authorized"] = False
        calls.clear()
        window._resume_or_recover()
        self.assertFalse(window._reopen_result.success)
        self.assertIn("no safe resume/recover", window._reopen_result.message)
        self.assertEqual(calls, [("refresh", "p", "e")])

        window.project.clear()
        self.assertFalse(window.resume.isEnabled())
        window.project.setText("p")
        self.assertTrue(window.resume.isEnabled())
        window.execution.setText("e")
        self.assertTrue(window.resume.isEnabled())
        window.execution.clear()
        self.assertFalse(window.resume.isEnabled())

    def _temp_root(self):
        base = Path(os.environ.get("ORQ_TEST_TMP", tempfile.gettempdir())).resolve()
        base.mkdir(parents=True, exist_ok=True)
        holder = tempfile.TemporaryDirectory(dir=base)
        root = Path(holder.name)
        self.addCleanup(holder.cleanup)
        return root

    def _durable_running_two_chunk(self, root, output_root, db_name="f11_5.sqlite3"):
        (root / "inputs").mkdir()
        (root / "inputs" / "initial.png").write_bytes(b"initial")
        project = Project()
        execution = Execution(
            project.id,
            defaults={
                "config_version": 1,
                "profile_ref": H3_PROFILE.name,
                "initial_image": "inputs/initial.png",
                "references": [],
                "chunk_count": 2,
                "prompts": ["chunk one", "chunk two"],
                "megapixels": 0.6,
                "length": 294,
                "steps": 20,
                "fps": 24,
                "ref_image_size": "match",
                "also_ref_first_frame": False,
                "orchestration_timeout_seconds": 1800,
            },
            workflow_profile_ref=WorkflowProfileRef(H3_PROFILE.name),
        )
        execution.add_chunk(Chunk(order=0, defaults={"prompt": "chunk one"}))
        execution.add_chunk(Chunk(order=1, defaults={"prompt": "chunk two"}))
        execution.transition(Lifecycle.RUNNING)
        first = execution.chunks[0]
        attempt = first.new_attempt()
        attempt.assign_external_job_ref(BackendJobRef("existing-job"))
        repo = SQLiteProjectRepository(root, db_name)
        repo.save(project, [execution])
        self.addCleanup(repo.close)
        return project, execution, repo

    def test_completed_external_ref_imports_artifact_and_n_minus_one_without_submit(self):
        root = self._temp_root()
        output_root = root / "comfy-output"
        (output_root / "video").mkdir(parents=True)
        (output_root / "video" / "existing.mp4").write_bytes(b"mp4")
        project, execution, repo = self._durable_running_two_chunk(root, output_root)
        chunk = execution.chunks[0]
        attempt = chunk.attempts[0]
        ref = attempt.external_job_ref
        descriptor = OutputDescriptor(ref, "92", "existing.mp4", "video", "output")
        history = HistoryResult(ref, HistoryState.SUCCEEDED, {
            "outputs": {"92": {"images": [{
                "filename": "existing.mp4", "subfolder": "video", "type": "output",
            }]}}
        })
        backend = Mock()
        backend.observe.return_value = history
        submitter = Mock()
        correlation = OutputCorrelationResult(ref, OutputCorrelationStatus.VALID, (descriptor,))
        physical = PhysicalOutputEvidence(
            descriptor, PhysicalOutputStatus.EXISTS, output_root,
            output_root / "video" / "existing.mp4",
        )

        class Extractor:
            def extract_last_frame(self, source, destination):
                destination = Path(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"frame")
                return type("Frame", (), {"frame_index": 9, "frame_count": 10})()

        coordinator = ChunkExecutionCoordinator(
            repo, SubmitBoundary(submitter, repository=repo), backend,
            extractor=Extractor(), trusted_root=root,
            comfyui_output_root=output_root,
            correlator=lambda *_: correlation,
            physical_validator=lambda *_: physical,
        )
        result = ResumeExecutionUseCase(
            repo, backend, coordinator, coordinator.submit_boundary, output_root,
        ).resume(project.id, execution.id)
        self.assertEqual(result.outcome, RecoveryOutcome.COMPLETE)
        submitter.submit.assert_not_called()
        loaded_project, executions = repo.load(project.id)
        loaded = executions[0]
        loaded_chunk = loaded.chunks[0]
        loaded_attempt = loaded_chunk.attempts[0]
        self.assertEqual(loaded_chunk.state, Lifecycle.SUCCEEDED)
        self.assertEqual(loaded_attempt.state, Lifecycle.SUCCEEDED)
        self.assertEqual(loaded_attempt.output, OutputRef("video/existing.mp4"))
        self.assertTrue((root / "video" / "existing.mp4").is_file())
        self.assertEqual(len(loaded.artifacts), 1)
        self.assertEqual(loaded.artifacts[0].phase, Phase.OUTPUT)
        transitions = repo.load_transitions(loaded.id)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0].source_frame_index, transitions[0].frame_count - 1)
        self.assertEqual(transitions[0].source_output, loaded_attempt.output)

    def test_missing_output_root_fails_closed_before_backend_or_submit(self):
        root = self._temp_root()
        project, execution, repo = self._durable_running_two_chunk(root, root / "missing-output")
        backend = Mock()
        submitter = Mock()
        coordinator = ChunkExecutionCoordinator(
            repo, SubmitBoundary(submitter, repository=repo), backend,
            extractor=Mock(), trusted_root=root, comfyui_output_root=None,
        )
        result = ResumeExecutionUseCase(
            repo, backend, coordinator, coordinator.submit_boundary, None,
        ).resume(project.id, execution.id)
        self.assertEqual(result.outcome, RecoveryOutcome.NEEDS_MANUAL_REVIEW)
        self.assertIn("output root is required", result.reason)
        backend.observe.assert_not_called()
        submitter.submit.assert_not_called()

    def test_resume_route_uses_fresh_durable_snapshot_and_injected_resume(self):
        root = self._temp_root()
        output_root = root / "comfy-output"
        output_root.mkdir()
        project = Project()
        execution = Execution(project.id)
        execution.add_chunk(Chunk(order=0))
        execution.add_chunk(Chunk(order=1))
        execution.transition(Lifecycle.RUNNING)
        execution.chunks[0].transition(Lifecycle.RUNNING)
        attempt = execution.chunks[0].new_attempt()
        attempt.assign_external_job_ref(BackendJobRef("durable-ref"))
        attempt.transition(Lifecycle.RUNNING)
        # compose() opens the canonical durable database name.
        repo = SQLiteProjectRepository(root)
        repo.save(project, [execution])
        self.addCleanup(repo.close)

        calls = []

        class Resume:
            def resume(self, project_id, execution_id, **kwargs):
                calls.append(("resume", project_id, execution_id, kwargs))
                return type("Result", (), {"outcome": RecoveryOutcome.WAIT, "execution_id": str(execution_id)})()

        class Client:
            def __init__(self, endpoint):
                calls.append(("client", endpoint))

            def history(self, ref):
                raise AssertionError("route must not observe when injected resume is selected")

            def upload_image(self, *args, **kwargs):
                raise AssertionError("route must not materialize GUI inputs")

        facade, resources = compose(
            AppConfig(root, comfyui_output_root=output_root),
            client_factory=Client,
            resume_usecase=Resume(),
        )
        self.addCleanup(resources["repository"].close)
        result = facade.resume_execution(project.id, execution.id)
        self.assertFalse(result.success)  # WAIT is intentionally not completion.
        self.assertEqual(calls, [("client", "http://127.0.0.1:8188"),
                                 ("resume", project.id, execution.id, {})])

    def test_id_first_recovery_completes_chunk_one_then_submits_chunk_two_once(self):
        root = self._temp_root()
        output_root = root / "comfy-output"
        (output_root / "video").mkdir(parents=True)
        (output_root / "video" / "existing-job.mp4").write_bytes(b"chunk-one")
        project, execution, repo = self._durable_running_two_chunk(
            root, output_root, db_name="orquestador.sqlite3",
        )
        repo.close()

        class Client:
            submits = []
            histories = []

            def __init__(self, endpoint):
                self.endpoint = endpoint

            def upload_image(self, path, *, subfolder="", overwrite=False, requested_filename=None):
                return {
                    "type": "input",
                    "name": requested_filename or Path(path).name,
                    "subfolder": subfolder,
                }

            def submit(self, prompt, client_id=None):
                ref = BackendJobRef(f"chunk-two-{len(self.submits) + 1}")
                self.submits.append((ref, prompt))
                target = output_root / "video" / f"{ref.value}.mp4"
                target.write_bytes(b"chunk-two")
                return ref

            def history(self, ref):
                self.histories.append(ref)
                filename = "existing-job.mp4" if ref == BackendJobRef("existing-job") else f"{ref.value}.mp4"
                return HistoryResult(ref, HistoryState.SUCCEEDED, {
                    "outputs": {"92": {"images": [{
                        "filename": filename,
                        "subfolder": "video",
                        "type": "output",
                    }]}}
                })

        class Extractor:
            def extract_last_frame(self, source, destination):
                destination = Path(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"n-minus-one")
                return type("Frame", (), {"frame_index": 4, "frame_count": 5})()

        facade, resources = compose(
            AppConfig(root, comfyui_output_root=output_root),
            client_factory=lambda endpoint: Client(endpoint),
            extractor_factory=lambda: Extractor(),
        )
        self.addCleanup(resources["repository"].close)
        result = facade.resume_execution(project.id, execution.id)
        self.assertTrue(result.success, result.message)
        self.assertEqual(result.snapshot.state, "succeeded")
        self.assertEqual(len(result.snapshot.chunks), 2)
        self.assertEqual(dict(result.snapshot.configuration)["megapixels"], 0.6)
        self.assertEqual(len(Client.submits), 1)
        self.assertEqual(Client.submits[0][0], BackendJobRef("chunk-two-1"))
        self.assertEqual(Client.histories.count(BackendJobRef("existing-job")), 1)
        self.assertEqual(
            len([ref for ref, _ in Client.submits if ref == BackendJobRef("existing-job")]),
            0,
        )
        _, executions = resources["repository"].load(project.id)
        durable = executions[0]
        self.assertEqual(durable.state, Lifecycle.SUCCEEDED)
        self.assertTrue(all(c.state is Lifecycle.SUCCEEDED for c in durable.chunks))
        self.assertEqual(len(durable.chunks[0].attempts), 1)
        self.assertEqual(len(durable.chunks[1].attempts), 1)
        self.assertEqual(len(resources["repository"].load_transitions(execution.id)), 2)

    def test_compose_does_not_fallback_output_root_to_project_root(self):
        root = self._temp_root()
        facade, resources = compose(AppConfig(root), client_factory=lambda _: Mock())
        self.addCleanup(resources["repository"].close)
        self.assertIsNone(resources["coordinator"].comfyui_output_root)
        project = Project()
        execution = Execution(project.id)
        execution.add_chunk(Chunk(order=0))
        execution.add_chunk(Chunk(order=1))
        execution.transition(Lifecycle.RUNNING)
        execution.chunks[0].transition(Lifecycle.RUNNING)
        attempt = execution.chunks[0].new_attempt()
        attempt.assign_external_job_ref(BackendJobRef("root-fallback-must-not-be-used"))
        attempt.transition(Lifecycle.RUNNING)
        resources["repository"].save(project, [execution])
        result, error = resources["coordinator"].submit_new(
            project, execution, execution.chunks[0].id, {},
        )
        self.assertIsNone(result)
        self.assertIn("output root is required", error)

    def test_resume_route_missing_output_root_fails_before_materialization_or_submit(self):
        root = self._temp_root()
        project, execution, repo = self._durable_running_two_chunk(
            root, root / "missing-output", db_name="orquestador.sqlite3",
        )
        repo.close()
        calls = []

        class Client:
            def __init__(self, endpoint):
                calls.append(("client", endpoint))

            def upload_image(self, *args, **kwargs):
                calls.append(("upload", args, kwargs))
                raise AssertionError("materialization must not start")

            def submit(self, *args, **kwargs):
                calls.append(("submit", args, kwargs))
                raise AssertionError("submit must not start")

            def history(self, *args, **kwargs):
                calls.append(("history", args, kwargs))
                raise AssertionError("backend observation must not start")

        facade, resources = compose(
            AppConfig(root),
            client_factory=Client,
            extractor_factory=lambda: Mock(),
        )
        self.addCleanup(resources["repository"].close)
        result = facade.resume_execution(project.id, execution.id)
        self.assertFalse(result.success)
        self.assertIn("output root is required", result.message)
        self.assertEqual(calls, [("client", "http://127.0.0.1:8188")])


if __name__ == "__main__":
    unittest.main()
