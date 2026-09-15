import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from orquestador.application.drafts import DraftUseCase
from orquestador.application.queue_dashboard import QueueDashboardUseCase
from orquestador.application.queue_operations import QueueOperationsUseCase
from orquestador.application.scheduler import (
    SchedulerRuntimeStatus,
    SchedulerTickOutcome,
    SchedulerTickResult,
)
from orquestador.domain import BackendJobRef, Lifecycle, ProjectId
from orquestador.persistence import SQLiteProjectRepository
from orquestador.ui.app import AppConfig, compose


class F1310QueueDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.repo = SQLiteProjectRepository(self.root)
        self.drafts = DraftUseCase(self.repo)
        self.runtime = SchedulerRuntimeStatus(False)
        self.dashboard = QueueDashboardUseCase(
            self.repo,
            scheduler_status=lambda: self.runtime,
        )

    def tearDown(self):
        self.repo.close()
        self.temp.cleanup()

    def draft(self, project_id, execution_id):
        return self.drafts.create(
            project_id,
            execution_id=execution_id,
            defaults={"label": project_id},
            chunks=[{"prompt": "one"}, {"prompt": "two"}],
        )

    def test_projection_reorder_pause_terminal_history_and_restart(self):
        first = self.draft("proyecto-a", "ejecucion-a")
        second = self.draft("proyecto-b", "ejecucion-b")

        first_action = self.dashboard.enqueue("proyecto-a", first.execution_id)
        second_action = self.dashboard.enqueue("proyecto-b", second.execution_id)
        self.assertEqual(first_action.selection.presentation_state, "queued")
        self.assertEqual(second_action.selection.project_id, "proyecto-b")
        self.assertEqual(
            [entry.execution_id for entry in second_action.snapshot.entries],
            [first.execution_id, second.execution_id],
        )
        project, executions = self.repo.load(ProjectId("proyecto-a"))
        queued_execution = next(item for item in executions if str(item.id) == first.execution_id)
        self.assertEqual(queued_execution.state, Lifecycle.PENDING)
        self.assertTrue(all(not chunk.attempts for chunk in queued_execution.chunks))

        reordered = self.dashboard.reorder(
            (second_action.selection.queue_item_id, first_action.selection.queue_item_id),
            selection_id=second_action.selection.queue_item_id,
        )
        self.assertEqual(
            [entry.execution_id for entry in reordered.snapshot.entries],
            [second.execution_id, first.execution_id],
        )
        self.assertTrue(reordered.selection.can_move_down)

        paused = self.dashboard.pause(
            expected_revision=reordered.snapshot.revision,
            selection_id=reordered.selection.queue_item_id,
        )
        self.assertTrue(paused.snapshot.paused)
        self.assertEqual(paused.snapshot.state, "paused")
        resumed = self.dashboard.resume(
            expected_revision=paused.snapshot.revision,
            selection_id=paused.selection.queue_item_id,
        )
        self.assertFalse(resumed.snapshot.paused)

        skipped = self.dashboard.skip(second_action.selection.queue_item_id)
        removed = self.dashboard.remove(first_action.selection.queue_item_id)
        self.assertEqual(skipped.selection.presentation_state, "skipped")
        self.assertEqual(removed.selection.presentation_state, "removed")
        self.assertEqual(
            {entry.presentation_state for entry in removed.snapshot.entries},
            {"removed", "skipped"},
        )

        self.repo.close()
        self.repo = SQLiteProjectRepository(self.root)
        self.drafts = DraftUseCase(self.repo)
        self.dashboard = QueueDashboardUseCase(
            self.repo,
            scheduler_status=lambda: self.runtime,
        )
        reopened = self.dashboard.snapshot()
        self.assertEqual(
            [(entry.execution_id, entry.presentation_state) for entry in reopened.entries],
            [(second.execution_id, "skipped"), (first.execution_id, "removed")],
        )

    def test_restart_adopts_one_direct_start_survivor_without_rewriting_attempt(self):
        draft = self.draft("orphan-project", "orphan-execution")
        project, executions = self.repo.load(ProjectId("orphan-project"))
        execution = next(item for item in executions if str(item.id) == draft.execution_id)
        execution.transition(Lifecycle.RUNNING)
        attempt = execution.chunks[0].new_attempt()
        attempt.assign_external_job_ref(BackendJobRef("comfy-job-survivor"))
        self.repo.save(project, [execution])

        adopted = self.repo.adopt_orphaned_running_executions()
        self.assertEqual(len(adopted), 1)
        item = adopted[0]
        self.assertEqual(item.state.value, "active")
        self.assertEqual(str(item.execution_id), draft.execution_id)
        self.assertEqual(str(self.repo.get_queue_control().active_queue_item_id), str(item.id))

        _, reopened = self.repo.load(ProjectId("orphan-project"))
        survivor = next(item for item in reopened if str(item.id) == draft.execution_id)
        self.assertEqual(survivor.state, Lifecycle.RUNNING)
        self.assertEqual(str(survivor.chunks[0].attempts[0].external_job_ref), "comfy-job-survivor")
        self.assertEqual(self.repo.adopt_orphaned_running_executions(), ())

    def test_active_manual_review_is_visible_and_keeps_next_waiting(self):
        first = self.draft("proyecto", "primera")
        second = self.draft("proyecto", "segunda")
        queue = QueueOperationsUseCase(self.repo)
        active = queue.enqueue("proyecto", first.execution_id, queue_item_id="activa")
        waiting = queue.enqueue("proyecto", second.execution_id, queue_item_id="espera")
        claim = self.repo.claim_next_queue_item()
        self.assertEqual(str(claim.item.id), active.id)
        project, executions = self.repo.load(ProjectId("proyecto"))
        execution = next(item for item in executions if str(item.id) == first.execution_id)
        execution.transition(Lifecycle.RUNNING)
        self.repo.start_execution_from_active_queue_claim(project, execution, active.id)

        self.runtime = SchedulerRuntimeStatus(
            True,
            SchedulerTickResult(
                SchedulerTickOutcome.RECOVERY_REQUIRED,
                active.id,
                first.execution_id,
                "durable attempt has no external_job_ref; resubmission is unsafe",
                "manual_review",
            ),
        )
        snapshot = self.dashboard.snapshot()
        by_id = {entry.queue_item_id: entry for entry in snapshot.entries}
        self.assertEqual(snapshot.state, "manual_review")
        self.assertIn("external_job_ref", snapshot.detail)
        self.assertEqual(by_id[active.id].presentation_state, "manual_review")
        self.assertEqual(by_id[waiting.id].presentation_state, "queued")
        self.assertFalse(by_id[active.id].can_remove)
        self.assertTrue(by_id[waiting.id].can_remove)

        paused = self.dashboard.pause(expected_revision=snapshot.revision, selection_id=active.id)
        self.assertEqual(paused.snapshot.state, "paused")
        self.assertEqual(
            next(entry for entry in paused.snapshot.entries if entry.queue_item_id == active.id).presentation_state,
            "paused",
        )


