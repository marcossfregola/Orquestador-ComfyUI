import tempfile
import unittest
from pathlib import Path

from orquestador.application.drafts import DraftError, DraftUseCase
from orquestador.domain import Chunk, Evidence, Execution, ExecutionId, Lifecycle, OutputRef, Project, ProjectId, QueueItem, QueueItemState
from orquestador.persistence import PersistenceConflict, SQLiteProjectRepository


class F131DraftTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.directory.name)
        self.repository = SQLiteProjectRepository(self.root)
        self.drafts = DraftUseCase(self.repository)

    def tearDown(self):
        self.repository.close()
        self.directory.cleanup()

    @staticmethod
    def defaults(label="one"):
        return {"label": label, "technical": 1}

    @staticmethod
    def chunks(label="one"):
        return [{"prompt": label}, {"prompt": label + " two"}]

    def create(self, project="project", execution=None):
        return self.drafts.create(project, defaults=self.defaults(project), chunks=self.chunks(project), execution_id=execution)

    def test_create_save_reopen_is_durable_and_preserves_identity(self):
        created = self.create(execution="draft-1")
        saved = self.drafts.save("project", "draft-1", defaults={"label": "changed"}, chunks=[{"prompt": "a"}, {"prompt": "b"}, {"prompt": "c"}])
        self.assertEqual((created.execution_id, created.execution_number), (saved.execution_id, saved.execution_number))
        self.repository.close()
        self.repository = SQLiteProjectRepository(self.root)
        self.drafts = DraftUseCase(self.repository)
        reopened = self.drafts.reopen("project", "draft-1")
        self.assertEqual(reopened.defaults, {"label": "changed"})
        self.assertEqual(reopened.chunks, ({"prompt": "a"}, {"prompt": "b"}, {"prompt": "c"}))
        self.assertEqual(len(self.repository.load(ProjectId("project"))[1]), 1)

    def test_listing_is_project_scoped_and_classifies_draft_queued_and_active_running(self):
        first = self.create("one", "one-draft")
        second = self.create("one", "one-queued")
        other = self.create("two", "two-draft")
        queued = QueueItem(ExecutionId(second.execution_id), 0)
        self.repository.save_queue_item(queued)
        self.assertEqual(
            [(item.execution_id, item.classification) for item in self.drafts.list_project_executions("one")],
            [(first.execution_id, "draft"), (second.execution_id, "queued")],
        )
        queued.transition(QueueItemState.ACTIVE)
        project, executions = self.repository.load(ProjectId("one"))
        execution = next(item for item in executions if item.id == queued.execution_id)
        execution.transition(Lifecycle.RUNNING)
        self.repository.save(project, [execution])
        self.repository.save_queue_item(queued)
        self.assertEqual(self.drafts.list_project_executions("one")[1].classification, "running")
        self.assertEqual([(item.execution_id, item.classification) for item in self.drafts.list_project_executions("two")], [(other.execution_id, "draft")])
        self.assertEqual(set(self.drafts.list_projects()), {"one", "two"})

    def test_active_runtime_evidence_is_classified_as_recovering(self):
        draft = self.create(execution="recovering")
        project, executions = self.repository.load(ProjectId("project"))
        execution = next(item for item in executions if str(item.id) == draft.execution_id)
        active = QueueItem(execution.id, 0)
        self.repository.save_queue_item(active)
        active.transition(QueueItemState.ACTIVE)
        self.repository.save_queue_item(active)
        execution.transition(Lifecycle.RUNNING)
        execution.chunks[0].new_attempt()
        self.repository.save(project, [execution])
        self.assertEqual(self.drafts.list_project_executions("project")[0].classification, "recovering")

    def test_queued_and_runtime_evidence_exclude_reopen_and_edit(self):
        queued = self.create(execution="queued")
        self.repository.save_queue_item(QueueItem(ExecutionId(queued.execution_id), 0))
        for method in (self.drafts.reopen,):
            with self.assertRaises(DraftError):
                method("project", queued.execution_id)
        with self.assertRaises(DraftError):
            self.drafts.save("project", queued.execution_id, defaults={}, chunks=self.chunks())

        evidence = self.create(execution="evidence")
        project, executions = self.repository.load(ProjectId("project"))
        execution = next(item for item in executions if str(item.id) == evidence.execution_id)
        execution.chunks[0].new_attempt()
        self.repository.save(project, [execution])
        self.assertEqual(self.drafts.list_project_executions("project")[1].classification, "attention_required")
        with self.assertRaises(DraftError):
            self.drafts.reopen("project", evidence.execution_id)
        with self.assertRaises(DraftError):
            self.drafts.save("project", evidence.execution_id, defaults={}, chunks=self.chunks())

    def test_missing_and_cross_project_ids_fail_closed(self):
        self.create("one", "one-draft")
        self.create("two", "two-draft")
        for project, execution in (("one", "missing"), ("one", "two-draft"), ("missing", "one-draft")):
            with self.subTest(project=project, execution=execution):
                with self.assertRaises(DraftError):
                    self.drafts.reopen(project, execution)

    def test_execution_numbers_are_project_local_monotonic(self):
        first = self.create("one", "one-1")
        other = self.create("two", "two-1")
        second = self.create("one", "one-2")
        self.assertEqual((first.execution_number, second.execution_number, other.execution_number), (1, 2, 1))

    def test_terminal_execution_is_historical_and_not_editable(self):
        draft = self.create(execution="terminal")
        project, executions = self.repository.load(ProjectId("project"))
        execution = next(item for item in executions if str(item.id) == draft.execution_id)
        execution.transition(Lifecycle.CANCELLED)
        self.repository.save(project, [execution])
        self.assertEqual(self.drafts.list_project_executions("project")[0].classification, "cancelled")
        with self.assertRaises(DraftError):
            self.drafts.save("project", draft.execution_id, defaults={}, chunks=self.chunks())

    def test_terminal_classifications_cover_failed_and_succeeded(self):
        failed = self.create("project", "failed")
        succeeded = self.create("project", "succeeded")
        project, executions = self.repository.load(ProjectId("project"))
        failure = next(item for item in executions if str(item.id) == failed.execution_id)
        failure.transition(Lifecycle.RUNNING)
        self.repository.save(project, [failure])
        failure.transition(Lifecycle.FAILED)
        self.repository.save(project, [failure])
        project, executions = self.repository.load(ProjectId("project"))
        success = next(item for item in executions if str(item.id) == succeeded.execution_id)
        for chunk in success.chunks:
            attempt = chunk.new_attempt()
            attempt.transition(Lifecycle.RUNNING)
            attempt.transition(Lifecycle.SUCCEEDED, output=OutputRef("outputs/result.mp4"), evidence=Evidence("verified"))
            chunk.transition(Lifecycle.RUNNING)
            chunk.transition(Lifecycle.SUCCEEDED)
        self.repository.save(project, [success])
        success.transition(Lifecycle.RUNNING)
        self.repository.save(project, [success])
        success.transition(Lifecycle.SUCCEEDED)
        self.repository.save(project, [success])
        self.assertEqual(
            [item.classification for item in self.drafts.list_project_executions("project")],
            ["failed", "succeeded"],
        )

    def test_durable_sequence_save_rejects_a_queue_race(self):
        draft = self.create(execution="race")
        project, executions = self.repository.load(ProjectId("project"))
        execution = next(item for item in executions if str(item.id) == draft.execution_id)
        self.repository.save_queue_item(QueueItem(execution.id, 0))
        with self.assertRaises(PersistenceConflict):
            self.repository.save_preparation_sequence(project, execution)


if __name__ == "__main__":
    unittest.main()
