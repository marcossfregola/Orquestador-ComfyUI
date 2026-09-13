import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from orquestador.domain import (
    Chunk, DomainError, Execution, ExecutionId, Lifecycle, Project, ProjectId,
    QueueControl, QueueItem, QueueItemId, QueueItemState, editable_virgin,
)
from orquestador.persistence import CorruptDatabaseError, PersistenceConflict, SQLiteProjectRepository
from orquestador.application.prepare_gui import PrepareGuiUseCase, PreparationError


class F130DomainTests(unittest.TestCase):
    def virgin(self):
        project = Project(ProjectId('project'))
        execution = Execution(project.id, ExecutionId('execution'))
        execution.add_chunk(Chunk(order=0))
        return project, execution

    def test_editable_virgin_boundaries_and_sequence_delegate(self):
        _, execution = self.virgin()
        self.assertTrue(editable_virgin(execution))
        execution.add_chunk(Chunk(order=1))
        execution.reorder_chunks([execution.chunks[1].id, execution.chunks[0].id])
        execution.chunks[0].new_attempt()
        self.assertFalse(editable_virgin(execution))
        with self.assertRaises(DomainError):
            execution.reorder_chunks([chunk.id for chunk in execution.chunks])

    def test_queue_state_transitions_fail_closed(self):
        item = QueueItem(ExecutionId('execution'), 0, QueueItemId('queue'))
        with self.assertRaises(DomainError):
            item.transition(QueueItemState.FINISHED)
        with self.assertRaises(DomainError):
            item.transition(QueueItemState.REMOVED)
        item.transition(QueueItemState.SKIPPED, terminal_reason='operator request')
        with self.assertRaises(DomainError):
            item.transition(QueueItemState.QUEUED)
        active = QueueItem(ExecutionId('other'), 1)
        active.transition(QueueItemState.ACTIVE)
        active.transition(QueueItemState.FINISHED)
        self.assertEqual(active.state, QueueItemState.FINISHED)

    def test_queue_contract_validation(self):
        with self.assertRaises(DomainError): QueueItem(ExecutionId('e'), -1)
        with self.assertRaises(DomainError): QueueControl(paused=1)
        with self.assertRaises(DomainError): QueueItem(ExecutionId('e'), 0, created_at=datetime.now())
        with self.assertRaises(DomainError):
            QueueItem(ExecutionId('e'), 0, state=QueueItemState.FINISHED, terminal_reason='not legal')


