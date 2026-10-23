import hashlib
import os
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from orquestador.application.gui_facade import ChunkSnapshot, ExecutionSnapshot, LibraryOperationResult
from orquestador.application.results import ExecutionResultsResolver, OutputResolution
from orquestador.domain.core import (
    Artifact,
    AssemblyAttempt,
    AssemblySourceEvidence,
    AssemblyState,
    Chunk,
    ErrorRecord,
    Evidence,
    Execution,
    Lifecycle,
    OutputRef,
    Phase,
    Project,
    ProjectId,
    TransitionFrame,
)
from orquestador.persistence.sqlite import SQLiteProjectRepository


def _mp4_bytes(marker=0):
    # A minimal ISO-BMFF ftyp box. The minor version distinguishes fixtures.
    return (24).to_bytes(4, "big") + b"ftypisom" + int(marker).to_bytes(4, "big") + b"isomiso2"


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _persist_successful_execution(repository, project, execution, artifacts, transitions):
    attempt = execution.latest_assembly_attempt()
    expected_sha = attempt.expected_sha256
    signature = attempt.probe_signature
    execution.state = Lifecycle.RUNNING
    attempt.state = AssemblyState.PENDING
    attempt.expected_sha256 = None
    attempt.probe_signature = None
    repository.save(project, [execution], artifacts=artifacts, transitions=transitions)
    attempt.transition(AssemblyState.ASSEMBLING)
    repository.save(project, [execution], artifacts=artifacts)
    attempt.record_staged_output(expected_sha, signature)
    repository.save(project, [execution], artifacts=artifacts)
    attempt.transition(AssemblyState.SUCCEEDED)
    execution.transition(Lifecycle.SUCCEEDED)
    repository.save(project, [execution], artifacts=artifacts)


def _build_execution(project_root, *, final=True):
    project = Project(ProjectId("project"), name="Proyecto de prueba")
    execution = Execution(project.id)
    execution.transition(Lifecycle.RUNNING)
    artifacts = []
    transitions = []
    sources = []
    for order in range(2):
        chunk = Chunk(order=order)
        execution.add_chunk(chunk)
        chunk.transition(Lifecycle.RUNNING)
        attempt = chunk.new_attempt()
        attempt.transition(Lifecycle.RUNNING)
        output = OutputRef(f"video/chunk-{order}.mp4")
        path = Path(project_root) / output.uri
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_mp4_bytes(order + 1))
        attempt.transition(
            Lifecycle.SUCCEEDED,
            output=output,
            evidence=Evidence("correlated, imported and decoded output"),
        )
        chunk.transition(Lifecycle.SUCCEEDED)
        artifact = Artifact(project.id, execution.id, chunk.id, attempt.id, Phase.OUTPUT, output)
        artifacts.append(artifact)
        sources.append(
            AssemblySourceEvidence(order, chunk.id, attempt.id, artifact.id, output.uri, _sha256(path))
        )
    execution.artifacts.extend(artifacts)
    transition = TransitionFrame(
        project.id,
        execution.id,
        execution.chunks[0].id,
        execution.chunks[0].attempts[0].id,
        execution.chunks[0].attempts[0].output,
        0,
        1,
        execution.chunks[1].id,
    )
    execution.link_transition(execution.chunks[1], transition)
    transitions.append(transition)
    if final:
        destination_uri = f"assembled-{execution.id}.mp4"
        destination = Path(project_root) / destination_uri
        final_bytes = _mp4_bytes(9)
        destination.write_bytes(final_bytes)
        execution.assembly_attempts.append(
            AssemblyAttempt(
                execution.id,
                1,
                AssemblyState.SUCCEEDED,
                destination_uri,
                f".orquestador-assembly/{execution.id}/attempt-1.mp4",
                tuple(sources),
                hashlib.sha256(final_bytes).hexdigest(),
                ("synthetic", "h264"),
            )
        )
        execution.transition(Lifecycle.SUCCEEDED)
    return project, execution, tuple(artifacts), tuple(transitions)


class ExecutionResultsResolverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.project_root = self.root / "project"
        self.comfy_root = self.root / "comfy-output"
        self.project_root.mkdir()
        self.comfy_root.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def make_execution(self, *, final=True):
        return _build_execution(self.project_root, final=final)

    def resolve(self, execution, *, project_root=None, comfy_root=None):
        return ExecutionResultsResolver(
            project_root or self.project_root,
            self.comfy_root if comfy_root is None else comfy_root,
        ).resolve(execution)

    def test_final_and_each_chunk_require_current_successful_evidence(self):
        _project, execution, _artifacts, _transitions = self.make_execution()
        resolved = self.resolve(execution)
        self.assertTrue(resolved.final.available)
        self.assertEqual(Path(resolved.final.path), self.project_root / execution.assembly_attempts[0].destination_uri)
        self.assertEqual(len(resolved.chunks), 2)
        self.assertTrue(all(item.available for item in resolved.chunks))
        self.assertEqual([item.attempt_number for item in resolved.chunks], [1, 1])

    def test_partial_execution_exposes_available_chunks_without_a_final_video(self):
        _project, execution, _artifacts, _transitions = self.make_execution(final=False)
        resolved = self.resolve(execution)
        self.assertEqual(resolved.final.status, "no_evidence")
        self.assertIsNone(resolved.final.path)
        self.assertTrue(all(item.available for item in resolved.chunks))

    def test_later_failed_attempt_does_not_replace_a_previous_successful_chunk(self):
        _project, execution, _artifacts, _transitions = self.make_execution(final=False)
        chunk = execution.chunks[0]
        failed = chunk.new_attempt()
        failed.transition(Lifecycle.RUNNING)
        failed.transition(Lifecycle.FAILED, error=ErrorRecord("retry", "retry failed"))
        chunk.state = Lifecycle.FAILED
        execution.state = Lifecycle.FAILED

        resolved = self.resolve(execution)
        self.assertTrue(resolved.chunks[0].available)
        self.assertEqual(resolved.chunks[0].attempt_number, 1)
        self.assertEqual(Path(resolved.chunks[0].path), self.project_root / "video" / "chunk-0.mp4")

    def test_project_artifact_origin_wins_over_same_relative_name_in_comfy_output(self):
        _project, execution, _artifacts, _transitions = self.make_execution(final=False)
        duplicate = self.comfy_root / "video" / "chunk-0.mp4"
        duplicate.parent.mkdir()
        duplicate.write_bytes(_mp4_bytes(50))

        resolved = self.resolve(execution)
        self.assertTrue(resolved.chunks[0].available)
        self.assertEqual(Path(resolved.chunks[0].path), self.project_root / "video" / "chunk-0.mp4")

    def test_missing_empty_and_invalid_mp4_outputs_are_disabled(self):
        _project, execution, _artifacts, _transitions = self.make_execution(final=False)
        chunk_path = self.project_root / "video" / "chunk-0.mp4"
        chunk_path.unlink()
        self.assertEqual(self.resolve(execution).chunks[0].status, "missing")

        chunk_path.write_bytes(b"")
        self.assertEqual(self.resolve(execution).chunks[0].status, "empty")

        chunk_path.write_bytes(b"not an mp4 container")
        self.assertEqual(self.resolve(execution).chunks[0].status, "invalid")

    def test_truncated_extended_mp4_header_is_invalid(self):
        _project, execution, _artifacts, _transitions = self.make_execution(final=False)
        chunk_path = self.project_root / "video" / "chunk-0.mp4"
        chunk_path.write_bytes((1).to_bytes(4, "big") + b"ftyp" + (64).to_bytes(8, "big"))
        self.assertEqual(self.resolve(execution).chunks[0].status, "invalid")

    def test_final_file_must_match_assembly_hash(self):
        _project, execution, _artifacts, _transitions = self.make_execution()
        final_path = self.project_root / execution.assembly_attempts[0].destination_uri
        final_path.write_bytes(_mp4_bytes(10))
        resolved = self.resolve(execution)
        self.assertEqual(resolved.final.status, "integrity_error")
        self.assertIsNone(resolved.final.path)

    def test_relative_traversal_and_absolute_escape_are_rejected(self):
        _project, execution, _artifacts, _transitions = self.make_execution(final=False)
        attempt = execution.chunks[0].attempts[0]
        attempt.output = OutputRef("../outside.mp4")
        artifact = execution.artifacts[0]
        execution.artifacts[0] = Artifact(
            artifact.project_id, artifact.execution_id, artifact.chunk_id,
            artifact.attempt_id, artifact.phase, attempt.output, artifact.id,
        )
        self.assertEqual(self.resolve(execution).chunks[0].status, "invalid")

        external = self.root / "outside.mp4"
        external.write_bytes(_mp4_bytes())
        attempt.output = OutputRef(str(external))
        artifact = execution.artifacts[0]
        execution.artifacts[0] = Artifact(
            artifact.project_id, artifact.execution_id, artifact.chunk_id,
            artifact.attempt_id, artifact.phase, attempt.output, artifact.id,
        )
        self.assertEqual(self.resolve(execution).chunks[0].status, "invalid")

    def test_symlink_escape_is_rejected_when_windows_allows_symlink_creation(self):
        _project, execution, _artifacts, _transitions = self.make_execution(final=False)
        chunk_path = self.project_root / "video" / "chunk-0.mp4"
        chunk_path.unlink()
        external = self.root / "external.mp4"
        external.write_bytes(_mp4_bytes())
        try:
            chunk_path.symlink_to(external)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        self.assertEqual(self.resolve(execution).chunks[0].status, "invalid")

    def test_absolute_result_inside_overlapping_roots_fails_closed(self):
        parent = self.root / "overlap"
        project_root = parent / "project"
        project_root.mkdir(parents=True)
        comfy_root = parent
        output = project_root / "video" / "chunk.mp4"
        output.parent.mkdir()
        output.write_bytes(_mp4_bytes())
        project = Project(ProjectId("overlap-project"), name="Overlap")
        execution = Execution(project.id)
        chunk = Chunk(order=0)
        execution.add_chunk(chunk)
        chunk.transition(Lifecycle.RUNNING)
        attempt = chunk.new_attempt()
        attempt.transition(Lifecycle.RUNNING)
        ref = OutputRef(str(output))
        attempt.transition(Lifecycle.SUCCEEDED, output=ref, evidence=Evidence("verified"))
        chunk.transition(Lifecycle.SUCCEEDED)
        execution.artifacts.append(Artifact(project.id, execution.id, chunk.id, attempt.id, Phase.OUTPUT, ref))

        result = ExecutionResultsResolver(project_root, comfy_root).resolve(execution)
        self.assertEqual(result.chunks[0].status, "ambiguous")
        self.assertIsNone(result.chunks[0].path)

    def test_reopened_historical_execution_retains_durable_result_access(self):
        project, execution, artifacts, transitions = self.make_execution()
        repo = SQLiteProjectRepository(self.project_root)
        _persist_successful_execution(repo, project, execution, artifacts, transitions)
        repo.close()

        reopened = SQLiteProjectRepository(self.project_root)
        try:
            _loaded_project, executions = reopened.load(project.id)
        finally:
            reopened.close()
        result = self.resolve(executions[0])
        self.assertTrue(result.final.available)
        self.assertTrue(all(item.available for item in result.chunks))


class MainWindowResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self):
        from orquestador.ui.main_window import MainWindow

        class EmptyFacade:
            def refresh(self, *_args):
                return ExecutionSnapshot(state="unavailable")

        return MainWindow(EmptyFacade())

    def snapshot(self, final_path, chunk_path, *, project_id="p", execution_id="e"):
        return ExecutionSnapshot(
            project_id,
            execution_id,
            "succeeded",
            chunks=(ChunkSnapshot(
                0,
                "succeeded",
                chunk_id="chunk-1",
                resolved_output=OutputResolution("available", str(chunk_path), attempt_number=1),
            ),),
            final_result=OutputResolution("available", str(final_path), attempt_number=1),
        )

    def wait_for_window_worker(self, window, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and (window._busy or window._thread is not None):
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        self.assertFalse(window._busy)
        self.assertIsNone(window._thread)

    def test_results_actions_use_qt_windows_handlers_and_do_not_modify_originals(self):
        from orquestador.ui import main_window

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            final_path = root / "assembled.mp4"
            chunk_path = root / "chunk.mp4"
            final_path.write_bytes(_mp4_bytes(1))
            chunk_path.write_bytes(_mp4_bytes(2))
            before = (_sha256(final_path), _sha256(chunk_path))
            window = self.make_window()
            self.addCleanup(window.close)
            window.render(self.snapshot(final_path, chunk_path))

            self.assertTrue(window.open_final_result.isEnabled())
            self.assertTrue(window.show_final_result_in_folder.isEnabled())
            chunk_button = window.chunks.itemWidget(window.chunks.item(0)).findChild(
                QPushButton, "chunkOpenButton1"
            )
            self.assertTrue(chunk_button.isEnabled())
            with patch.object(main_window.QDesktopServices, "openUrl", return_value=True) as open_url, \
                    patch.object(main_window.QProcess, "startDetached", return_value=(True, 123)) as start_detached:
                window.open_final_result.click()
                chunk_button.click()
                window.show_final_result_in_folder.click()
            self.assertEqual(open_url.call_count, 2)
            self.assertEqual(Path(open_url.call_args_list[0].args[0].toLocalFile()), final_path)
            self.assertEqual(Path(open_url.call_args_list[1].args[0].toLocalFile()), chunk_path)
            self.assertEqual(start_detached.call_args.args[0], "explorer.exe")
            self.assertEqual(start_detached.call_args.args[1], [f"/select,{final_path}"])
            self.assertEqual((_sha256(final_path), _sha256(chunk_path)), before)

    def test_opening_next_project_clears_old_result_routes_before_loading(self):
        from orquestador.ui import main_window

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            final_path = root / "assembled.mp4"
            chunk_path = root / "chunk.mp4"
            final_path.write_bytes(_mp4_bytes(1))
            chunk_path.write_bytes(_mp4_bytes(2))
            window = self.make_window()
            self.addCleanup(window.close)
            window.render(self.snapshot(final_path, chunk_path))
            old_generation = window._result_generation
            gate = Event()
            self.addCleanup(gate.set)
            next_snapshot = ExecutionSnapshot(
                "other-project", "other-execution", "pending",
                chunks=(ChunkSnapshot(0, "pending", chunk_id="other-chunk"),),
                final_result=OutputResolution("no_evidence", message="Todavía no hay ensamblado final."),
            )
            result = LibraryOperationResult(True, snapshot=next_snapshot)
            window._run(lambda: (gate.wait(3), result)[1], "library_open")
            self.assertFalse(window.open_final_result.isEnabled())
            self.assertFalse(window.show_final_result_in_folder.isEnabled())
            self.assertEqual(window._final_result_path, None)
            self.assertEqual(window._chunk_result_paths, {})
            with patch.object(main_window.QDesktopServices, "openUrl", return_value=True) as open_url:
                window._open_chunk_result(0, old_generation)
                self.assertEqual(open_url.call_count, 0)
            gate.set()
            self.wait_for_window_worker(window)
            self.assertFalse(window.open_final_result.isEnabled())
            self.assertFalse(window.show_final_result_in_folder.isEnabled())
            self.assertEqual(window._last_snapshot.project_id, "other-project")
            next_chunk_button = window.chunks.itemWidget(window.chunks.item(0)).findChild(
                QPushButton, "chunkOpenButton1"
            )
            self.assertFalse(next_chunk_button.isEnabled())

    def test_disappeared_result_and_failed_shell_launch_report_actionable_errors(self):
        from orquestador.ui import main_window

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            final_path = Path(temporary) / "assembled.mp4"
            chunk_path = Path(temporary) / "chunk.mp4"
            final_path.write_bytes(_mp4_bytes(1))
            chunk_path.write_bytes(_mp4_bytes(2))
            window = self.make_window()
            self.addCleanup(window.close)
            window.render(self.snapshot(final_path, chunk_path))
            with patch.object(main_window.QDesktopServices, "openUrl", return_value=False):
                window.open_final_result.click()
            self.assertIn("no pudo abrir", window.status.text().lower())
            final_path.unlink()
            window.open_final_result.click()
            self.assertIn("ya no está disponible", window.final_result_status.text())

    def test_library_open_returns_to_principal_with_durable_results_loaded(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from orquestador.ui.app import AppConfig, compose
        from orquestador.ui.main_window import MainWindow

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            comfy_root = root / "comfy-output"
            comfy_root.mkdir()
            project, execution, artifacts, transitions = _build_execution(root)
            facade, resources = compose(AppConfig(root, comfyui_output_root=comfy_root))
            self.addCleanup(resources["repository"].close)
            _persist_successful_execution(resources["repository"], project, execution, artifacts, transitions)
            window = MainWindow(facade, root)
            self.addCleanup(window.close)

            window.show()
            window.tabs.setCurrentIndex(window.library_tab_index)
            self.wait_for_window_worker(window)
            panel = window.library_panel
            selected = None
            for index in range(panel.execution_list.count()):
                item = panel.execution_list.item(index)
                value = item.data(Qt.UserRole)
                if getattr(value, "execution_id", None) == str(execution.id):
                    selected = item
                    break
            self.assertIsNotNone(selected)
            panel.execution_list.setCurrentItem(selected)
            QTest.mouseClick(panel.open_button, Qt.LeftButton)
            self.wait_for_window_worker(window)

            self.assertEqual(window.tabs.currentIndex(), 0)
            self.assertEqual(window._last_snapshot.execution_id, str(execution.id))
            self.assertTrue(window.open_final_result.isEnabled())
            self.assertTrue(window.show_final_result_in_folder.isEnabled())
            chunk_button = window.chunks.itemWidget(window.chunks.item(0)).findChild(
                QPushButton, "chunkOpenButton1"
            )
            self.assertTrue(chunk_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
