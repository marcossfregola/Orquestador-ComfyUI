import tempfile
import unittest
from pathlib import Path

from orquestador.application.drafts import DraftUseCase
from orquestador.application.preparation_library import (
    PreparationLibraryError,
    PreparationLibraryUseCase,
)
from orquestador.application.queue_operations import QueueOperationsUseCase
from orquestador.domain import (
    Artifact,
    Chunk,
    Evidence,
    Execution,
    ExecutionId,
    Lifecycle,
    OutputRef,
    Phase,
    Project,
    ProjectId,
)
from orquestador.persistence import SQLiteProjectRepository


class ProjectLibraryDeleteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.repository = SQLiteProjectRepository(self.root)
        self.drafts = DraftUseCase(self.repository)
        self.library = PreparationLibraryUseCase(self.repository)

    def tearDown(self):
        self.repository.close()
        self.temp.cleanup()

    def draft(self, project_id, execution_id):
        return self.drafts.create(
            project_id,
            execution_id=execution_id,
            defaults={},
            chunks=({"prompt": "one"}, {"prompt": "two"}),
        )

    def durable_rows(self):
        tables = (
            "projects",
            "executions",
            "chunks",
            "attempts",
            "artifacts",
            "errors",
            "transitions",
            "queue_items",
            "queue_control",
            "execution_assembly_attempts",
        )
        return {
            table: self.repository.db.execute(
                f"SELECT * FROM {table} ORDER BY rowid"
            ).fetchall()
            for table in tables
        }

    def test_delete_draft_removes_project_without_touching_files(self):
        selection = self.draft("delete-draft", "draft-execution")
        witness = self.root / "keep.txt"
        witness.write_text("keep", encoding="utf-8")

        deleted = self.library.delete_project(selection.project_id)

        self.assertEqual(deleted, selection.project_id)
        self.assertNotIn(selection.project_id, {str(item) for item in self.repository.list_project_ids()})
        self.assertTrue(witness.exists())
        self.assertEqual(
            self.repository.db.execute(
                "SELECT COUNT(*) FROM executions WHERE project_id=?",
                (selection.project_id,),
            ).fetchone()[0],
            0,
        )

    def test_delete_terminal_history_cleans_owned_rows_and_preserves_output(self):
        project = Project(ProjectId("terminal-history"), name="Terminal history")
        succeeded = Execution(project.id, ExecutionId("succeeded"))
        succeeded_chunk = Chunk(order=0)
        succeeded.add_chunk(succeeded_chunk)
        succeeded.transition(Lifecycle.RUNNING)
        succeeded_chunk.transition(Lifecycle.RUNNING)
        attempt = succeeded_chunk.new_attempt()
        attempt.transition(Lifecycle.RUNNING)
        output = OutputRef("outputs/preserved.mp4")
        attempt.transition(Lifecycle.SUCCEEDED, output=output, evidence=Evidence("verified"))
        succeeded_chunk.transition(Lifecycle.SUCCEEDED)
        succeeded.transition(Lifecycle.SUCCEEDED)
        artifact = Artifact(
            project.id,
            succeeded.id,
            succeeded_chunk.id,
            attempt.id,
            Phase.OUTPUT,
            output,
        )

        failed = Execution(project.id, ExecutionId("failed"))
        failed.add_chunk(Chunk(order=0))
        failed.transition(Lifecycle.RUNNING)
        failed.transition(Lifecycle.FAILED)

        cancelled = Execution(project.id, ExecutionId("cancelled"))
        cancelled.add_chunk(Chunk(order=0))
        cancelled.transition(Lifecycle.CANCELLED)

        output_path = self.root / output.uri
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"preserve-me")
        self.repository.save(project, [succeeded, failed, cancelled], artifacts=[artifact])

        self.assertEqual(self.library.delete_project(project.id.value), project.id.value)
        self.assertTrue(output_path.exists())
        self.assertEqual(output_path.read_bytes(), b"preserve-me")
        for table, column in (
            ("projects", "id"),
            ("executions", "project_id"),
            ("artifacts", "project_id"),
            ("errors", "project_id"),
            ("transitions", "project_id"),
        ):
            self.assertEqual(
                self.repository.db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {column}=?",
                    (project.id.value,),
                ).fetchone()[0],
                0,
                table,
            )
        for table, identifier in (
            ("chunks", str(succeeded_chunk.id)),
            ("attempts", str(attempt.id)),
        ):
            column = "id"
            self.assertEqual(
                self.repository.db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {column}=?",
                    (identifier,),
                ).fetchone()[0],
                0,
                table,
            )

    def test_delete_is_atomic_when_project_has_queued_work(self):
        selection = self.draft("queued-project", "queued-execution")
        QueueOperationsUseCase(self.repository).enqueue(
            selection.project_id, selection.execution_id
        )
        before = self.durable_rows()
        original_name = self.repository.get_project_name(selection.project_id)

        with self.assertRaisesRegex(PreparationLibraryError, "live queue work"):
            self.library.delete_project(selection.project_id)

        self.assertEqual(self.durable_rows(), before)
        self.assertEqual(
            self.repository.get_project_name(selection.project_id),
            original_name,
        )

    def test_delete_blocks_running_and_pending_recovery_evidence(self):
        running = self.draft("running-project", "running-execution")
        project, executions = self.repository.load(running.project_id)
        execution = next(item for item in executions if str(item.id) == running.execution_id)
        execution.transition(Lifecycle.RUNNING)
        self.repository.save(project, [execution])
        with self.assertRaisesRegex(PreparationLibraryError, "active or recovery-relevant"):
            self.library.delete_project(running.project_id)

        recovery = self.draft("recovery-project", "recovery-execution")
        self.repository.db.execute(
            "INSERT INTO errors VALUES(?,?,?,?,?,?,?)",
            (
                "recovery-error",
                recovery.project_id,
                recovery.execution_id,
                "chunk-placeholder",
                "attempt-placeholder",
                "RECOVERY",
                "durable evidence",
            ),
        )
        before = self.durable_rows()
        with self.assertRaisesRegex(PreparationLibraryError, "active or recovery-relevant"):
            self.library.delete_project(recovery.project_id)
        self.assertEqual(self.durable_rows(), before)


if __name__ == "__main__":
    unittest.main()