class F130PersistenceTests(unittest.TestCase):
    def tearDown(self):
        repository = getattr(self, 'repository', None)
        if repository: repository.close()

    def virgin(self, directory, execution_id='execution'):
        project = Project(ProjectId('project'))
        execution = Execution(project.id, ExecutionId(execution_id))
        execution.add_chunk(Chunk(order=0))
        self.repository = SQLiteProjectRepository(directory)
        self.repository.save(project, [execution])
        return project, execution

    def test_v3_to_v4_preserves_existing_rows_and_creates_singleton_control(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            db = sqlite3.connect(Path(directory, 'orquestador.sqlite3'))
            db.executescript("""CREATE TABLE schema_version(version INTEGER NOT NULL); INSERT INTO schema_version VALUES(3);
CREATE TABLE projects(id TEXT PRIMARY KEY,defaults TEXT NOT NULL); CREATE TABLE executions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,defaults TEXT NOT NULL,state TEXT NOT NULL,workflow_profile_ref TEXT,execution_number INTEGER); CREATE TABLE chunks(id TEXT PRIMARY KEY,execution_id TEXT NOT NULL,ord INTEGER NOT NULL,defaults TEXT NOT NULL,state TEXT NOT NULL,UNIQUE(execution_id,ord)); CREATE TABLE attempts(id TEXT PRIMARY KEY,chunk_id TEXT NOT NULL,number INTEGER NOT NULL,state TEXT NOT NULL,output TEXT,evidence TEXT,error_id TEXT,output_artifact_id TEXT,external_job_ref TEXT); CREATE TABLE errors(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,execution_id TEXT NOT NULL,chunk_id TEXT NOT NULL,attempt_id TEXT NOT NULL,code TEXT NOT NULL,message TEXT NOT NULL); CREATE TABLE artifacts(id TEXT PRIMARY KEY,project_id TEXT,execution_id TEXT,chunk_id TEXT,attempt_id TEXT,phase TEXT,output TEXT,path TEXT); CREATE TABLE transitions(project_id TEXT,execution_id TEXT,target_chunk_id TEXT PRIMARY KEY,source_chunk_id TEXT,source_attempt_id TEXT,source_output TEXT,frame_index INTEGER,frame_count INTEGER,materialized_type TEXT,materialized_subfolder TEXT,materialized_name TEXT,materialized_source_sha256 TEXT); INSERT INTO projects VALUES('p','{}'); INSERT INTO executions VALUES('e','p','{}','pending',NULL,1);""")
            db.commit(); db.close()
            self.repository = SQLiteProjectRepository(directory)
            self.assertEqual(self.repository.load(ProjectId('p'))[1][0].id, ExecutionId('e'))
            self.assertEqual(self.repository.db.execute('SELECT version FROM schema_version').fetchone()[0], 4)
            self.assertEqual(self.repository.get_queue_control(), QueueControl())
            with self.assertRaises(sqlite3.IntegrityError):
                self.repository.db.execute("INSERT INTO queue_items VALUES('bad-finished','e',0,'finished','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00','not legal')")

    def test_roundtrip_list_and_active_control(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            _, execution = self.virgin(directory)
            item = QueueItem(execution.id, 4, QueueItemId('queue-item'))
            self.repository.save_queue_item(item)
            self.assertEqual(self.repository.get_queue_item(item.id), item)
            self.assertEqual(self.repository.list_queue_items(states=(QueueItemState.QUEUED,)), [item])
            item.transition(QueueItemState.ACTIVE)
            self.repository.save_queue_item(item)
            control = QueueControl(active_queue_item_id=item.id, revision=1)
            self.repository.save_queue_control(control)
            self.assertEqual(self.repository.get_queue_control(), control)

    def test_fk_corruption_and_ineligible_execution_fail_closed(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            _, execution = self.virgin(directory)
            self.assertRaises(PersistenceConflict, self.repository.save_queue_item, QueueItem(ExecutionId('missing'), 0))
            execution.transition(Lifecycle.RUNNING)
            self.repository.save(Project(ProjectId('project')), [execution])
            self.assertRaises(PersistenceConflict, self.repository.save_queue_item, QueueItem(execution.id, 1))
            with self.assertRaises(sqlite3.IntegrityError):
                self.repository.db.execute("INSERT INTO queue_items VALUES('bad','missing',2,'queued','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00',NULL)")

    def test_queue_row_corruption_fails_closed_on_read(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            _, execution = self.virgin(directory)
            self.repository.db.execute("INSERT INTO queue_items VALUES('corrupt',?,0,'queued','not-a-time','not-a-time',NULL)", (str(execution.id),))
            with self.assertRaises(CorruptDatabaseError): self.repository.list_queue_items()

    def test_finished_reason_is_rejected_by_schema(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            _, execution = self.virgin(directory)
            timestamp = '2026-01-01T00:00:00+00:00'
            with self.assertRaises(sqlite3.IntegrityError):
                self.repository.db.execute("INSERT INTO queue_items VALUES('corrupt',?,0,'finished',?,?,?)", (str(execution.id), timestamp, timestamp, 'not legal'))

    def test_queue_control_active_pointer_to_nonactive_item_fails_closed_on_read(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            _, execution = self.virgin(directory)
            item = QueueItem(execution.id, 0, QueueItemId('queue-item'))
            self.repository.save_queue_item(item)
            self.repository.db.execute("UPDATE queue_control SET active_queue_item_id=? WHERE singleton=1", (str(item.id),))
            with self.assertRaises(CorruptDatabaseError): self.repository.get_queue_control()

    def test_prepare_reuses_only_unqueued_virgin_execution(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            image = root / 'source.png'
            image.write_bytes(b'image')
            self.repository = SQLiteProjectRepository(directory)
            prepare = PrepareGuiUseCase(self.repository, root, lambda project_id, execution_id: {'project_id': project_id, 'execution_id': execution_id})
            initial = prepare(project_id='project', execution_id='execution', initial_image=str(image), prompts=['one', 'two'], chunk_count=2)
            result = prepare(project_id='project', initial_image=str(image), prompts=['one', 'two'], chunk_count=2)
            self.assertEqual(result['execution_id'], initial['execution_id'])

    def test_prepare_does_not_reuse_queued_virgin_execution(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            image = root / 'source.png'
            image.write_bytes(b'image')
            self.repository = SQLiteProjectRepository(directory)
            prepare = PrepareGuiUseCase(self.repository, root, lambda project_id, execution_id: {'project_id': project_id, 'execution_id': execution_id})
            initial = prepare(project_id='project', execution_id='execution', initial_image=str(image), prompts=['one', 'two'], chunk_count=2)
            self.repository.save_queue_item(QueueItem(ExecutionId(initial['execution_id']), 0))
            with self.assertRaises(PreparationError):
                prepare(project_id='project', execution_id=initial['execution_id'], initial_image=str(image), prompts=['one', 'two'], chunk_count=2)
            result = prepare(project_id='project', initial_image=str(image), prompts=['one', 'two'], chunk_count=2)
            self.assertNotEqual(result['execution_id'], initial['execution_id'])
            self.assertEqual(len(self.repository.load(ProjectId('project'))[1]), 2)

    def test_duplicate_live_and_single_active_constraints_reject(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            _, first = self.virgin(directory, 'first')
            project, second = Project(ProjectId('project')), Execution(ProjectId('project'), ExecutionId('second'))
            second.add_chunk(Chunk(order=0)); self.repository.save(project, [second])
            one = QueueItem(first.id, 0); self.repository.save_queue_item(one)
            with self.assertRaises(PersistenceConflict): self.repository.save_queue_item(QueueItem(first.id, 1))
            one.transition(QueueItemState.ACTIVE); self.repository.save_queue_item(one)
            other = QueueItem(second.id, 2); self.repository.save_queue_item(other); other.transition(QueueItemState.ACTIVE)
            with self.assertRaises(PersistenceConflict): self.repository.save_queue_item(other)
            with self.assertRaises(sqlite3.IntegrityError): self.repository.db.execute("INSERT INTO queue_control VALUES(2,0,NULL,0)")

    def test_finished_item_requires_terminal_execution(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            project, execution = self.virgin(directory)
            item = QueueItem(execution.id, 0); self.repository.save_queue_item(item)
            item.transition(QueueItemState.ACTIVE); self.repository.save_queue_item(item)
            item.transition(QueueItemState.FINISHED)
            with self.assertRaises(PersistenceConflict): self.repository.save_queue_item(item)
            execution.transition(Lifecycle.RUNNING); execution.transition(Lifecycle.CANCELLED)
            self.repository.save(project, [execution])
            self.repository.save_queue_item(item)


if __name__ == '__main__':
    unittest.main()
