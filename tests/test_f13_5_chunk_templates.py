import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orquestador.application.chunk_templates import (
    ChunkTemplateError,
    ChunkTemplatesUseCase,
)
from orquestador.application.clone_configuration import CloneConfigurationUseCase
from orquestador.application.drafts import DraftUseCase
from orquestador.application.global_defaults import GlobalDefaultsUseCase
from orquestador.application.technical_presets import TechnicalPresetsUseCase
from orquestador.domain import ExecutionId, Lifecycle, ProjectId
from orquestador.domain.config import GenerationConfig, GlobalDefaults
from orquestador.persistence import SQLiteProjectRepository


class F135ChunkTemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.repo = SQLiteProjectRepository(self.root)
        self.templates = ChunkTemplatesUseCase(self.repo)
        self.drafts = DraftUseCase(self.repo)

    def tearDown(self):
        self.repo.close()
        self.temp.cleanup()

    def draft(self, execution_id="draft"):
        return self.drafts.create(
            "p",
            execution_id=execution_id,
            defaults={"label": "opaque", "profile_ref": "minimax-h3-ui"},
            chunks=[{"prompt": "old one", "steps": 29}, {"prompt": "old two", "fps": 12}],
        )

    def full_draft(self, execution_id="full", *, include_chunk_metadata=True):
        chunks = [
            {"prompt": "old one", "steps": 29},
            {"prompt": "old two", "fps": 12},
        ]
        if include_chunk_metadata:
            chunks[0]["chunk_metadata"] = "left"
            chunks[1]["chunk_metadata"] = "right"
        return self.drafts.create(
            "full",
            execution_id=execution_id,
            defaults={
                "initial_image": "inputs/source.png",
                "references": ("inputs/reference.png",),
                "prompts": ("old one", "old two"),
                "chunk_count": 2,
                "profile_ref": "minimax-h3-ui",
                "label": "opaque",
                "metadata": {"preserve": True},
            },
            chunks=chunks,
        )

    def test_exact_shape_names_crud_duplicate_and_reopen(self):
        for bad in ("one, two", {"one": "two"}, (), ("one",), ("one", "  ")):
            with self.subTest(bad=bad):
                with self.assertRaises(ChunkTemplateError):
                    self.templates.create("bad", bad)
        with self.assertRaises(ChunkTemplateError):
            self.templates.create("  ", ("one", "two"))

        first = self.templates.create(
            "  Caf\u00e9  ", ("first", "second", "third"), template_id="opaque-id"
        )
        self.assertEqual(first.name, "Caf\u00e9")
        self.assertEqual(first.id, "opaque-id")
        self.assertEqual(first.prompts, ("first", "second", "third"))
        with self.assertRaises(ChunkTemplateError):
            self.templates.create("CAFE\u0301", ("other", "template"))
        other = self.templates.create("Other", ("other one", "other two"))
        with self.assertRaises(ChunkTemplateError):
            self.templates.rename(first.id, "OTHER")
        self.assertEqual(self.templates.read(first.id).name, "Caf\u00e9")

        changed = self.templates.update(first.id, ("new first", "new second"))
        renamed = self.templates.rename(first.id, " Fast ")
        copied = self.templates.duplicate(
            first.id, " Copy ", new_template_id="copy-id"
        )
        self.assertEqual(changed.prompts, ("new first", "new second"))
        self.assertEqual(renamed.name, "Fast")
        self.assertEqual(copied.prompts, ("new first", "new second"))
        self.assertGreaterEqual(changed.updated_at, changed.created_at)
        with self.assertRaises(ChunkTemplateError):
            self.templates.update(first.id, ("only one",))
        self.assertEqual(self.templates.read(first.id).prompts, ("new first", "new second"))

        self.repo.close()
        self.repo = SQLiteProjectRepository(self.root)
        self.templates = ChunkTemplatesUseCase(self.repo)
        self.assertEqual(self.templates.read("opaque-id").name, "Fast")
        self.assertEqual(self.templates.read("copy-id").prompts, ("new first", "new second"))
        self.templates.delete("opaque-id")
        self.templates.delete("copy-id")
        self.assertEqual([(item.id, item.name) for item in self.templates.list()], [(other.id, "Other")])

    def test_apply_by_copy_replaces_only_prompt_plan_and_is_nonretroactive(self):
        template = self.templates.create("story", ("new one", "new two", "new three"))
        created = self.full_draft()
        before_defaults = dict(created.defaults)
        _, before_executions = self.repo.load(ProjectId("full"))
        before_chunk_ids = [
            str(chunk.id)
            for chunk in next(
                item for item in before_executions if str(item.id) == created.execution_id
            ).chunks
        ]

        with patch.object(
            self.repo, "load_global_defaults", side_effect=AssertionError("apply consulted globals")
        ), patch.object(
            self.repo, "list_technical_presets", side_effect=AssertionError("apply consulted presets")
        ), patch.object(
            self.repo, "get_technical_preset", side_effect=AssertionError("apply consulted presets")
        ):
            applied = self.templates.apply(template.id, "full", created.execution_id)

        expected_defaults = {
            **before_defaults,
            "chunk_count": 3,
            "prompts": ["new one", "new two", "new three"],
        }
        self.assertEqual(applied.defaults, expected_defaults)
        self.assertEqual(
            applied.chunks,
            (
                {"prompt": "new one", "steps": 29, "chunk_metadata": "left"},
                {"prompt": "new two", "fps": 12, "chunk_metadata": "right"},
                {"prompt": "new three"},
            ),
        )
        self.assertEqual(applied.defaults["initial_image"], "inputs/source.png")
        self.assertEqual(applied.defaults["references"], ["inputs/reference.png"])
        self.assertEqual(applied.defaults["label"], "opaque")
        self.assertEqual(applied.defaults["metadata"], {"preserve": True})
        self.assertEqual(
            GenerationConfig.from_mapping(applied.defaults, strict=False).prompts,
            ("new one", "new two", "new three"),
        )
        self.assertNotIn("template_id", applied.defaults)
        self.assertNotIn("chunk_template_id", applied.defaults)

        _, executions = self.repo.load(ProjectId("full"))
        execution = next(item for item in executions if str(item.id) == created.execution_id)
        self.assertEqual(execution.workflow_profile_ref.value, "minimax-h3-ui")
        self.assertEqual([chunk.order for chunk in execution.chunks], [0, 1, 2])
        self.assertEqual([str(chunk.id) for chunk in execution.chunks[:2]], before_chunk_ids)
        self.assertEqual(len({str(chunk.id) for chunk in execution.chunks}), 3)

        self.templates.update(template.id, ("changed", "source"))
        self.templates.delete(template.id)
        reopened = self.drafts.reopen("full", created.execution_id)
        self.assertEqual(reopened.defaults, expected_defaults)
        self.assertEqual(reopened.chunks, applied.chunks)

    def test_apply_can_shrink_the_durable_sequence_without_orphan_chunks(self):
        expanding = self.templates.create("long", ("one", "two", "three"))
        shrinking = self.templates.create("short", ("new one", "new two"))
        created = self.full_draft()
        expanded = self.templates.apply(expanding.id, "full", created.execution_id)
        _, expanded_executions = self.repo.load(ProjectId("full"))
        expanded_ids = [
            str(chunk.id)
            for chunk in next(
                item for item in expanded_executions if str(item.id) == created.execution_id
            ).chunks
        ]

        shrunk = self.templates.apply(shrinking.id, "full", created.execution_id)
        self.assertEqual(shrunk.defaults["chunk_count"], 2)
        self.assertEqual(shrunk.defaults["prompts"], ["new one", "new two"])
        self.assertEqual(shrunk.chunks, (
            {"prompt": "new one", "steps": 29, "chunk_metadata": "left"},
            {"prompt": "new two", "fps": 12, "chunk_metadata": "right"},
        ))
        _, executions = self.repo.load(ProjectId("full"))
        execution = next(item for item in executions if str(item.id) == created.execution_id)
        self.assertEqual([str(chunk.id) for chunk in execution.chunks], expanded_ids[:2])
        self.assertEqual(
            self.repo.db.execute("SELECT count(*) FROM chunks WHERE execution_id=?", (created.execution_id,)).fetchone()[0],
            2,
        )

    def test_apply_rejects_live_queue_runtime_evidence_and_missing_ids(self):
        template = self.templates.create("story", ("one", "two"))
        queued = self.draft("queued")
        self.repo.db.execute(
            "INSERT INTO queue_items VALUES('q',?,0,'queued','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00',NULL)",
            (queued.execution_id,),
        )
        with self.assertRaises(ChunkTemplateError):
            self.templates.apply(template.id, "p", queued.execution_id)

        runtime = self.draft("runtime")
        project, executions = self.repo.load(ProjectId("p"))
        execution = next(item for item in executions if str(item.id) == runtime.execution_id)
        execution.transition(Lifecycle.RUNNING)
        execution.chunks[0].new_attempt()
        self.repo.save(project, [execution])
        with self.assertRaises(ChunkTemplateError):
            self.templates.apply(template.id, "p", runtime.execution_id)
        for template_id, project_id, execution_id in (
            ("missing", "p", runtime.execution_id),
            (template.id, "missing", runtime.execution_id),
            (template.id, "p", "missing"),
            ("   ", "p", runtime.execution_id),
        ):
            with self.subTest(template_id=template_id, project_id=project_id, execution_id=execution_id):
                with self.assertRaises(ChunkTemplateError):
                    self.templates.apply(template_id, project_id, execution_id)

    def test_schema_six_to_seven_preserves_globals_presets_and_historical_execution(self):
        globals_mapping = {**GlobalDefaults().to_mapping(), "steps": 31}
        GlobalDefaultsUseCase(self.repo).update(globals_mapping)
        preset = TechnicalPresetsUseCase(self.repo).create("technical", globals_mapping)
        history = self.full_draft("history")
        history_snapshot = (dict(history.defaults), history.chunks)

        self.repo.close()
        db = sqlite3.connect(self.root / "orquestador.sqlite3")
        db.execute("DROP TABLE chunk_templates")
        db.execute("UPDATE schema_version SET version=6")
        db.commit()
        db.close()

        self.repo = SQLiteProjectRepository(self.root)
        self.templates = ChunkTemplatesUseCase(self.repo)
        self.drafts = DraftUseCase(self.repo)
        self.assertEqual(self.repo.db.execute("SELECT version FROM schema_version").fetchone()[0], 7)
        self.assertEqual(
            [row[1] for row in self.repo.db.execute("PRAGMA table_info(chunk_templates)")],
            ["id", "name", "name_key", "prompts", "template_version", "created_at", "updated_at"],
        )
        self.assertEqual(self.repo.load_global_defaults().to_mapping(), globals_mapping)
        self.assertEqual(TechnicalPresetsUseCase(self.repo).read(preset.id).mapping, globals_mapping)
        reopened = self.drafts.reopen("full", history.execution_id)
        self.assertEqual((dict(reopened.defaults), reopened.chunks), history_snapshot)
        self.assertEqual(self.templates.list(), ())

    def test_durable_corruption_and_future_template_version_fail_closed(self):
        timestamp = "2026-01-01T00:00:00+00:00"
        valid = json.dumps(["one", "two"], separators=(",", ":"))
        cases = (
            (sqlite3.Binary(b"id"), "valid", "valid", valid, 1, timestamp, timestamp),
            ("", "valid", "valid", valid, 1, timestamp, timestamp),
            ("   ", "valid", "valid", valid, 1, timestamp, timestamp),
            ("id", "", "", valid, 1, timestamp, timestamp),
            ("id", " padded ", "padded", valid, 1, timestamp, timestamp),
            ("id", "Cafe\u0301", "caf\u00e9", valid, 1, timestamp, timestamp),
            ("id", "valid", "wrong", valid, 1, timestamp, timestamp),
            ("id", "valid", "valid", "{}", 1, timestamp, timestamp),
            ("id", "valid", "valid", json.dumps(["only one"]), 1, timestamp, timestamp),
            ("id", "valid", "valid", json.dumps(["one", "  "]), 1, timestamp, timestamp),
            ("id", "valid", "valid", valid, 2, timestamp, timestamp),
            ("id", "valid", "valid", valid, 1, "invalid", timestamp),
            ("id", "valid", "valid", valid, 1, "2026-01-01T00:00:00", timestamp),
            ("id", "valid", "valid", valid, 1, "2026-01-01T00:00:00+01:00", timestamp),
            ("id", "valid", "valid", valid, 1, "2026-01-02T00:00:00+00:00", timestamp),
        )
        for row in cases:
            with self.subTest(row=row):
                self.repo.db.execute("DELETE FROM chunk_templates")
                self.repo.db.execute("PRAGMA ignore_check_constraints=ON")
                self.repo.db.execute("INSERT INTO chunk_templates VALUES(?,?,?,?,?,?,?)", row)
                self.repo.db.execute("PRAGMA ignore_check_constraints=OFF")
                with self.assertRaises(ChunkTemplateError):
                    self.templates.list()

    def test_transaction_rollbacks_leave_templates_and_drafts_unchanged(self):
        first = self.templates.create("first", ("one", "two"))
        self.repo.db.execute(
            "CREATE TRIGGER reject_template BEFORE INSERT ON chunk_templates "
            "WHEN NEW.name='blocked' BEGIN SELECT RAISE(ABORT,'forced'); END"
        )
        with self.assertRaises(ChunkTemplateError):
            self.templates.create("blocked", ("three", "four"))
        self.assertEqual([(item.id, item.name) for item in self.templates.list()], [(first.id, "first")])

        expanding = self.templates.create("expand", ("a", "b", "c"))
        draft = self.draft("rollback")
        before = self.drafts.reopen("p", draft.execution_id)
        self.repo.db.execute(
            "CREATE TRIGGER reject_template_apply BEFORE INSERT ON chunks "
            "WHEN NEW.execution_id='rollback' AND NEW.ord=2 "
            "BEGIN SELECT RAISE(ABORT,'forced'); END"
        )
        with self.assertRaises(ChunkTemplateError):
            self.templates.apply(expanding.id, "p", draft.execution_id)
        self.assertEqual(self.drafts.reopen("p", draft.execution_id), before)

    def test_draft_creation_and_clone_never_look_up_templates(self):
        with patch.object(
            self.repo, "list_chunk_templates", side_effect=AssertionError("draft consulted templates")
        ), patch.object(
            self.repo, "get_chunk_template", side_effect=AssertionError("draft consulted templates")
        ):
            self.draft("no-template")

        inputs = self.root / "inputs"
        inputs.mkdir()
        (inputs / "source.png").write_bytes(b"source")
        (inputs / "reference.png").write_bytes(b"reference")
        source = self.full_draft("source", include_chunk_metadata=False)
        with patch.object(
            self.repo, "list_chunk_templates", side_effect=AssertionError("clone consulted templates")
        ), patch.object(
            self.repo, "get_chunk_template", side_effect=AssertionError("clone consulted templates")
        ):
            CloneConfigurationUseCase(self.repo)("full", source.execution_id)

    def test_clone_copies_an_applied_template_snapshot_without_template_lookup(self):
        inputs = self.root / "inputs"
        inputs.mkdir()
        (inputs / "source.png").write_bytes(b"source")
        (inputs / "reference.png").write_bytes(b"reference")
        source = self.full_draft("applied-source", include_chunk_metadata=False)
        template = self.templates.create("three", ("one", "two", "three"))
        applied = self.templates.apply(template.id, "full", source.execution_id)

        with patch.object(
            self.repo, "list_chunk_templates", side_effect=AssertionError("clone consulted templates")
        ), patch.object(
            self.repo, "get_chunk_template", side_effect=AssertionError("clone consulted templates")
        ):
            cloned = CloneConfigurationUseCase(self.repo)("full", source.execution_id)
        _, executions = self.repo.load(ProjectId(cloned.project_id))
        target = executions[0]
        self.assertEqual(target.defaults["chunk_count"], 3)
        self.assertEqual(target.defaults["prompts"], ["one", "two", "three"])
        self.assertEqual([dict(chunk.defaults) for chunk in target.chunks], list(applied.chunks))
        self.assertNotIn("template_id", target.defaults)


if __name__ == "__main__":
    unittest.main()
