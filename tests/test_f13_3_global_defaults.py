import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orquestador.application.clone_configuration import CloneConfigurationUseCase
from orquestador.application.drafts import DraftError, DraftUseCase
from orquestador.application.global_defaults import GlobalDefaultsError, GlobalDefaultsUseCase
from orquestador.domain.config import DEFAULT_PROFILE_REF, GLOBAL_DEFAULT_KEYS, GenerationConfig, GlobalDefaults
from orquestador.domain import Chunk, Execution, ExecutionId, Project, ProjectId, WorkflowProfileRef
from orquestador.persistence import SQLiteProjectRepository
from orquestador.persistence.sqlite import PersistenceDataError


class F133GlobalDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.repository = SQLiteProjectRepository(self.root)
        self.defaults = GlobalDefaultsUseCase(self.repository)
        self.drafts = DraftUseCase(self.repository)

    def tearDown(self):
        self.repository.close()
        self.temp.cleanup()

    @staticmethod
    def config(label):
        return {"initial_image": "inputs/%s.png" % label, "prompts": ("one", "two"), "chunk_count": 2}

    @staticmethod
    def chunks():
        return [{"prompt": "one"}, {"prompt": "two", "steps": 27}]

    def test_new_database_initializes_canonical_defaults_and_reopens(self):
        initial = self.defaults.read()
        self.assertEqual(initial, GlobalDefaults())
        self.assertEqual(set(initial.to_mapping()), {
            "megapixels", "length", "steps", "fps", "ref_image_size",
            "also_ref_first_frame", "first_frame_as_primary_reference", "orchestration_timeout_seconds",
        })
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.db.execute("INSERT INTO global_defaults(singleton,mapping,config_version) VALUES(2,'{}',1)")
        updated = {**initial.to_mapping(), "steps": 31}
        self.assertEqual(self.defaults.update(updated).steps, 31)
        self.repository.close()
        self.repository = SQLiteProjectRepository(self.root)
        self.defaults = GlobalDefaultsUseCase(self.repository)
        self.assertEqual(self.defaults.read().steps, 31)

    def test_schema_four_migrates_without_touching_historical_rows(self):
        legacy = self.drafts.create("legacy", defaults={"opaque": "historical"}, chunks=self.chunks(), execution_id="old")
        self.repository.close()
        db = sqlite3.connect(self.root / "orquestador.sqlite3")
        # Simulate an execution persisted before F13.3: the migration must
        # create only the singleton defaults row and never rewrite this row.
        db.execute("UPDATE executions SET defaults=? WHERE id=?", (json.dumps({"opaque": "historical"}), legacy.execution_id))
        db.execute("DROP TABLE global_defaults")
        db.execute("DROP TABLE technical_presets")
        db.execute("DROP TABLE chunk_templates")
        db.execute("UPDATE schema_version SET version=4")
        db.commit(); db.close()
        self.repository = SQLiteProjectRepository(self.root)
        self.drafts = DraftUseCase(self.repository)
        self.assertEqual(self.defaults.__class__(self.repository).read(), GlobalDefaults())
        self.assertEqual(self.drafts.reopen("legacy", legacy.execution_id).defaults, {"opaque": "historical"})

    def test_validation_is_fail_closed_without_partial_persistence(self):
        before = self.defaults.read()
        cases = (
            {"bad": 1},
            {**before.to_mapping(), "steps": True},
            {**before.to_mapping(), "also_ref_first_frame": True, "first_frame_as_primary_reference": True},
        )
        for mapping in cases:
            with self.subTest(mapping=mapping):
                with self.assertRaises(GlobalDefaultsError):
                    self.defaults.update(mapping)
                self.assertEqual(self.defaults.read(), before)
        self.repository.db.execute("UPDATE global_defaults SET config_version=2")
        with self.assertRaises(PersistenceDataError):
            self.repository.load_global_defaults()

    def test_creation_snapshot_precedence_nonretroactivity_and_chunk_override(self):
        old = self.drafts.create("p", defaults=self.config("old"), chunks=self.chunks(), execution_id="old")
        changed = {**self.defaults.read().to_mapping(), "steps": 31, "fps": 12}
        self.defaults.update(changed)
        fresh = self.drafts.create("p", defaults=self.config("fresh"), chunks=self.chunks(), execution_id="fresh")
        self.assertEqual(old.defaults["steps"], GlobalDefaults().steps)
        self.assertEqual(fresh.defaults["steps"], 31)
        self.assertEqual(fresh.defaults["fps"], 12)
        self.assertEqual(fresh.chunks[1]["steps"], 27)
        self.defaults.update({**changed, "steps": 42})
        self.assertEqual(self.drafts.reopen("p", fresh.execution_id).defaults["steps"], 31)

    def test_empty_defaults_materialize_global_snapshot_and_workflow_profile(self):
        changed = {**self.defaults.read().to_mapping(), "steps": 31}
        self.defaults.update(changed)
        created = self.drafts.create("p", defaults={}, chunks=self.chunks(), execution_id="empty")
        project, executions = self.repository.load(ProjectId("p"))
        execution = next(item for item in executions if str(item.id) == created.execution_id)
        self.assertEqual({key: created.defaults[key] for key in GLOBAL_DEFAULT_KEYS}, changed)
        self.assertEqual(created.defaults["profile_ref"], DEFAULT_PROFILE_REF)
        self.assertEqual(execution.workflow_profile_ref.value, DEFAULT_PROFILE_REF)

    def test_opaque_defaults_materialize_globals_and_remain_nonretroactive(self):
        created = self.drafts.create("p", defaults={"label": "opaque"}, chunks=self.chunks(), execution_id="opaque")
        self.assertEqual(created.defaults["label"], "opaque")
        self.assertEqual({key: created.defaults[key] for key in GLOBAL_DEFAULT_KEYS}, GlobalDefaults().to_mapping())
        changed = {**self.defaults.read().to_mapping(), "steps": 31}
        self.defaults.update(changed)
        self.assertEqual(self.drafts.reopen("p", created.execution_id).defaults["steps"], GlobalDefaults().steps)

    def test_opaque_metadata_with_profile_ref_materializes_globals(self):
        created = self.drafts.create(
            "p", defaults={"label": "opaque", "profile_ref": DEFAULT_PROFILE_REF},
            chunks=self.chunks(), execution_id="opaque-profile",
        )
        project, executions = self.repository.load(ProjectId("p"))
        execution = next(item for item in executions if str(item.id) == created.execution_id)
        self.assertEqual(created.defaults["label"], "opaque")
        self.assertEqual({key: created.defaults[key] for key in GLOBAL_DEFAULT_KEYS}, GlobalDefaults().to_mapping())
        self.assertEqual(created.defaults["profile_ref"], DEFAULT_PROFILE_REF)
        self.assertEqual(execution.workflow_profile_ref.value, DEFAULT_PROFILE_REF)

    def test_opaque_unsupported_profile_fails_closed(self):
        with self.assertRaises(DraftError):
            self.drafts.create(
                "p", defaults={"label": "opaque", "profile_ref": "unsupported"},
                chunks=self.chunks(), execution_id="bad-profile",
            )
        self.assertEqual(self.repository.list_project_ids(), [])

    def test_partial_technical_override_materializes_without_generation_shape(self):
        created = self.drafts.create(
            "p", defaults={"label": "partial", "steps": 31},
            chunks=self.chunks(), execution_id="partial-technical",
        )
        expected = {**GlobalDefaults().to_mapping(), "steps": 31}
        self.assertEqual(created.defaults["label"], "partial")
        self.assertEqual({key: created.defaults[key] for key in GLOBAL_DEFAULT_KEYS}, expected)
        self.assertEqual(created.defaults["profile_ref"], DEFAULT_PROFILE_REF)

    def test_partial_technical_conflict_fails_closed(self):
        with self.assertRaises(DraftError):
            self.drafts.create(
                "p", defaults={"also_ref_first_frame": True, "first_frame_as_primary_reference": True},
                chunks=self.chunks(), execution_id="bad-partial-technical",
            )
        self.assertEqual(self.repository.list_project_ids(), [])

    def test_clone_copies_source_snapshot_without_global_lookup(self):
        inputs = self.root / "inputs"
        inputs.mkdir()
        (inputs / "initial.png").write_bytes(b"initial")
        project = Project(ProjectId("source"))
        generation = GenerationConfig(
            initial_image="inputs/initial.png", prompts=("one", "two"),
            chunk_count=2, steps=22,
        )
        source = Execution(
            project.id, ExecutionId("source-execution"), generation.to_mapping(),
            workflow_profile_ref=WorkflowProfileRef(generation.profile_ref),
        )
        source.add_chunk(Chunk(order=0, defaults={"prompt": "one"}))
        source.add_chunk(Chunk(order=1, defaults={"prompt": "two"}))
        self.repository.save(project, [source])
        self.defaults.update({**self.defaults.read().to_mapping(), "steps": 31})
        with patch.object(self.repository, "load_global_defaults", side_effect=AssertionError("clone consulted globals")) as read:
            cloned = CloneConfigurationUseCase(self.repository)(str(project.id), str(source.id))
        read.assert_not_called()
        _, executions = self.repository.load(ProjectId(cloned.project_id))
        self.assertEqual(executions[0].defaults["steps"], 22)

    def test_complete_configuration_preserves_valid_opaque_metadata(self):
        self.defaults.update({**self.defaults.read().to_mapping(), "steps": 31})
        created = self.drafts.create(
            "p", defaults={**self.config("metadata"), "label": "kept", "opaque": {"kind": "metadata"}},
            chunks=self.chunks(), execution_id="complete-metadata",
        )
        self.assertEqual(created.defaults["label"], "kept")
        self.assertEqual(created.defaults["opaque"], {"kind": "metadata"})
        self.assertEqual(created.defaults["steps"], 31)

    def test_creation_precedence_is_base_then_globals_then_explicit_then_chunk(self):
        self.repository.save(Project(ProjectId("p"), defaults={"steps": 26, "fps": 30}), [])
        self.defaults.update({**self.defaults.read().to_mapping(), "steps": 31, "fps": 12})
        created = self.drafts.create(
            "p", defaults={**self.config("precedence"), "steps": 29}, chunks=self.chunks(), execution_id="precedence"
        )
        self.assertEqual(created.defaults["steps"], 29)
        self.assertEqual(created.defaults["fps"], 12)
        self.assertEqual(created.chunks[1]["steps"], 27)

    def test_creation_rollback_leaves_no_execution(self):
        self.repository.db.execute("CREATE TRIGGER reject_f133 BEFORE INSERT ON chunks BEGIN SELECT RAISE(ABORT, 'forced'); END")
        with self.assertRaises(Exception):
            self.drafts.create("p", defaults=self.config("bad"), chunks=self.chunks())
        self.assertEqual(self.repository.list_project_ids(), [])


if __name__ == "__main__":
    unittest.main()
