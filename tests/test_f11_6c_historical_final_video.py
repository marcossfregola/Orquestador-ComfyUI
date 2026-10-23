import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from orquestador.adapters.assembly import AssemblyError
from orquestador.application.assembly import FinalizeExecutionUseCase
from orquestador.application.results import ExecutionResultsResolver
from orquestador.domain import (
    Artifact, AssemblyState, Chunk, Evidence, Execution, ExecutionId,
    Lifecycle, OutputRef, Phase, Project, ProjectId, QueueItemState,
    TransitionFrame,
)
from orquestador.persistence.sqlite import SQLiteProjectRepository


def _mp4_bytes(marker=0):
    return (24).to_bytes(4, "big") + b"ftypisom" + int(marker).to_bytes(4, "big") + b"isomiso2"


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FakeHistoricalAssemblyAdapter:
    def __init__(self):
        self.calls = []
        self.fail_next_stage = False
        self.interrupt_next_stage = False
        self.interrupt_after_stage = False
        self.payload = _mp4_bytes(99)
        self.signature = ("synthetic", "h264", 32, 32, "yuv420p")

    def stage(self, sources, destination, *, reencode=False):
        destination = Path(destination)
        self.calls.append(("stage", tuple(map(Path, sources)), destination))
        if self.interrupt_next_stage:
            self.interrupt_next_stage = False
            raise KeyboardInterrupt("simulated process interruption")
        if self.fail_next_stage:
            self.fail_next_stage = False
            raise AssemblyError("synthetic FFmpeg failure")
        if destination.exists():
            raise AssemblyError("staging destination already exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.payload)
        if self.interrupt_after_stage:
            self.interrupt_after_stage = False
            raise KeyboardInterrupt("simulated interruption after staged file creation")
        return SimpleNamespace(
            path=destination,
            sha256=_sha256(destination),
            probe_signature=self.signature,
        )

    def inspect(self, path):
        path = Path(path)
        self.calls.append(("inspect", path))
        if not path.is_file() or path.stat().st_size == 0:
            raise AssemblyError("missing or empty synthetic video")
        return _sha256(path), self.signature

    def publish(self, staged, destination, *, expected_sha256):
        staged, destination = Path(staged), Path(destination)
        self.calls.append(("publish", staged, destination))
        if destination.exists():
            raise AssemblyError("destination already exists")
        if _sha256(staged) != expected_sha256:
            raise AssemblyError("staged hash mismatch")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as target:
            target.write(staged.read_bytes())
        return destination


class FailHistoricalSuccessSave:
    """Test-only crash seam after publishing, before AssemblyAttempt success save."""
    def __init__(self, repository):
        self.repository = repository
        self.root = repository.root
        self.failed = False

    def __getattr__(self, name):
        return getattr(self.repository, name)

    def save(self, project, executions, *args, **kwargs):
        if not self.failed and any(
            execution.latest_assembly_attempt() is not None
            and execution.latest_assembly_attempt().state is AssemblyState.SUCCEEDED
            for execution in executions
        ):
            self.failed = True
            raise RuntimeError("simulated crash before historical success evidence commit")
        return self.repository.save(project, executions, *args, **kwargs)


class HistoricalFinalVideoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parents[1], ignore_cleanup_errors=True
        )
        self.root = Path(self.temp.name)
        self.repository = SQLiteProjectRepository(self.root)
        self.project = Project(ProjectId("legacy-project"), name="Legacy project")
        self.execution = Execution(self.project.id, ExecutionId("legacy-execution"))
        for order in range(5):
            self.execution.add_chunk(Chunk(order=order))
        self.repository.save(self.project, [self.execution])
        self.queue_item = None
        self.queue_item_id = None

    def tearDown(self):
        try:
            self.repository.close()
        except Exception:
            pass
        self.temp.cleanup()

    def prepare_legacy_success(self, *, queue_state="finished"):
        if queue_state is not None:
            from orquestador.application.queue_operations import QueueOperationsUseCase
            queue = QueueOperationsUseCase(self.repository)
            self.queue_item = queue.enqueue(
                str(self.project.id), str(self.execution.id), queue_item_id="legacy-queue-item"
            )
            self.queue_item_id = str(getattr(self.queue_item, "id", self.queue_item))
            claim = self.repository.claim_next_queue_item()
            self.assertEqual(str(claim.item.id), self.queue_item_id)

        project, executions = self.repository.load(self.project.id)
        execution = executions[0]
        execution.transition(Lifecycle.RUNNING)
        if self.queue_item is not None:
            self.repository.start_execution_from_active_queue_claim(project, execution, self.queue_item_id)
        else:
            self.repository.save(project, [execution])

        transitions = []
        artifacts = []
        for order, chunk in enumerate(execution.chunks):
            chunk.transition(Lifecycle.RUNNING)
            attempt = chunk.new_attempt()
            attempt.transition(Lifecycle.RUNNING)
            output = OutputRef(f"outputs/chunk-{order}.mp4")
            path = self.root / output.uri
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_mp4_bytes(order + 1))
            attempt.transition(
                Lifecycle.SUCCEEDED,
                output=output,
                evidence=Evidence("legacy imported chunk output"),
            )
            chunk.transition(Lifecycle.SUCCEEDED)
            artifact = Artifact(
                self.project.id, execution.id, chunk.id, attempt.id, Phase.OUTPUT, output
            )
            artifacts.append(artifact)
            execution.artifacts.append(artifact)
            next_chunk = execution.chunks[order + 1] if order < len(execution.chunks) - 1 else None
            transition = TransitionFrame(
                self.project.id, execution.id, chunk.id, attempt.id, output,
                0, 1, next_chunk.id if next_chunk is not None else None,
            )
            if next_chunk is not None:
                execution.link_transition(next_chunk, transition)
            transitions.append(transition)
        self.repository.save(
            project, [execution], artifacts=artifacts, transitions=transitions
        )

        # Simulate the terminal row produced before F14.3: execution and queue
        # were marked complete without an AssemblyAttempt record.
        self.repository.db.execute(
            "UPDATE executions SET state='succeeded' WHERE id=?", (str(execution.id),)
        )
        if queue_state == "finished":
            self.repository.db.execute(
                "UPDATE queue_items SET state='finished' WHERE id=?", (self.queue_item_id,)
            )
            self.repository.db.execute(
                "UPDATE queue_control SET active_queue_item_id=NULL, revision=revision+1 WHERE singleton=1"
            )
        self.repository.db.commit()
        self.project, loaded = self.repository.load(self.project.id)
        self.execution = loaded[0]
        self.transitions = tuple(self.repository.load_transitions(self.execution.id))
        self.chunk_attempt_ids = tuple(
            tuple(str(attempt.id) for attempt in chunk.attempts)
            for chunk in self.execution.chunks
        )
        self.queue_control_revision = self.repository.get_queue_control().revision
        return self.project, self.execution

    def finalizer(self, adapter=None, repository=None):
        return FinalizeExecutionUseCase(
            repository or self.repository,
            adapter or FakeHistoricalAssemblyAdapter(),
            self.root,
        )

    def test_explicit_historical_generation_records_final_without_reopening_execution_or_queue(self):
        project, execution = self.prepare_legacy_success()
        queue_before = self.repository.get_queue_item(self.queue_item_id)
        adapter = FakeHistoricalAssemblyAdapter()
        finalizer = self.finalizer(adapter)

        self.assertTrue(finalizer.can_generate_historical(execution))
        self.assertEqual(adapter.calls, [])
        result = finalizer.generate_historical(project.id, execution.id)

        self.assertTrue(result.success, result.reason)
        self.assertEqual(result.output, self.root / f"assembled-{execution.id}.mp4")
        loaded_project, executions = self.repository.load(project.id)
        completed = executions[0]
        self.assertEqual(completed.state, Lifecycle.SUCCEEDED)
        self.assertEqual(completed.latest_assembly_attempt().state, AssemblyState.SUCCEEDED)
        self.assertTrue(finalizer.is_durably_complete(completed))
        self.assertEqual(
            tuple(tuple(str(a.id) for a in c.attempts) for c in completed.chunks),
            self.chunk_attempt_ids,
        )
        self.assertEqual(self.repository.load_transitions(execution.id), list(self.transitions))
        queue_after = self.repository.get_queue_item(self.queue_item_id)
        self.assertEqual(queue_after.state, QueueItemState.FINISHED)
        self.assertEqual(queue_after.updated_at, queue_before.updated_at)
        self.assertEqual(self.repository.get_queue_control().revision, self.queue_control_revision)
        resolved = ExecutionResultsResolver(self.root).resolve(completed)
        self.assertTrue(resolved.final.available)
        self.assertEqual(Path(resolved.final.path), result.output)
        self.assertEqual([call[0] for call in adapter.calls].count("stage"), 1)

    def test_existing_final_file_without_attempt_evidence_is_never_adopted_or_overwritten(self):
        project, execution = self.prepare_legacy_success()
        destination = self.root / f"assembled-{execution.id}.mp4"
        original = b"unproven existing file"
        destination.write_bytes(original)
        adapter = FakeHistoricalAssemblyAdapter()
        finalizer = self.finalizer(adapter)

        self.assertFalse(finalizer.can_generate_historical(execution))
        result = finalizer.generate_historical(project.id, execution.id)

        self.assertFalse(result.success)
        self.assertIn("without durable assembly evidence", result.reason)
        self.assertEqual(destination.read_bytes(), original)
        self.assertEqual(adapter.calls, [])
        _, loaded = self.repository.load(project.id)
        self.assertEqual(loaded[0].state, Lifecycle.SUCCEEDED)
        self.assertEqual(loaded[0].assembly_attempts, [])
        self.assertEqual(self.repository.get_queue_item(self.queue_item_id).state, QueueItemState.FINISHED)

    def test_active_queue_ownership_blocks_historical_generation(self):
        project, execution = self.prepare_legacy_success(queue_state="active")
        adapter = FakeHistoricalAssemblyAdapter()
        finalizer = self.finalizer(adapter)

        self.assertFalse(finalizer.can_generate_historical(execution))
        result = finalizer.generate_historical(project.id, execution.id)

        self.assertFalse(result.success)
        self.assertIn("live queue item", result.reason)
        self.assertEqual(adapter.calls, [])
        _, loaded = self.repository.load(project.id)
        self.assertEqual(loaded[0].state, Lifecycle.SUCCEEDED)
        self.assertEqual(loaded[0].assembly_attempts, [])
        self.assertEqual(self.repository.get_queue_item(self.queue_item_id).state, QueueItemState.ACTIVE)

    def test_missing_durable_transition_blocks_generation_without_recording_or_running_adapter(self):
        project, execution = self.prepare_legacy_success()
        self.repository.db.execute(
            "DELETE FROM transitions WHERE execution_id=? AND source_chunk_id=?",
            (str(execution.id), str(execution.chunks[0].id)),
        )
        adapter = FakeHistoricalAssemblyAdapter()
        finalizer = self.finalizer(adapter)
        _, loaded = self.repository.load(project.id)

        self.assertFalse(finalizer.can_generate_historical(loaded[0]))
        result = finalizer.generate_historical(project.id, execution.id)

        self.assertFalse(result.success)
        self.assertIn("continuity transition", result.reason)
        self.assertEqual(adapter.calls, [])
        _, reread = self.repository.load(project.id)
        self.assertEqual(reread[0].state, Lifecycle.SUCCEEDED)
        self.assertEqual(reread[0].assembly_attempts, [])

    def test_duplicate_terminal_transition_blocks_generation_as_ambiguous(self):
        project, execution = self.prepare_legacy_success()
        final_chunk = execution.chunks[-1]
        final_attempt = final_chunk.attempts[0]
        unexpected = TransitionFrame(
            project.id, execution.id, final_chunk.id, final_attempt.id,
            final_attempt.output, 0, 1, None,
        )
        self.repository.save(project, [execution], transitions=(unexpected,))
        _, loaded = self.repository.load(project.id)
        adapter = FakeHistoricalAssemblyAdapter()
        finalizer = self.finalizer(adapter)

        self.assertFalse(finalizer.can_generate_historical(loaded[0]))
        result = finalizer.generate_historical(project.id, execution.id)

        self.assertFalse(result.success)
        self.assertIn("transition set is missing or ambiguous", result.reason)
        self.assertEqual(adapter.calls, [])
        _, reread = self.repository.load(project.id)
        self.assertEqual(reread[0].state, Lifecycle.SUCCEEDED)
        self.assertEqual(reread[0].assembly_attempts, [])

    def test_contradictory_terminal_transition_blocks_generation(self):
        project, execution = self.prepare_legacy_success()
        self.repository.db.execute(
            "UPDATE transitions SET source_output=? WHERE execution_id=? AND target_chunk_id IS NULL",
            ("outputs/untrusted-terminal.mp4", str(execution.id)),
        )
        adapter = FakeHistoricalAssemblyAdapter()
        finalizer = self.finalizer(adapter)

        self.assertFalse(finalizer.can_generate_historical(execution))
        result = finalizer.generate_historical(project.id, execution.id)

        self.assertFalse(result.success)
        self.assertEqual(adapter.calls, [])
        state, attempt_count = self.repository.db.execute(
            "SELECT e.state,(SELECT count(*) FROM execution_assembly_attempts a WHERE a.execution_id=e.id) "
            "FROM executions e WHERE e.id=?",
            (str(execution.id),),
        ).fetchone()
        self.assertEqual(state, Lifecycle.SUCCEEDED.value)
        self.assertEqual(attempt_count, 0)

    def test_ambiguous_successful_output_artifact_blocks_generation(self):
        project, execution = self.prepare_legacy_success()
        source_chunk = execution.chunks[0]
        source_attempt = source_chunk.attempts[0]
        duplicate = Artifact(
            project.id, execution.id, source_chunk.id, source_attempt.id,
            Phase.OUTPUT, source_attempt.output,
        )
        self.repository.save(project, [execution], artifacts=(duplicate,))
        _, loaded = self.repository.load(project.id)
        adapter = FakeHistoricalAssemblyAdapter()
        finalizer = self.finalizer(adapter)

        self.assertFalse(finalizer.can_generate_historical(loaded[0]))
        result = finalizer.generate_historical(project.id, execution.id)

        self.assertFalse(result.success)
        self.assertIn("ambiguous durable output artifact", result.reason)
        self.assertEqual(adapter.calls, [])
        _, reread = self.repository.load(project.id)
        self.assertEqual(reread[0].state, Lifecycle.SUCCEEDED)
        self.assertEqual(reread[0].assembly_attempts, [])

    def test_failed_historical_assembly_retries_only_assembly_and_keeps_terminal_states(self):
        project, execution = self.prepare_legacy_success()
        adapter = FakeHistoricalAssemblyAdapter()
        adapter.fail_next_stage = True
        finalizer = self.finalizer(adapter)

        failed = finalizer.generate_historical(project.id, execution.id)
        self.assertFalse(failed.success)
        _, loaded = self.repository.load(project.id)
        interrupted = loaded[0]
        self.assertEqual(interrupted.state, Lifecycle.SUCCEEDED)
        self.assertEqual(interrupted.latest_assembly_attempt().state, AssemblyState.FAILED)
        self.assertTrue(finalizer.can_retry_historical(interrupted))
        self.assertEqual(self.repository.get_queue_item(self.queue_item_id).state, QueueItemState.FINISHED)

        retried = finalizer.retry_historical(project.id, execution.id)
        self.assertTrue(retried.success, retried.reason)
        _, loaded = self.repository.load(project.id)
        completed = loaded[0]
        self.assertEqual(completed.state, Lifecycle.SUCCEEDED)
        self.assertEqual([attempt.number for attempt in completed.assembly_attempts], [1, 2])
        self.assertEqual(completed.latest_assembly_attempt().state, AssemblyState.SUCCEEDED)
        self.assertEqual(
            tuple(tuple(str(a.id) for a in c.attempts) for c in completed.chunks),
            self.chunk_attempt_ids,
        )
        self.assertEqual(self.repository.load_transitions(execution.id), list(self.transitions))
        self.assertEqual(self.repository.get_queue_item(self.queue_item_id).state, QueueItemState.FINISHED)
        self.assertEqual([call[0] for call in adapter.calls].count("stage"), 2)

    def test_changed_historical_chunk_bytes_block_retry(self):
        project, execution = self.prepare_legacy_success()
        adapter = FakeHistoricalAssemblyAdapter()
        adapter.fail_next_stage = True
        finalizer = self.finalizer(adapter)
        failed = finalizer.generate_historical(project.id, execution.id)
        self.assertFalse(failed.success)
        source_path = self.root / execution.chunks[0].attempts[0].output.uri
        source_path.write_bytes(_mp4_bytes(200))
        _, loaded = self.repository.load(project.id)

        self.assertFalse(finalizer.can_retry_historical(loaded[0]))
        retry = finalizer.retry_historical(project.id, execution.id)

        self.assertFalse(retry.success)
        self.assertEqual([call[0] for call in adapter.calls].count("stage"), 1)
        self.assertEqual(self.repository.get_queue_item(self.queue_item_id).state, QueueItemState.FINISHED)
        _, reread = self.repository.load(project.id)
        self.assertEqual(reread[0].state, Lifecycle.SUCCEEDED)
        self.assertEqual(reread[0].latest_assembly_attempt().state, AssemblyState.FAILED)

    def test_interrupted_historical_stage_resumes_after_repository_restart(self):
        project, execution = self.prepare_legacy_success()
        crashed_adapter = FakeHistoricalAssemblyAdapter()
        crashed_adapter.interrupt_next_stage = True
        finalizer = self.finalizer(crashed_adapter)

        with self.assertRaises(KeyboardInterrupt):
            finalizer.generate_historical(project.id, execution.id)
        self.repository.close()
        self.repository = SQLiteProjectRepository(self.root)
        _, loaded = self.repository.load(project.id)
        assembling = loaded[0]
        self.assertEqual(assembling.state, Lifecycle.SUCCEEDED)
        self.assertEqual(assembling.latest_assembly_attempt().state, AssemblyState.ASSEMBLING)
        self.assertTrue(self.finalizer(FakeHistoricalAssemblyAdapter()).can_generate_historical(assembling))

        recovered_adapter = FakeHistoricalAssemblyAdapter()
        recovered = self.finalizer(recovered_adapter).generate_historical(project.id, execution.id)
        self.assertTrue(recovered.success, recovered.reason)
        _, loaded = self.repository.load(project.id)
        self.assertEqual(loaded[0].state, Lifecycle.SUCCEEDED)
        self.assertEqual(loaded[0].latest_assembly_attempt().state, AssemblyState.SUCCEEDED)
        self.assertEqual([call[0] for call in recovered_adapter.calls].count("stage"), 1)
        self.assertEqual(self.repository.get_queue_item(self.queue_item_id).state, QueueItemState.FINISHED)

    def test_interrupted_unidentified_stage_is_preserved_then_retried_under_new_attempt(self):
        project, execution = self.prepare_legacy_success()
        adapter = FakeHistoricalAssemblyAdapter()
        adapter.interrupt_after_stage = True
        with self.assertRaises(KeyboardInterrupt):
            self.finalizer(adapter).generate_historical(project.id, execution.id)

        staging = self.root / ".orquestador-assembly" / str(execution.id) / "attempt-1.mp4"
        original_stage = staging.read_bytes()
        self.repository.close()
        self.repository = SQLiteProjectRepository(self.root)
        _, loaded = self.repository.load(project.id)
        self.assertEqual(loaded[0].state, Lifecycle.SUCCEEDED)
        self.assertEqual(loaded[0].latest_assembly_attempt().state, AssemblyState.ASSEMBLING)
        failed = self.finalizer(adapter).generate_historical(project.id, execution.id)
        self.assertFalse(failed.success)
        self.assertIn("no durable hash/probe identity", failed.reason)
        self.assertEqual(staging.read_bytes(), original_stage)

        _, loaded = self.repository.load(project.id)
        self.assertEqual(loaded[0].latest_assembly_attempt().state, AssemblyState.FAILED)
        self.assertTrue(self.finalizer(adapter).can_retry_historical(loaded[0]))
        recovered = self.finalizer(adapter).retry_historical(project.id, execution.id)
        self.assertTrue(recovered.success, recovered.reason)
        self.assertEqual(staging.read_bytes(), original_stage)
        _, loaded = self.repository.load(project.id)
        self.assertEqual([attempt.number for attempt in loaded[0].assembly_attempts], [1, 2])
        self.assertEqual(loaded[0].state, Lifecycle.SUCCEEDED)
        self.assertEqual(self.repository.get_queue_item(self.queue_item_id).state, QueueItemState.FINISHED)

    def test_restart_after_publish_adopts_only_matching_durable_hash_and_probe(self):
        project, execution = self.prepare_legacy_success()
        underlying = self.repository
        adapter = FakeHistoricalAssemblyAdapter()
        failing_repository = FailHistoricalSuccessSave(underlying)
        result = self.finalizer(adapter, failing_repository).generate_historical(project.id, execution.id)

        self.assertFalse(result.success)
        destination = self.root / f"assembled-{execution.id}.mp4"
        self.assertTrue(destination.is_file())
        self.repository.close()
        self.repository = SQLiteProjectRepository(self.root)
        _, loaded = self.repository.load(project.id)
        interrupted = loaded[0]
        self.assertEqual(interrupted.state, Lifecycle.SUCCEEDED)
        self.assertEqual(interrupted.latest_assembly_attempt().state, AssemblyState.ASSEMBLING)
        self.assertEqual(interrupted.latest_assembly_attempt().expected_sha256, _sha256(destination))

        recovered = self.finalizer(adapter).generate_historical(project.id, execution.id)
        self.assertTrue(recovered.success, recovered.reason)
        _, loaded = self.repository.load(project.id)
        self.assertEqual(loaded[0].state, Lifecycle.SUCCEEDED)
        self.assertEqual(loaded[0].latest_assembly_attempt().state, AssemblyState.SUCCEEDED)
        self.assertEqual([call[0] for call in adapter.calls].count("stage"), 1)
        self.assertEqual(self.repository.get_queue_item(self.queue_item_id).state, QueueItemState.FINISHED)


class HistoricalFinalVideoGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_shows_and_invokes_explicit_historical_action(self):
        from orquestador.application.gui_facade import ExecutionSnapshot, GuiFacade
        from orquestador.ui.main_window import MainWindow

        calls = []
        snapshot = ExecutionSnapshot(
            project_id="legacy-project", execution_id="legacy-execution", state="succeeded",
            can_generate_historical_final=True,
        )
        facade = GuiFacade(
            snapshot=lambda *_: snapshot,
            historical_assembly=lambda project_id, execution_id: calls.append(
                (project_id, execution_id)
            ) or SimpleNamespace(success=True, execution_id=execution_id, state="succeeded"),
        )
        window = MainWindow(facade)
        self.addCleanup(window.close)
        window.project.setText("legacy-project")
        window.execution.setText("legacy-execution")
        window.render(snapshot)
        window._run = lambda operation, kind="other": operation()

        self.assertFalse(window.generate_historical_final.isHidden())
        self.assertTrue(window.generate_historical_final.isEnabled())
        self.assertEqual(calls, [])
        window.generate_historical_final.click()
        self.assertEqual(calls, [("legacy-project", "legacy-execution")])

        hidden = ExecutionSnapshot(
            project_id="another-project", execution_id="another-execution", state="succeeded",
            can_generate_historical_final=False,
        )
        window.render(hidden)
        self.assertTrue(window.generate_historical_final.isHidden())

    def test_five_chunk_historical_snapshot_with_terminal_checkpoint_shows_action(self):
        from orquestador.ui.app import AppConfig, compose
        from orquestador.ui.main_window import MainWindow

        fixture = HistoricalFinalVideoTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        project, execution = fixture.prepare_legacy_success()
        adapter = FakeHistoricalAssemblyAdapter()
        facade, resources = compose(
            AppConfig(fixture.root),
            client_factory=lambda _endpoint: object(),
            assembler_factory=lambda: adapter,
        )
        self.addCleanup(resources["repository"].close)
        window = MainWindow(facade)
        self.addCleanup(window.close)

        snapshot = facade.refresh(str(project.id), str(execution.id))
        window.render(snapshot)

        self.assertEqual(len(execution.chunks), 5)
        self.assertEqual(len(fixture.repository.load_transitions(execution.id)), 5)
        self.assertTrue(snapshot.can_generate_historical_final)
        self.assertFalse(window.generate_historical_final.isHidden())
        self.assertTrue(window.generate_historical_final.isEnabled())
        self.assertEqual(adapter.calls, [])

    def test_chunk_result_widget_does_not_paint_duplicate_item_text(self):
        from orquestador.application.gui_facade import GuiFacade
        from PySide6.QtWidgets import QLabel, QPushButton, QStyleOptionViewItem
        from orquestador.ui.main_window import MainWindow

        window = MainWindow(GuiFacade())
        self.addCleanup(window.close)
        chunks = [
            SimpleNamespace(
                order=index,
                state="succeeded",
                attempt_ref=f"attempt-{index}",
                error=None,
                output=f"outputs/chunk-{index}.mp4",
                transition=f"transition-{index}",
                resolved_output=SimpleNamespace(
                    available=True,
                    path=f"C:/results/chunk-{index}.mp4",
                    attempt_number=1,
                    message="",
                ),
            )
            for index in range(2)
        ]
        window._render_results(
            SimpleNamespace(
                chunks=chunks,
                can_generate_historical_final=False,
                final_result=None,
                state="succeeded",
            )
        )
        window.show()
        self.app.processEvents()

        for index in range(len(chunks)):
            item = window.chunks.item(index)
            model_index = window.chunks.model().index(index, 0)
            delegate = window.chunks.itemDelegate()
            paint_option = delegate._style_option(QStyleOptionViewItem(), model_index)
            row = window.chunks.itemWidget(item)
            label = row.findChild(QLabel)
            button = row.findChild(QPushButton, f"chunkOpenButton{index + 1}")
            self.assertIn("output=outputs/chunk-", item.text())
            self.assertEqual(paint_option.text, "")
            self.assertIn("Chunk ", label.text())
            self.assertTrue(button.isEnabled())

    def test_composed_action_runs_only_after_click_and_refreshes_final_result(self):
        from orquestador.ui.app import AppConfig, compose
        from orquestador.ui.main_window import MainWindow

        fixture = HistoricalFinalVideoTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        project, execution = fixture.prepare_legacy_success()
        adapter = FakeHistoricalAssemblyAdapter()

        facade, resources = compose(
            AppConfig(fixture.root),
            client_factory=lambda _endpoint: object(),
            assembler_factory=lambda: adapter,
        )
        self.addCleanup(resources["repository"].close)
        window = MainWindow(facade)
        self.addCleanup(window.close)
        window.project.setText(str(project.id))
        window.execution.setText(str(execution.id))
        snapshot = facade.refresh(str(project.id), str(execution.id))
        window.render(snapshot)
        calls = []
        window._run = lambda operation, kind="other": calls.append((kind, operation()))

        self.assertTrue(snapshot.can_generate_historical_final)
        self.assertTrue(window.generate_historical_final.isEnabled())
        self.assertEqual(adapter.calls, [])
        window.generate_historical_final.click()

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "historical_assembly")
        self.assertTrue(calls[0][1].success, calls[0][1].message)
        self.assertTrue(calls[0][1].snapshot.final_result.available)
        window.render(calls[0][1].snapshot)
        self.assertTrue(window.open_final_result.isEnabled())
        self.assertTrue(window.show_final_result_in_folder.isEnabled())
        self.assertEqual([call[0] for call in adapter.calls].count("stage"), 1)
        self.assertFalse(calls[0][1].snapshot.can_generate_historical_final)
        self.assertTrue(window.generate_historical_final.isHidden())


if __name__ == "__main__":
    unittest.main()
