import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orquestador.application.chunk_templates import ChunkTemplatesUseCase
from orquestador.application.chain_execution import ChainExecutionUseCase, ChainOutcome
from orquestador.application.drafts import DraftError, DraftUseCase
from orquestador.application.edit_chunk_sequence import EditChunkSequenceUseCase
from orquestador.application.global_defaults import GlobalDefaultsUseCase
from orquestador.application.queue_operations import (
    QueueOperationError,
    QueueOperationsUseCase,
)
from orquestador.application.technical_presets import TechnicalPresetsUseCase
from orquestador.application.start_gui_chain import StartGuiChainUseCase, StartPreparationError
from orquestador.domain import DomainError, Lifecycle, ProjectId, QueueControl, QueueItemState
from orquestador.domain.config import GenerationConfig, GlobalDefaults
from orquestador.persistence import SQLiteProjectRepository


class F137QueueOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        (self.root / "inputs").mkdir()
        (self.root / "inputs" / "initial.png").write_bytes(b"initial")
        (self.root / "inputs" / "reference.png").write_bytes(b"reference")
        self.repo = SQLiteProjectRepository(self.root)
        self.drafts = DraftUseCase(self.repo)
        self.queue = QueueOperationsUseCase(self.repo)

    def tearDown(self):
        self.repo.close()
        self.temp.cleanup()

    def draft(self, project_id="project", execution_id="draft", *, complete=False):
        if complete:
            defaults = {
                "profile_ref": "minimax-h3-ui",
                "initial_image": "inputs/initial.png",
                "references": ["inputs/reference.png"],
                "chunk_count": 2,
                "prompts": ["one", "two"],
                "metadata": {"preserve": True},
            }
        else:
            defaults = {"label": project_id, "metadata": {"preserve": True}}
        return self.drafts.create(
            project_id,
            execution_id=execution_id,
            defaults=defaults,
            chunks=[{"prompt": "one", "steps": 21}, {"prompt": "two", "fps": 12}],
        )

    def test_enqueue_selection_reorder_and_reopen_are_durable(self):
        first = self.draft(execution_id="first")
        second = self.draft(execution_id="second")
        with self.assertRaises(QueueOperationError):
            self.queue.enqueue("another-project", first.execution_id)
        item_one = self.queue.enqueue("project", first.execution_id, queue_item_id="queue-one")
        item_two = self.queue.enqueue("project", second.execution_id, queue_item_id="queue-two")

        self.assertEqual(
            [(item.id, item.position, item.state) for item in self.queue.list()],
            [("queue-one", 0, "queued"), ("queue-two", 1, "queued")],
        )
        self.assertEqual(self.queue.select("queue-one"), item_one)
        self.assertEqual(self.queue.snapshot().control.paused, False)
        self.assertEqual(
            [(item.id, item.position) for item in self.queue.reorder(["queue-two", "queue-one"])],
            [("queue-two", 0), ("queue-one", 1)],
        )
        with self.assertRaises(DraftError):
            self.drafts.reopen("project", first.execution_id)

        self.repo.close()
        self.repo = SQLiteProjectRepository(self.root)
        self.drafts = DraftUseCase(self.repo)
        self.queue = QueueOperationsUseCase(self.repo)
        self.assertEqual(
            [(item.id, item.execution_id, item.position) for item in self.queue.list()],
            [
                ("queue-two", second.execution_id, 0),
                ("queue-one", first.execution_id, 1),
            ],
        )

    def test_remove_skip_preserve_aggregates_and_allow_a_fresh_enqueue(self):
        first = self.draft(execution_id="first")
        second = self.draft(execution_id="second")
        item_one = self.queue.enqueue("project", first.execution_id, queue_item_id="queue-one")
        item_two = self.queue.enqueue("project", second.execution_id, queue_item_id="queue-two")

        removed = self.queue.remove(item_one.id)
        skipped = self.queue.skip(item_two.id, reason="operator chose a later run")
        self.assertEqual((removed.state, removed.terminal_reason), ("removed", "operator removed"))
        self.assertEqual((skipped.state, skipped.terminal_reason), ("skipped", "operator chose a later run"))
        self.assertFalse(self.repo.has_live_queue_item(first.execution_id))
        self.assertFalse(self.repo.has_live_queue_item(second.execution_id))
        self.assertEqual(self.drafts.reopen("project", first.execution_id).execution_id, first.execution_id)
        self.assertEqual(self.drafts.reopen("project", second.execution_id).execution_id, second.execution_id)
        project, executions = self.repo.load(ProjectId("project"))
        self.assertEqual(str(project.id), "project")
        self.assertEqual({str(execution.id) for execution in executions}, {"first", "second"})
        self.assertTrue(all(len(execution.chunks) == 2 for execution in executions))

        fresh = self.queue.enqueue("project", first.execution_id, queue_item_id="queue-one-again")
        self.assertEqual(fresh.position, 2)
        another = self.queue.enqueue("project", second.execution_id, queue_item_id="queue-two-again")
        self.assertEqual(
            [(item.id, item.position) for item in self.queue.reorder([another.id, fresh.id])],
            [(another.id, 2), (fresh.id, 3)],
        )
        self.assertEqual(
            [item.state for item in self.queue.list()], ["removed", "skipped", "queued", "queued"]
        )

    def test_only_editable_virgin_executions_enter_and_active_items_are_protected(self):
        queued = self.draft(execution_id="queued")
        runtime = self.draft(execution_id="runtime")
        project, executions = self.repo.load(ProjectId("project"))
        execution = next(item for item in executions if str(item.id) == runtime.execution_id)
        execution.transition(Lifecycle.RUNNING)
        execution.chunks[0].new_attempt()
        self.repo.save(project, [execution])
        with self.assertRaises(QueueOperationError):
            self.queue.enqueue("project", runtime.execution_id)

        item = self.queue.enqueue("project", queued.execution_id, queue_item_id="active")
        with self.assertRaises(QueueOperationError):
            self.queue.enqueue("project", queued.execution_id, queue_item_id="duplicate-live")
        durable = self.repo.get_queue_item(item.id)
        durable.transition(QueueItemState.ACTIVE)
        self.repo.save_queue_item(durable)
        self.repo.save_queue_control(QueueControl(active_queue_item_id=durable.id, revision=1))

        for operation in (
            lambda: self.queue.remove(item.id),
            lambda: self.queue.skip(item.id),
            lambda: self.queue.reorder([item.id]),
            lambda: self.queue.duplicate(item.id),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises(QueueOperationError):
                    operation()
        self.assertEqual(self.queue.pause().paused, True)
        self.assertEqual(self.queue.read(item.id).state, "active")

    def test_queue_blocks_direct_start_and_sequence_edits_without_scheduling(self):
        created = self.draft(execution_id="guarded", complete=True)
        item = self.queue.enqueue("project", created.execution_id, queue_item_id="guarded-item")
        calls = []

        class Chain:
            def run(self, *args, **kwargs):
                calls.append((args, kwargs))

        with self.assertRaises(StartPreparationError):
            StartGuiChainUseCase(self.repo, self.root, Chain())("project", created.execution_id)
        project, executions = self.repo.load(ProjectId("project"))
        execution = next(entry for entry in executions if str(entry.id) == created.execution_id)
        with self.assertRaises(DomainError):
            EditChunkSequenceUseCase(self.repo)(
                "project", created.execution_id, "update_prompt", execution.chunks[0].id, prompt="changed"
            )
        class Runner:
            def execute(self, *args, **kwargs):
                calls.append((args, kwargs))

        direct = ChainExecutionUseCase(self.repo, Runner()).run(
            project, execution, lambda index, chunk: {"prompt": "unused"}
        )
        self.assertEqual(calls, [])
        self.assertEqual(direct.outcome, ChainOutcome.BLOCKED)
        self.assertEqual(self.queue.read(item.id).state, "queued")
        self.assertEqual(execution.state, Lifecycle.PENDING)

        durable = self.repo.get_queue_item(item.id)
        durable.transition(QueueItemState.ACTIVE)
        self.repo.save_queue_item(durable)
        self.repo.save_queue_control(QueueControl(active_queue_item_id=durable.id))
        active_direct = ChainExecutionUseCase(self.repo, Runner()).run(
            project, execution, lambda index, chunk: {"prompt": "unused"}
        )
        self.assertEqual(calls, [])
        self.assertEqual(active_direct.outcome, ChainOutcome.BLOCKED)
        self.assertEqual(execution.state, Lifecycle.PENDING)

    def test_pause_resume_are_durable_idempotent_and_revision_guarded(self):
        initial = self.queue.control()
        paused = self.queue.pause(expected_revision=initial.revision)
        self.assertEqual((paused.paused, paused.revision), (True, initial.revision + 1))
        self.assertEqual(self.queue.pause(expected_revision=paused.revision), paused)
        with self.assertRaises(QueueOperationError):
            self.queue.resume(expected_revision=initial.revision)
        resumed = self.queue.resume(expected_revision=paused.revision)
        self.assertEqual((resumed.paused, resumed.revision), (False, paused.revision + 1))

        self.repo.close()
        self.repo = SQLiteProjectRepository(self.root)
        self.queue = QueueOperationsUseCase(self.repo)
        self.assertEqual(self.queue.control(), resumed)

    def test_duplicate_clones_selected_pending_item_and_enqueues_the_copy_by_value(self):
        source = self.draft("source", "source-execution", complete=True)
        original = self.queue.enqueue("source", source.execution_id, queue_item_id="source-item")
        with patch.object(self.repo, "load_global_defaults", side_effect=AssertionError("clone consulted globals")), patch.object(
            self.repo, "list_technical_presets", side_effect=AssertionError("clone consulted presets")
        ), patch.object(
            self.repo, "list_chunk_templates", side_effect=AssertionError("clone consulted templates")
        ):
            copied = self.queue.duplicate(original.id, new_queue_item_id="copy-item")

        self.assertEqual(copied.source_queue_item_id, original.id)
        self.assertNotEqual(copied.project_id, "source")
        self.assertNotEqual(copied.execution_id, source.execution_id)
        self.assertEqual((copied.queue_item.id, copied.queue_item.state), ("copy-item", "queued"))
        source_project, source_executions = self.repo.load(ProjectId("source"))
        copy_project, copy_executions = self.repo.load(ProjectId(copied.project_id))
        source_execution = next(item for item in source_executions if str(item.id) == source.execution_id)
        copy_execution = next(item for item in copy_executions if str(item.id) == copied.execution_id)
        self.assertEqual(dict(copy_project.defaults), {})
        self.assertEqual(
            dict(copy_execution.defaults),
            GenerationConfig.from_mapping(source_execution.defaults, strict=False).to_mapping(),
        )
        self.assertNotIn("metadata", copy_execution.defaults)
        self.assertEqual(
            [dict(chunk.defaults) for chunk in copy_execution.chunks],
            [dict(chunk.defaults) for chunk in source_execution.chunks],
        )
        self.assertNotEqual(
            [str(chunk.id) for chunk in copy_execution.chunks],
            [str(chunk.id) for chunk in source_execution.chunks],
        )
        self.assertTrue(all(not chunk.attempts and chunk.state is Lifecycle.PENDING for chunk in copy_execution.chunks))
        self.assertEqual(
            [(item.id, item.execution_id, item.state) for item in self.queue.list()],
            [("source-item", source.execution_id, "queued"), ("copy-item", copied.execution_id, "queued")],
        )

    def test_duplicate_rolls_back_clone_when_enqueue_cannot_persist(self):
        source = self.draft("source", "source-execution", complete=True)
        item = self.queue.enqueue("source", source.execution_id, queue_item_id="source-item")
        projects_before = self.repo.list_project_ids()
        queue_before = self.queue.list()
        self.repo.db.execute(
            "CREATE TRIGGER reject_queued_clone BEFORE INSERT ON queue_items "
            "WHEN NEW.id='blocked-copy' BEGIN SELECT RAISE(ABORT,'forced'); END"
        )
        with self.assertRaises(QueueOperationError):
            self.queue.duplicate(item.id, new_queue_item_id="blocked-copy")
        self.assertEqual(self.repo.list_project_ids(), projects_before)
        self.assertEqual(self.queue.list(), queue_before)

    def test_two_repository_connections_cannot_enqueue_the_same_execution_twice(self):
        created = self.draft(execution_id="shared")
        other_repository = SQLiteProjectRepository(self.root)
        self.addCleanup(other_repository.close)
        other_queue = QueueOperationsUseCase(other_repository)
        first = self.queue.enqueue("project", created.execution_id, queue_item_id="first")
        with self.assertRaises(QueueOperationError):
            other_queue.enqueue("project", created.execution_id, queue_item_id="second")
        self.assertEqual(
            [(item.id, item.execution_id) for item in other_queue.list()],
            [(first.id, created.execution_id)],
        )

    def test_reorder_rolls_back_and_corruption_fails_closed(self):
        first = self.draft(execution_id="first")
        second = self.draft(execution_id="second")
        self.queue.enqueue("project", first.execution_id, queue_item_id="one")
        self.queue.enqueue("project", second.execution_id, queue_item_id="two")
        before = self.queue.list()
        for invalid_order in (("one",), ("one", "one")):
            with self.subTest(invalid_order=invalid_order):
                with self.assertRaises(QueueOperationError):
                    self.queue.reorder(invalid_order)
                self.assertEqual(self.queue.list(), before)
        self.repo.db.execute(
            "CREATE TRIGGER reject_queue_reorder BEFORE UPDATE OF position ON queue_items "
            "WHEN NEW.id='one' BEGIN SELECT RAISE(ABORT,'forced'); END"
        )
        with self.assertRaises(QueueOperationError):
            self.queue.reorder(["two", "one"])
        self.assertEqual(self.queue.list(), before)

        self.repo.db.execute("DROP TRIGGER reject_queue_reorder")
        self.repo.db.execute("PRAGMA ignore_check_constraints=ON")
        self.repo.db.execute("UPDATE queue_control SET paused=2 WHERE singleton=1")
        self.repo.db.execute("PRAGMA ignore_check_constraints=OFF")
        with self.assertRaises(QueueOperationError):
            self.queue.control()

    def test_authoring_sources_and_existing_snapshots_are_preserved(self):
        globals_mapping = {**GlobalDefaults().to_mapping(), "steps": 31}
        GlobalDefaultsUseCase(self.repo).update(globals_mapping)
        preset = TechnicalPresetsUseCase(self.repo).create("technical", globals_mapping)
        template = ChunkTemplatesUseCase(self.repo).create("story", ("one", "two"))
        created = self.draft("project", "draft", complete=True)
        before = self.drafts.reopen("project", created.execution_id)
        with patch.object(self.repo, "load_global_defaults", side_effect=AssertionError("queue consulted globals")), patch.object(
            self.repo, "list_technical_presets", side_effect=AssertionError("queue consulted presets")
        ), patch.object(
            self.repo, "list_chunk_templates", side_effect=AssertionError("queue consulted templates")
        ):
            item = self.queue.enqueue("project", created.execution_id, queue_item_id="queue")
            self.queue.reorder([item.id])
        self.assertEqual(self.repo.load_global_defaults().to_mapping(), globals_mapping)
        self.assertEqual(TechnicalPresetsUseCase(self.repo).read(preset.id).mapping, globals_mapping)
        self.assertEqual(ChunkTemplatesUseCase(self.repo).read(template.id).prompts, ("one", "two"))
        project, executions = self.repo.load(ProjectId("project"))
        execution = next(item for item in executions if str(item.id) == created.execution_id)
        self.assertEqual((dict(execution.defaults), tuple(dict(chunk.defaults) for chunk in execution.chunks)), (before.defaults, before.chunks))
        self.assertEqual(str(project.id), "project")

    def test_schema_four_queue_rows_migrate_to_current_schema_and_remain_operable(self):
        created = self.draft(execution_id="legacy")
        item = self.queue.enqueue("project", created.execution_id, queue_item_id="legacy-item")
        self.queue.pause()
        self.repo.close()
        db = sqlite3.connect(self.root / "orquestador.sqlite3")
        db.execute("DROP TABLE chunk_templates")
        db.execute("DROP TABLE technical_presets")
        db.execute("DROP TABLE global_defaults")
        db.execute("UPDATE schema_version SET version=4")
        db.commit()
        db.close()

        self.repo = SQLiteProjectRepository(self.root)
        self.queue = QueueOperationsUseCase(self.repo)
        self.assertEqual(self.repo.db.execute("SELECT version FROM schema_version").fetchone()[0], 7)
        self.assertEqual(self.queue.read(item.id).execution_id, created.execution_id)
        self.assertTrue(self.queue.control().paused)
        self.assertFalse(self.queue.resume().paused)


if __name__ == "__main__":
    unittest.main()
