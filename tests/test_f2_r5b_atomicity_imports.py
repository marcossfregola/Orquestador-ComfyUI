import ast
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from orquestador.persistence import PersistenceError, SQLiteProjectRepository


class MigrationAtomicityTests(unittest.TestCase):
    def test_ordered_injected_migration_commits(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            repo = SQLiteProjectRepository(d)
            repo.db.execute("ALTER TABLE transitions RENAME TO transitions_v2")
            repo.db.execute("CREATE TABLE transitions(project_id TEXT,execution_id TEXT,target_chunk_id TEXT PRIMARY KEY,source_chunk_id TEXT,source_attempt_id TEXT,source_output TEXT,frame_index INTEGER,frame_count INTEGER)")
            repo.db.execute("INSERT INTO transitions SELECT project_id,execution_id,target_chunk_id,source_chunk_id,source_attempt_id,source_output,frame_index,frame_count FROM transitions_v2")
            repo.db.execute("DROP TABLE transitions_v2")
            repo.db.execute("UPDATE schema_version SET version=1")
            repo.db.commit()
            repo._run_migrations({2: lambda conn: conn.execute("CREATE TABLE future_marker(value TEXT)")}, target_version=2)
            self.assertEqual(repo.db.execute("SELECT version FROM schema_version").fetchone()[0], 2)
            self.assertIsNotNone(repo.db.execute("SELECT 1 FROM sqlite_master WHERE name='future_marker'").fetchone())
            repo.close()

    def test_failing_future_migration_rolls_back_everything(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            repo = SQLiteProjectRepository(d)
            repo.db.execute("ALTER TABLE transitions RENAME TO transitions_v2")
            repo.db.execute("CREATE TABLE transitions(project_id TEXT,execution_id TEXT,target_chunk_id TEXT PRIMARY KEY,source_chunk_id TEXT,source_attempt_id TEXT,source_output TEXT,frame_index INTEGER,frame_count INTEGER)")
            repo.db.execute("INSERT INTO transitions SELECT project_id,execution_id,target_chunk_id,source_chunk_id,source_attempt_id,source_output,frame_index,frame_count FROM transitions_v2")
            repo.db.execute("DROP TABLE transitions_v2")
            repo.db.execute("UPDATE schema_version SET version=1")
            repo.db.commit()
            repo.db.execute("INSERT INTO projects VALUES ('sentinel','{}')")
            repo.db.commit()

            def failing(conn):
                conn.execute("CREATE TABLE synthetic_table(value TEXT)")
                conn.execute("ALTER TABLE projects ADD COLUMN synthetic_column TEXT")
                conn.execute("INSERT INTO synthetic_table VALUES ('created')")
                conn.execute("UPDATE schema_version SET version=2")
                raise RuntimeError("deliberate migration failure")

            with self.assertRaises(PersistenceError):
                repo._run_migrations({2: failing}, target_version=2)
            self.assertEqual(repo.db.execute("SELECT version FROM schema_version").fetchone()[0], 1)
            self.assertEqual(repo.db.execute("SELECT defaults FROM projects WHERE id='sentinel'").fetchone()[0], "{}")
            self.assertIsNone(repo.db.execute("SELECT 1 FROM sqlite_master WHERE name='synthetic_table'").fetchone())
            self.assertNotIn("synthetic_column", [r[1] for r in repo.db.execute("PRAGMA table_info(projects)")])
            repo.close()
            repo = None
            reopened = SQLiteProjectRepository(d)
            self.assertEqual(reopened.db.execute("SELECT version FROM schema_version").fetchone()[0], 2)
            self.assertEqual(reopened.db.execute("SELECT defaults FROM projects WHERE id='sentinel'").fetchone()[0], "{}")
            reopened.close()


class ImportAuditTests(unittest.TestCase):
    def test_production_imports_are_stdlib_or_local(self):
        roots = set()
        src = Path(__file__).parents[1] / "src"
        stdlib = set(getattr(sys, "stdlib_module_names", ())) | set(sys.builtin_module_names)
        for path in src.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots.update(a.name.split('.')[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    roots.add(node.module.split('.')[0])
        self.assertEqual(roots - stdlib - {"orquestador"}, set(), sorted(roots))


if __name__ == "__main__":
    unittest.main()
