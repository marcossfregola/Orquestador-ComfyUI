import sqlite3
import tempfile
import unittest
from pathlib import Path
from uuid import UUID

from orquestador.application.clone_configuration import CloneConfigurationUseCase
from orquestador.application.drafts import DraftUseCase
from orquestador.application.preparation_library import (
    PreparationLibraryError,
    PreparationLibraryUseCase,
)
from orquestador.application.queue_dashboard import QueueDashboardUseCase
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
    TransitionFrame,
    WorkflowProfileRef,
)
from orquestador.domain.config import GenerationConfig
from orquestador.persistence import SQLiteProjectRepository


class F141ProjectNameTests(unittest.TestCase):
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

    def cloneable_source(self, project_id="clone-source", execution_id="source-execution"):
        inputs = self.root / "inputs"
        inputs.mkdir(exist_ok=True)
        (inputs / "source.png").write_bytes(b"source image")
        config = GenerationConfig(
            initial_image="inputs/source.png",
            references=(),
            prompts=("one", "two"),
            chunk_count=2,
        )
        project = Project(ProjectId(project_id), name="Source")
        execution = Execution(
            project.id,
            ExecutionId(execution_id),
            config.to_mapping(),
            workflow_profile_ref=WorkflowProfileRef(config.profile_ref),
        )
        execution.add_chunk(Chunk(order=0, defaults={"prompt": "one"}))
        execution.add_chunk(Chunk(order=1, defaults={"prompt": "two"}))
        self.repository.save(project, [execution])
        return project, execution

    def test_named_creation_is_normalized_unique_and_survives_reopen(self):
        selection = self.library.create_named_draft("  Cafe\u0301  ")
        self.assertEqual(selection.project_name, "Café")
        self.assertEqual(str(UUID(selection.project_id)), selection.project_id)
        self.assertNotEqual(selection.project_id, "Café")
        self.assertEqual(self.repository.get_project_name(selection.project_id), "Café")
        with self.assertRaisesRegex(PreparationLibraryError, "name conflict"):
            self.library.create_named_draft("CAFÉ")

        self.repository.close()
        self.repository = SQLiteProjectRepository(self.root)
        self.library = PreparationLibraryUseCase(self.repository)
        project, executions = self.repository.load(selection.project_id)
        self.assertEqual(project.name, "Café")
        self.assertEqual([str(item.id) for item in executions], [selection.execution_id])
        snapshot = self.library.snapshot()
        self.assertEqual(snapshot.projects[0].name, "Café")
        self.assertEqual(snapshot.projects[0].executions[0].project_name, "Café")

    def test_rename_only_changes_durable_name_across_queue_and_history(self):
        self.draft("stable-id", "draft-execution")
        queued = self.draft("stable-id", "queued-execution")
        active = self.draft("stable-id", "active-execution")
        terminal = self.draft("stable-id", "terminal-execution")
        operations = QueueOperationsUseCase(self.repository)
        operations.enqueue("stable-id", queued.execution_id)
        operations.enqueue("stable-id", active.execution_id)
        claimed = self.repository.claim_next_queue_item()
        self.assertEqual(str(claimed.item.execution_id), queued.execution_id)

        project, executions = self.repository.load("stable-id")
        active_execution = next(item for item in executions if str(item.id) == queued.execution_id)
        active_execution.transition(Lifecycle.RUNNING)
        self.repository.save(project, [active_execution])

        project, executions = self.repository.load("stable-id")
        terminal_execution = next(item for item in executions if str(item.id) == terminal.execution_id)
        terminal_execution.transition(Lifecycle.RUNNING)
        for chunk in terminal_execution.chunks:
            chunk.transition(Lifecycle.RUNNING)
            attempt = chunk.new_attempt()
            attempt.transition(Lifecycle.RUNNING)
        self.repository.save(project, [terminal_execution])
        artifacts = []
        for chunk in terminal_execution.chunks:
            attempt = chunk.attempts[0]
            output = OutputRef(f"outputs/{chunk.order}.mp4")
            attempt.transition(Lifecycle.SUCCEEDED, output=output, evidence=Evidence("verified"))
            chunk.transition(Lifecycle.SUCCEEDED)
            artifacts.append(
                Artifact(project.id, terminal_execution.id, chunk.id, attempt.id, Phase.OUTPUT, output)
            )
        terminal_execution.transition(Lifecycle.SUCCEEDED)
        transition = TransitionFrame(
            project.id,
            terminal_execution.id,
            terminal_execution.chunks[0].id,
            terminal_execution.chunks[0].attempts[0].id,
            terminal_execution.chunks[0].attempts[0].output,
            9,
            10,
            terminal_execution.chunks[1].id,
        )
        self.repository.save(project, [terminal_execution], artifacts=artifacts, transitions=[transition])

        preserved_tables = (
            "executions",
            "chunks",
            "attempts",
            "artifacts",
            "errors",
            "transitions",
            "queue_items",
            "queue_control",
        )
        before = {
            table: self.repository.db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in preserved_tables
        }
        original_ids = [str(item) for item in self.repository.list_project_ids()]
        stale_project, _ = self.repository.load("stable-id")

        self.assertEqual(self.repository.rename_project("stable-id", " Proyecto nuevo "), "Proyecto nuevo")
        self.assertEqual(self.repository.get_project_name("stable-id"), "Proyecto nuevo")
        self.repository.save(stale_project, [])
        self.assertEqual(self.repository.get_project_name("stable-id"), "Proyecto nuevo")
        after = {
            table: self.repository.db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in preserved_tables
        }
        self.assertEqual(after, before)
        self.assertEqual([str(item) for item in self.repository.list_project_ids()], original_ids)

        dashboard = QueueDashboardUseCase(self.repository).snapshot()
        self.assertEqual({entry.project_name for entry in dashboard.entries}, {"Proyecto nuevo"})
        self.repository.close()
        self.repository = SQLiteProjectRepository(self.root)
        self.assertEqual(self.repository.load("stable-id")[0].name, "Proyecto nuevo")
        self.assertEqual(
            [item.execution_number for item in self.repository.load("stable-id")[1]],
            [1, 2, 3, 4],
        )

    def test_normalized_rename_conflict_is_atomic(self):
        first = self.library.create_named_draft("Mañana")
        second = self.library.create_named_draft("Tarde")
        with self.assertRaisesRegex(PreparationLibraryError, "name conflict"):
            self.library.rename_project(second.project_id, "MAN\u0303ANA")
        self.assertEqual(self.repository.get_project_name(first.project_id), "Mañana")
        self.assertEqual(self.repository.get_project_name(second.project_id), "Tarde")
        self.library.rename_project(second.project_id, "  Noche  ")
        self.assertEqual(self.repository.get_project_name(second.project_id), "Noche")

    def test_schema_seven_migration_preserves_ids_evidence_and_resolves_collisions(self):
        project = Project(ProjectId("legacy-visible"), name="Legacy visible")
        execution = Execution(project.id, ExecutionId("historic-execution"))
        execution.add_chunk(Chunk(order=0))
        execution.transition(Lifecycle.RUNNING)
        chunk = execution.chunks[0]
        chunk.transition(Lifecycle.RUNNING)
        attempt = chunk.new_attempt()
        attempt.transition(Lifecycle.RUNNING)
        output = OutputRef("outputs/historic.mp4")
        attempt.transition(Lifecycle.SUCCEEDED, output=output, evidence=Evidence("historic"))
        chunk.transition(Lifecycle.SUCCEEDED)
        execution.transition(Lifecycle.SUCCEEDED)
        artifact = Artifact(project.id, execution.id, chunk.id, attempt.id, Phase.OUTPUT, output)
        self.repository.save(project, [execution], artifacts=[artifact])

        generated_uuid = "12345678-0000-4000-8000-000000000001"
        for project_id, name in (
            (generated_uuid, "old uuid label"),
            ("Proyecto generado 12345678", "old colliding label"),
            ("CASE", "old uppercase label"),
            ("case", "old lowercase label"),
        ):
            self.repository.save(Project(ProjectId(project_id), name=name), [])
        before_evidence = {
            table: self.repository.db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in ("executions", "chunks", "attempts", "artifacts", "errors", "transitions")
        }
        self.repository.close()

        db = sqlite3.connect(self.root / "orquestador.sqlite3")
        db.execute("DROP INDEX projects_name_key_unique")
        db.execute("ALTER TABLE projects DROP COLUMN name_key")
        db.execute("ALTER TABLE projects DROP COLUMN name")
        db.execute("UPDATE schema_version SET version=7")
        db.commit()
        db.close()

        self.repository = SQLiteProjectRepository(self.root)
        self.assertEqual(self.repository.db.execute("SELECT version FROM schema_version").fetchone()[0], 8)
        ids = {str(project_id) for project_id in self.repository.list_project_ids()}
        self.assertEqual(ids, {"legacy-visible", generated_uuid, "Proyecto generado 12345678", "CASE", "case"})
        names = {project.id.value: project.name for project in self.repository.list_projects()}
        self.assertEqual(names["legacy-visible"], "legacy-visible")
        self.assertEqual(names[generated_uuid], "Proyecto generado 12345678")
        self.assertEqual(names["Proyecto generado 12345678"], "Proyecto generado 12345678 (2)")
        self.assertEqual(names["CASE"], "CASE")
        self.assertEqual(names["case"], "case (2)")
        self.assertEqual(
            {
                table: self.repository.db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                for table in before_evidence
            },
            before_evidence,
        )
        name_keys = [row[0] for row in self.repository.db.execute("SELECT name_key FROM projects")]
        self.assertEqual(len(name_keys), len(set(name_keys)))

    def test_clone_names_are_durable_and_autosuffix_for_both_clone_routes(self):
        inputs = self.root / "inputs"
        inputs.mkdir()
        (inputs / "initial.png").write_bytes(b"initial")
        config = GenerationConfig(
            initial_image="inputs/initial.png",
            references=(),
            prompts=("one", "two"),
            chunk_count=2,
        )
        source_project = Project(ProjectId("source-id"), name="Playa")
        source_execution = Execution(
            source_project.id,
            ExecutionId("source-execution"),
            config.to_mapping(),
            workflow_profile_ref=WorkflowProfileRef(config.profile_ref),
        )
        source_execution.add_chunk(Chunk(order=0, defaults={"prompt": "one"}))
        source_execution.add_chunk(Chunk(order=1, defaults={"prompt": "two"}))
        self.repository.save(source_project, [source_execution])

        clone = CloneConfigurationUseCase(self.repository)
        expected_names = (
            "Copia de Playa",
            "Copia de Playa (2)",
            "Copia de Playa (3)",
        )
        for expected in expected_names:
            result = clone("source-id", "source-execution")
            cloned_project, executions = self.repository.load(result.project_id)
            self.assertEqual(cloned_project.name, expected)
            self.assertEqual(len(executions), 1)
            self.assertFalse(executions[0].artifacts or executions[0].errors)

        operations = QueueOperationsUseCase(self.repository)
        queued = operations.enqueue("source-id", "source-execution")
        queued_clone = operations.duplicate(queued.id)
        self.assertEqual(self.repository.load(queued_clone.project_id)[0].name, "Copia de Playa (4)")
        dashboard = QueueDashboardUseCase(self.repository).snapshot()
        cloned_entry = next(entry for entry in dashboard.entries if entry.execution_id == queued_clone.execution_id)
        self.assertEqual(cloned_entry.project_name, "Copia de Playa (4)")

    def test_library_clone_persists_the_explicit_name_and_preserves_source(self):
        project, source = self.cloneable_source()
        source_before = self.repository.load(project.id)
        project_ids_before = {str(item) for item in self.repository.list_project_ids()}

        clone = self.library.clone(
            str(project.id), str(source.id), target_name="Playa noche"
        )

        self.assertEqual(self.repository.get_project_name(clone.project_id), "Playa noche")
        self.assertNotIn(clone.project_id, project_ids_before)
        self.assertNotEqual(clone.project_id, str(project.id))
        self.assertNotEqual(clone.execution_id, str(source.id))
        self.assertEqual(self.repository.load(project.id), source_before)
        clone_project, clone_executions = self.repository.load(clone.project_id)
        self.assertEqual(clone_project.name, "Playa noche")
        self.assertEqual(len(clone_executions), 1)
        self.assertNotEqual(
            [str(chunk.id) for chunk in clone_executions[0].chunks],
            [str(chunk.id) for chunk in source.chunks],
        )
        self.repository.close()
        self.repository = SQLiteProjectRepository(self.root)
        names = {project.name for project in self.repository.list_projects()}
        self.assertEqual(names, {"Source", "Playa noche"})

    def test_explicit_clone_name_conflict_is_atomic(self):
        project, source = self.cloneable_source()
        occupied = self.library.create_named_draft("Tarde")
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
        )
        before = {
            table: self.repository.db.execute(
                f"SELECT * FROM {table} ORDER BY rowid"
            ).fetchall()
            for table in tables
        }

        with self.assertRaisesRegex(PreparationLibraryError, "project name conflict"):
            self.library.clone(
                str(project.id), str(source.id), target_name="  TARDE  "
            )

        after = {
            table: self.repository.db.execute(
                f"SELECT * FROM {table} ORDER BY rowid"
            ).fetchall()
            for table in tables
        }
        self.assertEqual(after, before)
        self.assertFalse(self.repository.db.in_transaction)
        self.assertEqual(self.repository.get_project_name(occupied.project_id), "Tarde")


if __name__ == "__main__":
    unittest.main()
