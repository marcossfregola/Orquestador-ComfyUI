import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from orquestador.application.drafts import DraftUseCase
from orquestador.application.chunk_templates import ChunkTemplatesUseCase
from orquestador.application.global_defaults import GlobalDefaultsUseCase
from orquestador.application.gui_facade import GuiFacade
from orquestador.application.preparation_library import (
    PreparationLibraryError,
    PreparationLibraryUseCase,
)
from orquestador.application.queue_operations import QueueOperationsUseCase
from orquestador.domain.config import GlobalDefaults
from orquestador.domain.core import Lifecycle, QueueItemState
from orquestador.persistence import SQLiteProjectRepository
from orquestador.ui.app import AppConfig, compose


class F136PreparationLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        (self.root / "inputs").mkdir()
        (self.root / "inputs" / "start.png").write_bytes(b"start")
        (self.root / "inputs" / "reference.png").write_bytes(b"reference")
        self.repository = SQLiteProjectRepository(self.root)
        self.drafts = DraftUseCase(self.repository)
        self.library = PreparationLibraryUseCase(self.repository)

    def tearDown(self):
        self.repository.close()
        self.temp.cleanup()

    @staticmethod
    def mapping(**updates):
        return {**GlobalDefaults().to_mapping(), **updates}

    def draft(self, project="project", execution="draft"):
        return self.drafts.create(
            project,
            execution_id=execution,
            defaults={
                "profile_ref": "minimax-h3-ui",
                "initial_image": "inputs/start.png",
                "references": ["inputs/reference.png"],
                "prompts": ["one", "two"],
                "chunk_count": 2,
                "metadata": {"preserve": True},
            },
            chunks=[{"prompt": "one"}, {"prompt": "two", "steps": 27}],
        )

    def test_projection_selection_clone_and_no_dynamic_global_lookup(self):
        source = self.draft("source", "source-execution")
        self.library.update_global_defaults(self.mapping(steps=31))
        preset = self.library.create_preset("Fast", self.mapping(fps=12))
        template = self.library.create_template("Story", ("first", "second"))

        snapshot = self.library.snapshot()
        self.assertEqual(
            [(project.project_id, item.execution_number, item.classification)
             for project in snapshot.projects for item in project.executions],
            [("source", 1, "draft")],
        )
        self.assertEqual(dict(snapshot.global_defaults)["steps"], 31)
        self.assertEqual([(item.name, item.is_default) for item in snapshot.technical_presets], [("Fast", False)])
        self.assertEqual([(item.name, item.prompts) for item in snapshot.chunk_templates], [("Story", ("first", "second"))])

        new_draft = self.library.create_draft("new-project")
        captured = self.drafts.reopen(new_draft.project_id, new_draft.execution_id)
        self.assertEqual(captured.defaults["steps"], 31)
        self.assertEqual(len(captured.chunks), 2)
        _, durable = self.repository.load("new-project")
        self.assertEqual(durable[0].workflow_profile_ref.value, "minimax-h3-ui")

        selected = self.library.select("source", source.execution_id)
        self.assertTrue(selected.can_open)
        self.assertTrue(selected.can_edit)
        self.assertTrue(selected.can_clone)
        with patch.object(
            self.repository,
            "load_global_defaults",
            side_effect=AssertionError("clone consulted Global Defaults"),
        ):
            cloned = self.library.clone("source", source.execution_id)
        self.assertNotEqual(cloned.project_id, "source")
        self.assertNotEqual(cloned.execution_id, source.execution_id)
        source_snapshot = self.drafts.reopen("source", source.execution_id)
        clone_snapshot = self.drafts.reopen(cloned.project_id, cloned.execution_id)
        self.assertEqual(source_snapshot.defaults["steps"], 20)
        self.assertEqual(clone_snapshot.defaults["steps"], 20)
        self.assertEqual(clone_snapshot.chunks, source_snapshot.chunks)

    def test_administered_values_apply_by_copy_and_queued_rows_are_not_editable(self):
        draft = self.draft()
        preset = self.library.create_preset("Fast", self.mapping(steps=31, fps=12))
        template = self.library.create_template("Story", ("opening", "ending"))
        before = self.drafts.reopen("project", draft.execution_id)

        self.library.apply_preset(preset.id, "project", draft.execution_id)
        self.library.apply_template(template.id, "project", draft.execution_id)
        applied = self.drafts.reopen("project", draft.execution_id)
        self.assertEqual((applied.defaults["steps"], applied.defaults["fps"]), (31, 12))
        self.assertEqual([chunk["prompt"] for chunk in applied.chunks], ["opening", "ending"])
        self.assertEqual(applied.defaults["metadata"], before.defaults["metadata"])
        self.assertEqual(applied.chunks[1]["steps"], 27)

        self.library.update_preset(preset.id, self.mapping(steps=42, fps=8))
        self.library.update_template(template.id, ("changed", "later"))
        stable = self.drafts.reopen("project", draft.execution_id)
        self.assertEqual((stable.defaults["steps"], stable.defaults["fps"]), (31, 12))
        self.assertEqual([chunk["prompt"] for chunk in stable.chunks], ["opening", "ending"])

        QueueOperationsUseCase(self.repository).enqueue("project", draft.execution_id)
        queued = self.library.select("project", draft.execution_id)
        self.assertEqual(queued.classification, "queued")
        self.assertFalse(queued.can_edit)
        with self.assertRaises(PreparationLibraryError):
            self.library.apply_preset(preset.id, "project", draft.execution_id)

        # F13.6 only projects the active state; it does not claim or schedule
        # work.  Once another authority makes the item active, the same
        # non-editable gate must remain visible through the library.
        active_item = self.repository.list_queue_items()[0]
        active_item.transition(QueueItemState.ACTIVE)
        project, executions = self.repository.load("project")
        execution = next(item for item in executions if str(item.id) == draft.execution_id)
        execution.transition(Lifecycle.RUNNING)
        self.repository.save(project, [execution])
        self.repository.save_queue_item(active_item)
        active = self.library.select("project", draft.execution_id)
        self.assertEqual(active.classification, "running")
        self.assertFalse(active.can_edit)

    def test_facade_returns_library_results_and_authoritative_selection_snapshot(self):
        draft = self.draft()
        facade = GuiFacade(
            snapshot=lambda project_id, execution_id: {
                "project_id": project_id,
                "execution_id": execution_id,
                "execution_number": 1,
                "state": "pending",
                "can_edit": True,
            },
            library=self.library,
        )
        listing = facade.library_snapshot()
        self.assertTrue(listing.success, listing.message)
        self.assertEqual(listing.library.projects[0].project_id, "project")
        opened = facade.open_library_execution("project", draft.execution_id)
        self.assertTrue(opened.success, opened.message)
        self.assertEqual(
            (opened.snapshot.project_id, opened.snapshot.execution_id),
            ("project", draft.execution_id),
        )
        cloned = facade.clone_library_execution("project", draft.execution_id)
        self.assertTrue(cloned.success, cloned.message)
        self.assertNotEqual(cloned.selection.execution_id, draft.execution_id)