class F1310QtQueueTests(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication

        self.app = QApplication.instance() or QApplication([])
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.facade, self.resources = compose(AppConfig(self.root))
        self.drafts = DraftUseCase(self.resources["repository"])
        self.first = self.drafts.create(
            "visible-a",
            execution_id="execution-a",
            defaults={"label": "visible-a"},
            chunks=[{"prompt": "one"}, {"prompt": "two"}],
        )
        self.second = self.drafts.create(
            "visible-b",
            execution_id="execution-b",
            defaults={"label": "visible-b"},
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
        while time.monotonic() < deadline and (
            self.window._busy or self.window._thread is not None
        ):
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        self.assertFalse(self.window._busy)
        self.assertIsNone(self.window._thread)

    def prepare_identity(self, project_id, execution_id):
        from orquestador.ui.main_window import PreparedIdentity

        self.window.render(self.facade.refresh(project_id, execution_id))
        selection = (project_id, execution_id)
        self.window._prepared_identity = PreparedIdentity(self.window._form_key(), selection)
        self.window._prepared_key = self.window._prepared_identity.form_key
        self.window._prepared_selection = selection
        self.window._update_start()
        self.assertTrue(self.window.enqueue.isEnabled())

    def select_queue_item(self, queue_item_id):
        panel = self.window.queue_panel
        for index in range(panel.items.topLevelItemCount()):
            item = panel.items.topLevelItem(index)
            entry = item.data(0, 256)
            if getattr(entry, "queue_item_id", None) == queue_item_id:
                panel.items.setCurrentItem(item)
                self.app.processEvents()
                return item
        self.fail("queue item was not rendered")

    def test_offscreen_enqueue_reorder_pause_and_open(self):
        self.window.show()
        self.app.processEvents()

        self.prepare_identity("visible-a", self.first.execution_id)
        self.window.enqueue.click()
        self.wait_for_worker()
        first_item = self.window.queue_panel._snapshot.entries[0]
        self.assertEqual(self.window.tabs.currentIndex(), self.window.queue_tab_index)
        self.assertEqual(first_item.execution_id, self.first.execution_id)
        self.assertEqual(first_item.presentation_state, "queued")

        self.prepare_identity("visible-b", self.second.execution_id)
        self.window.enqueue.click()
        self.wait_for_worker()
        entries = self.window.queue_panel._snapshot.entries
        second_item = next(entry for entry in entries if entry.execution_id == self.second.execution_id)

        self.select_queue_item(second_item.queue_item_id)
        self.assertTrue(self.window.queue_panel.move_up_button.isEnabled())
        self.window.queue_panel.move_up_button.click()
        self.wait_for_worker()
        refreshed = self.facade.queue_snapshot()
        self.assertTrue(refreshed.success, refreshed.message)
        self.assertEqual(
            [entry.execution_id for entry in refreshed.queue.entries],
            [self.second.execution_id, self.first.execution_id],
        )

        self.window.queue_panel.pause_resume_button.click()
        self.wait_for_worker()
        self.assertIn("Paused", self.window.queue_panel.global_state.text())
        self.window.queue_panel.pause_resume_button.click()
        self.wait_for_worker()
        self.assertIn("Idle", self.window.queue_panel.global_state.text())

        self.select_queue_item(second_item.queue_item_id)
        self.window.queue_panel.skip_button.click()
        self.wait_for_worker()
        skipped = self.facade.queue_snapshot()
        selected = next(
            entry for entry in skipped.queue.entries if entry.queue_item_id == second_item.queue_item_id
        )
        self.assertEqual(selected.presentation_state, "skipped")
        self.select_queue_item(second_item.queue_item_id)
        self.window.queue_panel.open_button.click()
        self.wait_for_worker()
        self.assertEqual(
            (self.window.project.text(), self.window.execution.text()),
            ("visible-b", self.second.execution_id),
        )

    def test_start_button_admits_queue_item_instead_of_direct_chain(self):
        self.window.show()
        self.app.processEvents()
        self.prepare_identity("visible-a", self.first.execution_id)
        self.window.start.click()
        self.wait_for_worker()
        queued = self.facade.queue_snapshot()
        self.assertTrue(queued.success, queued.message)
        self.assertEqual(
            [(entry.execution_id, entry.queue_state) for entry in queued.queue.entries],
            [(self.first.execution_id, "queued")],
        )
        self.assertEqual(self.window.tabs.currentIndex(), self.window.queue_tab_index)

    def test_prepare_operation_captures_widgets_before_worker(self):
        from orquestador.ui.main_window import MainWindow
        from orquestador.application.gui_facade import ExecutionSnapshot, GuiFacade, OperationResult

        calls = []
        facade = GuiFacade(snapshot=lambda *_: ExecutionSnapshot(state="pending"))
        facade.prepare = lambda **kwargs: calls.append(kwargs) or OperationResult(
            True, ExecutionSnapshot(state="pending", can_start=True)
        )
        window = MainWindow(facade, self.root)
        self.addCleanup(window.close)
        captured = []
        window._run = lambda operation, kind="other": captured.append(operation)
        window.project.setText("before-worker")
        window._prepare()
        window.project.setText("after-capture")
        captured[0]()
        self.assertEqual(calls[0]["project_id"], "before-worker")

    def test_queue_panel_uses_the_facade_not_storage_or_backend_adapters(self):
        source = Path("src/orquestador/ui/queue_panel.py").read_text(encoding="utf-8")
        self.assertIn("self.facade.", source)
        self.assertNotIn("SQLiteProjectRepository", source)
        self.assertNotIn("ComfyUIClient", source)
        self.assertNotIn("SingleExecutionScheduler", source)


if __name__ == "__main__":
    unittest.main()