class F136QtLibraryTests(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication

        self.app = QApplication.instance() or QApplication([])
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        (self.root / "inputs").mkdir()
        (self.root / "inputs" / "start.png").write_bytes(b"start")
        (self.root / "inputs" / "reference.png").write_bytes(b"reference")
        self.facade, self.resources = compose(AppConfig(self.root))
        self.drafts = DraftUseCase(self.resources["repository"])
        self.draft = self.drafts.create(
            "visible-project",
            execution_id="technical-execution-id",
            defaults={
                "profile_ref": "minimax-h3-ui",
                "initial_image": "inputs/start.png",
                "references": ["inputs/reference.png"],
                "prompts": ["one", "two"],
                "chunk_count": 2,
            },
            chunks=[{"prompt": "one"}, {"prompt": "two"}],
        )
        from orquestador.ui.main_window import MainWindow

        self.window = MainWindow(self.facade, self.root)
        self.addCleanup(self.window.close)

    def tearDown(self):
        self.resources["repository"].close()
        self.temp.cleanup()

    def wait_for_worker(self, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and (self.window._busy or self.window._thread is not None):
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        self.assertFalse(self.window._busy)
        self.assertIsNone(self.window._thread)

    def select_execution(self, project_id, execution_id):
        panel = self.window.library_panel
        for index in range(panel.execution_list.count()):
            item = panel.execution_list.item(index)
            value = item.data(256)
            if (
                hasattr(value, "project_id")
                and value.project_id == project_id
                and value.execution_id == execution_id
            ):
                panel.execution_list.setCurrentItem(item)
                self.app.processEvents()
                return item
        self.fail("execution was not rendered")

    def test_offscreen_wiring_selection_editability_clone_and_saved_configuration(self):
        panel = self.window.library_panel
        self.window.resize(1280, 900)
        self.window.show()
        self.app.processEvents()
        self.window.tabs.setCurrentIndex(self.window.library_tab_index)
        self.wait_for_worker()
        self.assertEqual(self.window.tabs.tabText(self.window.library_tab_index), "Biblioteca")
        item = self.select_execution("visible-project", self.draft.execution_id)
        self.assertNotIn(self.draft.execution_id, item.text())
        self.assertIn("Proyecto: visible-project", item.text())
        self.assertIn("Selección actual: Proyecto: visible-project", panel.selection_context.text())
        self.assertTrue(panel.open_button.isEnabled())
        self.assertTrue(panel.clone_button.isEnabled())
        panel.refresh()
        self.wait_for_worker()
        self.assertEqual(panel._current_execution().execution_id, self.draft.execution_id)

        before_globals = GlobalDefaultsUseCase(self.resources["repository"]).read().to_mapping()
        before_globals = {**before_globals, "steps": before_globals["steps"] + 1}
        GlobalDefaultsUseCase(self.resources["repository"]).update(before_globals)
        panel.reload_globals_button.click()
        self.wait_for_worker()
        self.assertEqual(panel._technical_widgets["steps"].value(), before_globals["steps"])
        panel._technical_widgets["also_ref_first_frame"].setChecked(True)
        panel._technical_widgets["first_frame_as_primary_reference"].setChecked(True)
        panel.save_globals_button.click()
        self.wait_for_worker()
        self.assertIn("conflicts", panel.status.text())
        self.assertEqual(
            GlobalDefaultsUseCase(self.resources["repository"]).read().to_mapping(),
            before_globals,
        )
        panel._technical_widgets["also_ref_first_frame"].setChecked(False)
        panel._technical_widgets["first_frame_as_primary_reference"].setChecked(False)

        panel.new_project_id.setText("new-visible-project")
        self.assertTrue(panel.create_draft_button.isEnabled())
        panel.create_draft_button.click()
        self.wait_for_worker()
        new_draft_id = self.window.execution.text()
        self.assertTrue(new_draft_id)
        created = self.drafts.reopen("new-visible-project", new_draft_id)
        self.assertEqual(created.defaults["steps"], before_globals["steps"])
        self.assertEqual(self.window.initial.text(), "")
        self.select_execution("visible-project", self.draft.execution_id)

        before_open_log = self.window.log.toPlainText()
        panel.open_selected()
        self.wait_for_worker()
        self.assertEqual(self.window.project.text(), "visible-project")
        self.assertEqual(self.window.execution.text(), self.draft.execution_id)
        self.assertTrue(self.window.prepare.isEnabled())
        self.assertNotIn("Library operation completed", self.window.log.toPlainText()[len(before_open_log):])
        self.assertIn("Proyecto: visible-project", self.window.current_context.text())

        panel.preset_name.setText("Fast")
        panel.create_preset_button.click()
        self.wait_for_worker()
        self.assertEqual(panel.preset_list.count(), 1)
        panel.preset_list.setCurrentRow(0)
        panel._technical_widgets["steps"].setValue(31)
        panel.update_preset_button.click()
        self.wait_for_worker()
        self.assertTrue(panel.apply_preset_button.isEnabled())
        panel.apply_preset_button.click()
        self.wait_for_worker()
        self.assertEqual(
            self.drafts.reopen("visible-project", self.draft.execution_id).defaults["steps"],
            31,
        )

        panel.template_name.setText("Story")
        self.assertEqual(panel.template_tabs.count(), 2)
        panel._template_prompt_editors[0].setPlainText("opening")
        panel._template_prompt_editors[1].setPlainText("middle")
        panel.add_template_chunk_button.click()
        self.assertEqual(panel.template_tabs.count(), 3)
        panel._template_prompt_editors[2].setPlainText("ending")
        panel.create_template_button.click()
        self.wait_for_worker()
        panel.template_list.setCurrentRow(0)
        self.assertEqual(panel.template_tabs.count(), 3)
        self.assertEqual(
            tuple(editor.toPlainText() for editor in panel._template_prompt_editors),
            ("opening", "middle", "ending"),
        )
        template_id = panel._current_template_id()
        self.assertEqual(
            ChunkTemplatesUseCase(self.resources["repository"]).read(template_id).prompts,
            ("opening", "middle", "ending"),
        )
        panel._template_prompt_editors[1].setPlainText("middle revised")
        panel.update_template_button.click()
        self.wait_for_worker()
        self.assertEqual(
            ChunkTemplatesUseCase(self.resources["repository"]).read(template_id).prompts,
            ("opening", "middle revised", "ending"),
        )
        panel.template_name.setText("Story copy")
        panel.duplicate_template_button.click()
        self.wait_for_worker()
        duplicated = [
            item for item in ChunkTemplatesUseCase(self.resources["repository"]).list()
            if item.name == "Story copy"
        ]
        self.assertEqual(len(duplicated), 1)
        self.assertEqual(duplicated[0].prompts, ("opening", "middle revised", "ending"))
        self.assertTrue(panel.apply_template_button.isEnabled())
        panel.apply_template_button.click()
        self.wait_for_worker()
        self.assertEqual(
            [chunk["prompt"] for chunk in self.drafts.reopen("visible-project", self.draft.execution_id).chunks],
            ["opening", "middle revised", "ending"],
        )

        panel.scroll_area.verticalScrollBar().setValue(panel.scroll_area.verticalScrollBar().maximum())
        panel.clone_selected()
        self.wait_for_worker()
        self.assertNotEqual(self.window.execution.text(), self.draft.execution_id)
        clone_id = self.window.execution.text()
        self.assertTrue(clone_id)
        self.assertEqual(panel._current_execution().execution_id, clone_id)
        clone_project_id = panel._current_execution().project_id
        self.assertEqual(self.window.project.text(), clone_project_id)
        self.assertNotIn(clone_project_id, panel.execution_list.currentItem().text())
        self.assertIn("Copia de visible-project", panel.execution_list.currentItem().text())
        self.assertIn("Copia de visible-project", self.window.current_context.text())
        self.assertNotIn(clone_project_id, self.window.current_context.text())
        self.assertTrue(self.window.project.isHidden())
        self.app.processEvents()
        self.assertEqual(panel.scroll_area.verticalScrollBar().value(), 0)
        # Clone lineage is intentionally not a new durable Project field.  A
        # fresh presentation still hides the generated ProjectId rather than
        # making it the normal identity.
        panel._project_labels.clear()
        panel.render(PreparationLibraryUseCase(self.resources["repository"]).snapshot())
        self.assertNotIn(clone_project_id, panel.execution_list.currentItem().text())
        self.assertIn("Proyecto generado", panel.execution_list.currentItem().text())
        self.window._project_display_names.clear()
        self.window.render(self.facade.refresh(clone_project_id, clone_id))
        self.assertNotIn(clone_project_id, self.window.current_context.text())
        self.assertIn("Proyecto generado", self.window.current_context.text())

        QueueOperationsUseCase(self.resources["repository"]).enqueue(
            "visible-project", self.draft.execution_id
        )
        panel.refresh()
        self.wait_for_worker()
        self.select_execution("visible-project", self.draft.execution_id)
        self.assertFalse(panel.apply_preset_button.isEnabled())
        panel.open_selected()
        self.wait_for_worker()
        self.assertFalse(self.window.prepare.isEnabled())
        self.assertFalse(self.window.add_chunk_button.isEnabled())
        self.assertIn("queue", self.window._last_snapshot.edit_reason)
        self.assertFalse(self.window.read_only_notice.isHidden())
        self.assertIn("Solo lectura", self.window.read_only_notice.text())
        self.assertIn("Crear a partir de esta", self.window.read_only_notice.text())

    def test_library_refresh_preserves_scroll_and_chunk_override_layout_has_rows(self):
        from PySide6.QtWidgets import QGroupBox

        panel = self.window.library_panel
        self.window.resize(1280, 900)
        self.window.show()
        self.window.tabs.setCurrentIndex(self.window.library_tab_index)
        self.wait_for_worker()
        self.app.processEvents()
        bar = panel.scroll_area.verticalScrollBar()
        prior = min(80, bar.maximum())
        bar.setValue(prior)
        panel.refresh()
        self.wait_for_worker()
        self.app.processEvents()
        self.assertEqual(bar.value(), min(prior, bar.maximum()))

        self.select_execution("visible-project", self.draft.execution_id)
        panel.open_selected()
        self.wait_for_worker()
        self.window.tabs.setCurrentIndex(2)
        self.window.chunk_tabs.setCurrentIndex(0)
        self.app.processEvents()
        settings = self.window.chunk_tabs.widget(0).findChild(QGroupBox, "chunkSettings")
        self.assertIsNotNone(settings)
        layout = settings.layout()
        self.assertEqual(type(layout).__name__, "QGridLayout")
        for row in range(1, 7):
            with self.subTest(row=row):
                self.assertIsNotNone(layout.itemAtPosition(row, 0).widget())
                self.assertIsNotNone(layout.itemAtPosition(row, 1).widget())
                self.assertIsNotNone(layout.itemAtPosition(row, 2).widget())
                self.assertIsNotNone(layout.itemAtPosition(row, 3).widget())
                self.assertIsNotNone(layout.itemAtPosition(row, 4).widget())

    def test_library_wheel_requires_explicit_click_before_mutating_spinbox(self):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication

        panel = self.window.library_panel
        self.window.resize(1000, 400)
        self.window.show()
        self.window.tabs.setCurrentIndex(self.window.library_tab_index)
        self.wait_for_worker()
        self.app.processEvents()

        spinbox = panel._technical_widgets["steps"]
        spinbox.setValue(20)
        panel.scroll_area.ensureWidgetVisible(spinbox)
        spinbox.setFocus(Qt.OtherFocusReason)
        self.app.processEvents()
        self.assertTrue(spinbox.hasFocus())
        bar = panel.scroll_area.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)

        def wheel(delta):
            position = spinbox.rect().center()
            return QWheelEvent(
                QPointF(position),
                QPointF(spinbox.mapToGlobal(position)),
                QPoint(),
                QPoint(0, delta),
                Qt.NoButton,
                Qt.NoModifier,
                Qt.ScrollUpdate,
                False,
            )

        before_first_scroll = bar.value()
        self.assertLess(before_first_scroll, bar.maximum())
        QApplication.sendEvent(spinbox, wheel(-120))
        self.app.processEvents()
        self.assertEqual(spinbox.value(), 20)
        self.assertGreater(bar.value(), before_first_scroll)

        panel.scroll_area.ensureWidgetVisible(spinbox)
        self.app.processEvents()
        QTest.mouseClick(
            spinbox.lineEdit(),
            Qt.LeftButton,
            Qt.NoModifier,
            spinbox.lineEdit().rect().center(),
        )
        self.app.processEvents()
        self.assertTrue(spinbox.hasFocus())
        QApplication.sendEvent(spinbox, wheel(120))
        self.app.processEvents()
        self.assertGreater(spinbox.value(), 20)

        panel.scroll_area.ensureWidgetVisible(panel.new_project_id)
        self.app.processEvents()
        QTest.mouseClick(
            panel.new_project_id,
            Qt.LeftButton,
            Qt.NoModifier,
            panel.new_project_id.rect().center(),
        )
        panel.scroll_area.ensureWidgetVisible(spinbox)
        spinbox.setFocus(Qt.OtherFocusReason)
        self.app.processEvents()
        self.assertTrue(spinbox.hasFocus())
        before_final_value = spinbox.value()
        before_final_scroll = bar.value()
        self.assertLess(before_final_scroll, bar.maximum())
        QApplication.sendEvent(spinbox, wheel(-120))
        self.app.processEvents()
        self.assertEqual(spinbox.value(), before_final_value)
        self.assertGreater(bar.value(), before_final_scroll)

    def test_ui_source_uses_facade_not_storage_or_backend_adapters(self):
        source = Path("src/orquestador/ui/preparation_library.py").read_text(encoding="utf-8")
        self.assertNotIn("SQLiteProjectRepository", source)
        self.assertNotIn("ComfyUIClient", source)
        self.assertNotIn("FFmpeg", source)
        self.assertIn("self.facade.", source)


if __name__ == "__main__":
    unittest.main()
