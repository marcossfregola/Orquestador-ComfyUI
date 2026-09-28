import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from orquestador.application.drafts import DraftUseCase
from orquestador.application.queue_dashboard import QueueDashboardUseCase
from orquestador.application.queue_dispatch import QueueDispatchError, QueueDispatchSession
from orquestador.application.queue_operations import QueueOperationsUseCase
from orquestador.application.queue_recovery import ActiveQueueRecoveryUseCase, QueueRecoveryOutcome
from orquestador.application.scheduler import (
    SchedulerExecutionBoundary,
    SchedulerInstanceLock,
    SchedulerTickOutcome,
    SingleExecutionScheduler,
)
from orquestador.domain import BackendJobRef, Lifecycle, ProjectId, QueueClaimStatus, QueueStartMode
from orquestador.persistence import SQLiteProjectRepository
from orquestador.persistence.sqlite import PersistenceDataError


class F142QueueStartPolicyPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.repo = SQLiteProjectRepository(self.root)

    def tearDown(self):
        self.repo.close()
        self.temp.cleanup()

    def test_schema9_defaults_to_auto_and_manual_mode_survives_reopen(self):
        self.assertEqual(self.repo.db.execute("SELECT version FROM schema_version").fetchone()[0], 9)
        self.assertEqual(self.repo.get_queue_start_mode(), QueueStartMode.AUTO)
        self.assertEqual(
            self.repo.db.execute("SELECT singleton,mode FROM queue_start_policy").fetchall(),
            [(1, "auto")],
        )

        self.repo.set_queue_start_mode(QueueStartMode.MANUAL)
        self.repo.close()
        self.repo = SQLiteProjectRepository(self.root)
        self.assertEqual(self.repo.get_queue_start_mode(), QueueStartMode.MANUAL)

    def test_schema8_migration_defaults_to_auto_without_changing_queue_pause(self):
        self.repo.set_queue_start_mode(QueueStartMode.MANUAL)
        self.repo.set_queue_paused(True)
        self.repo.db.execute("DROP TABLE queue_start_policy")
        self.repo.db.execute("UPDATE schema_version SET version=8")
        self.repo.close()

        self.repo = SQLiteProjectRepository(self.root)
        self.assertEqual(self.repo.get_queue_start_mode(), QueueStartMode.AUTO)
        self.assertTrue(self.repo.get_queue_control().paused)
        self.assertEqual(self.repo.db.execute("SELECT version FROM schema_version").fetchone()[0], 9)

    def test_invalid_and_missing_policy_fail_closed(self):
        with self.assertRaises(PersistenceDataError):
            self.repo.set_queue_start_mode("automatic")
        self.repo.db.execute("PRAGMA ignore_check_constraints=ON")
        self.repo.db.execute("UPDATE queue_start_policy SET mode='automatic' WHERE singleton=1")
        with self.assertRaises(PersistenceDataError):
            self.repo.get_queue_start_mode()
        self.repo.db.execute("UPDATE queue_start_policy SET mode='auto' WHERE singleton=1")
        self.repo.db.execute("DELETE FROM queue_start_policy")
        with self.assertRaises(PersistenceDataError):
            self.repo.get_queue_start_mode()


class F142QueueStartPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.repo = SQLiteProjectRepository(self.root)
        self.drafts = DraftUseCase(self.repo)
        self.queue = QueueOperationsUseCase(self.repo)
        self.session = QueueDispatchSession()
        self.schedulers = []

    def tearDown(self):
        for scheduler in reversed(self.schedulers):
            try:
                scheduler.stop()
            except Exception:
                pass
        self.repo.close()
        self.temp.cleanup()

    def draft(self, execution_id):
        return self.drafts.create(
            "policy-project",
            execution_id=execution_id,
            defaults={"label": execution_id},
            chunks=[{"prompt": "one"}, {"prompt": "two"}],
        )

    def scheduler(self, starter, *, recovery=None, session=None):
        scheduler = SingleExecutionScheduler(
            self.repo,
            SchedulerExecutionBoundary(starter, reconcile_active=recovery),
            SchedulerInstanceLock(self.root),
            dispatch_session=self.session if session is None else session,
        )
        self.schedulers.append(scheduler)
        scheduler.start()
        return scheduler

    def active_running_with_bound_attempt(self, execution_id, item_id):
        draft = self.draft(execution_id)
        item = self.queue.enqueue("policy-project", draft.execution_id, queue_item_id=item_id)
        claim = self.repo.claim_next_queue_item()
        self.assertEqual(claim.status, QueueClaimStatus.CLAIMED)
        project, executions = self.repo.load(ProjectId("policy-project"))
        execution = next(entry for entry in executions if str(entry.id) == draft.execution_id)
        execution.transition(Lifecycle.RUNNING)
        self.repo.start_execution_from_active_queue_claim(project, execution, item.id)
        chunk = execution.chunks[0]
        chunk.transition(Lifecycle.RUNNING)
        attempt = chunk.new_attempt()
        attempt.assign_external_job_ref(BackendJobRef("existing-backend-job"))
        self.repo.save(project, [execution])
        return item, draft, attempt

    def test_manual_cold_start_empty_and_queued_never_claim_or_start(self):
        self.session.set_mode(self.repo, QueueStartMode.MANUAL)
        empty_scheduler = self.scheduler(lambda *_: self.fail("empty manual queue must not start"))
        empty = empty_scheduler.tick()
        self.assertEqual(empty.outcome, SchedulerTickOutcome.DISPATCH_CLOSED)
        self.assertIsNone(self.repo.get_queue_control().active_queue_item_id)
        empty_scheduler.stop()

        draft = self.draft("queued-manual")
        item = self.queue.enqueue("policy-project", draft.execution_id, queue_item_id="queued-item")
        submitted = []
        result = self.scheduler(lambda *args: submitted.append(args)).tick()
        self.assertEqual(result.outcome, SchedulerTickOutcome.DISPATCH_CLOSED)
        self.assertEqual(submitted, [])
        self.assertEqual(self.repo.get_queue_item(item.id).state.value, "queued")
        self.assertIsNone(self.repo.get_queue_control().active_queue_item_id)

    def test_scheduler_without_injected_session_still_fails_closed_in_manual_mode(self):
        self.repo.set_queue_start_mode(QueueStartMode.MANUAL)
        draft = self.draft("default-session-closed")
        item = self.queue.enqueue(
            "policy-project", draft.execution_id, queue_item_id="default-session-item"
        )
        starts = []
        scheduler = SingleExecutionScheduler(
            self.repo,
            SchedulerExecutionBoundary(lambda *args: starts.append(args)),
            SchedulerInstanceLock(self.root),
        )
        self.schedulers.append(scheduler)
        scheduler.start()
        self.assertEqual(scheduler.tick().outcome, SchedulerTickOutcome.DISPATCH_CLOSED)
        self.assertEqual(starts, [])
        self.assertEqual(self.repo.get_queue_item(item.id).state.value, "queued")

    def test_manual_permission_is_session_only_and_explicitly_starts_existing_scheduler_path(self):
        self.session.set_mode(self.repo, QueueStartMode.MANUAL)
        draft = self.draft("explicit-start")
        item = self.queue.enqueue("policy-project", draft.execution_id, queue_item_id="one-item")
        calls = []

        def start(project_id, execution_id, queue_item_id):
            calls.append((project_id, execution_id, queue_item_id))
            project, executions = self.repo.load(ProjectId(project_id))
            execution = next(entry for entry in executions if str(entry.id) == execution_id)
            execution.transition(Lifecycle.RUNNING)
            self.repo.start_execution_from_active_queue_claim(project, execution, queue_item_id)
            self.repo.save(project, [execution])

        scheduler = self.scheduler(start)
        self.assertEqual(scheduler.tick().outcome, SchedulerTickOutcome.DISPATCH_CLOSED)
        self.session.start_manual_session(self.repo)
        self.assertEqual(scheduler.tick().outcome, SchedulerTickOutcome.RECOVERY_REQUIRED)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.repo.get_queue_item(item.id).state.value, "active")
        self.assertEqual(str(self.repo.get_queue_control().active_queue_item_id), item.id)
        self.assertEqual(scheduler.tick().outcome, SchedulerTickOutcome.RECOVERY_REQUIRED)
        self.assertEqual(len(calls), 1)
        scheduler.stop()

        restarted_session = QueueDispatchSession()
        self.assertEqual(restarted_session.snapshot(self.repo), (QueueStartMode.MANUAL, False))
        self.assertEqual(
            self.scheduler(lambda *_: self.fail("restart must close the manual session"), session=restarted_session)
            .tick().outcome,
            SchedulerTickOutcome.RECOVERY_REQUIRED,
        )
        self.assertEqual(len(calls), 1)

    def test_manual_permission_opens_only_in_manual_mode_and_pause_remains_independent(self):
        with self.assertRaises(QueueDispatchError):
            self.session.start_manual_session(self.repo)
        self.session.set_mode(self.repo, QueueStartMode.MANUAL)
        draft = self.draft("paused-manual")
        item = self.queue.enqueue("policy-project", draft.execution_id, queue_item_id="paused-item")
        self.queue.pause()
        self.session.start_manual_session(self.repo)
        calls = []
        scheduler = self.scheduler(lambda *args: calls.append(args))
        self.assertEqual(scheduler.tick().outcome, SchedulerTickOutcome.PAUSED)
        self.assertEqual(calls, [])
        self.assertEqual(self.repo.get_queue_item(item.id).state.value, "queued")
        self.queue.resume()
        self.assertEqual(scheduler.tick().outcome, SchedulerTickOutcome.RECOVERY_REQUIRED)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.repo.get_queue_item(item.id).state.value, "active")

    def test_auto_policy_preserves_f13_10_automatic_claim_behavior(self):
        self.assertEqual(self.repo.get_queue_start_mode(), QueueStartMode.AUTO)
        draft = self.draft("automatic")
        item = self.queue.enqueue("policy-project", draft.execution_id, queue_item_id="auto-item")
        calls = []
        result = self.scheduler(lambda *args: calls.append(args)).tick()
        self.assertEqual(result.outcome, SchedulerTickOutcome.RECOVERY_REQUIRED)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.repo.get_queue_item(item.id).state.value, "active")

    def test_closed_manual_session_reconciles_bound_survivor_without_submit_or_cancel(self):
        item, draft, attempt = self.active_running_with_bound_attempt("running-active", "running-item")
        self.session.set_mode(self.repo, QueueStartMode.MANUAL)
        starts = []
        observations = []

        def resume(*_):
            observations.append("observed")
            return SimpleNamespace(outcome="wait", reason="backend job remains observable")

        recovery = ActiveQueueRecoveryUseCase(
            self.repo,
            lambda *args: starts.append(args),
            resume,
            completion_validator=lambda _execution: False,
        )
        scheduler = self.scheduler(
            lambda *args: starts.append(args),
            recovery=recovery.reconcile,
        )
        result = scheduler.tick()
        self.assertEqual(result.outcome, SchedulerTickOutcome.RECOVERY_REQUIRED)
        self.assertEqual(result.recovery_outcome, QueueRecoveryOutcome.WAIT.value)
        self.assertEqual(starts, [])
        self.assertEqual(observations, ["observed"])
        self.assertEqual(self.repo.get_queue_item(item.id).state.value, "active")
        self.assertEqual(str(self.repo.get_queue_control().active_queue_item_id), item.id)
        _, execution = self.repo.load(ProjectId("policy-project"))
        survivor = next(entry for entry in execution if str(entry.id) == draft.execution_id)
        self.assertEqual(survivor.state, Lifecycle.RUNNING)
        self.assertEqual(survivor.chunks[0].attempts[0].id, attempt.id)

    def test_manual_closed_defers_pending_virgin_active_until_explicit_session_start(self):
        draft = self.draft("virgin-active")
        next_draft = self.draft("waiting-item")
        active = self.queue.enqueue("policy-project", draft.execution_id, queue_item_id="virgin-active-item")
        waiting = self.queue.enqueue("policy-project", next_draft.execution_id, queue_item_id="waiting-item-id")
        self.assertEqual(str(self.repo.claim_next_queue_item().item.id), active.id)
        self.session.set_mode(self.repo, QueueStartMode.MANUAL)
        starts = []
        recovery = ActiveQueueRecoveryUseCase(
            self.repo,
            lambda *args: starts.append(args) or SimpleNamespace(outcome="wait"),
            lambda *args: self.fail("pending virgin active has no backend job to observe"),
            completion_validator=lambda _execution: False,
        )
        scheduler = self.scheduler(lambda *args: starts.append(args), recovery=recovery.reconcile)

        deferred = scheduler.tick()
        self.assertEqual(deferred.outcome, SchedulerTickOutcome.RECOVERY_REQUIRED)
        self.assertEqual(deferred.recovery_outcome, QueueRecoveryOutcome.WAIT.value)
        self.assertIn("dispatch is closed", deferred.reason)
        self.assertEqual(starts, [])
        self.assertEqual(self.repo.get_queue_item(active.id).state.value, "active")
        self.assertEqual(self.repo.get_queue_item(waiting.id).state.value, "queued")

        self.session.start_manual_session(self.repo)
        resumed = scheduler.tick()
        self.assertEqual(resumed.outcome, SchedulerTickOutcome.RECOVERY_REQUIRED)
        self.assertEqual(len(starts), 1)
        self.assertEqual(str(self.repo.get_queue_control().active_queue_item_id), active.id)
        self.assertEqual(self.repo.get_queue_item(waiting.id).state.value, "queued")

    def test_switching_auto_to_manual_does_not_cancel_or_rewrite_active_evidence(self):
        item, draft, attempt = self.active_running_with_bound_attempt("switch-active", "switch-item")
        self.session.set_mode(self.repo, QueueStartMode.MANUAL)
        self.assertEqual(self.repo.get_queue_start_mode(), QueueStartMode.MANUAL)
        self.assertEqual(self.repo.get_queue_item(item.id).state.value, "active")
        self.assertEqual(str(self.repo.get_queue_control().active_queue_item_id), item.id)
        _, executions = self.repo.load(ProjectId("policy-project"))
        active = next(entry for entry in executions if str(entry.id) == draft.execution_id)
        self.assertEqual(active.state, Lifecycle.RUNNING)
        self.assertEqual(active.chunks[0].attempts[0].id, attempt.id)
        self.assertEqual(self.session.snapshot(self.repo), (QueueStartMode.MANUAL, False))

    def test_policy_dashboard_distinguishes_manual_gate_from_durable_pause(self):
        self.session.set_mode(self.repo, QueueStartMode.MANUAL)
        draft = self.draft("dashboard-manual")
        self.queue.enqueue("policy-project", draft.execution_id, queue_item_id="dashboard-item")
        dashboard = QueueDashboardUseCase(self.repo, dispatch_session=self.session)
        closed = dashboard.snapshot()
        self.assertEqual(closed.state, "dispatch_closed")
        self.assertEqual(closed.start_mode, "manual")
        self.assertFalse(closed.manual_dispatch_open)
        self.assertFalse(closed.paused)

        self.session.start_manual_session(self.repo)
        opened = dashboard.snapshot()
        self.assertEqual(opened.start_mode, "manual")
        self.assertTrue(opened.manual_dispatch_open)
        self.assertNotEqual(opened.state, "paused")
        self.queue.pause()
        paused = dashboard.snapshot()
        self.assertTrue(paused.paused)
        self.assertEqual(paused.state, "paused")
        self.assertTrue(paused.manual_dispatch_open)


class F142QueueStartPolicyQtTests(unittest.TestCase):
    def test_offscreen_policy_selector_and_session_start_are_separate_from_pause(self):
        from PySide6.QtWidgets import QApplication
        from orquestador.ui.app import AppConfig, compose
        from orquestador.ui.queue_panel import QueuePanel

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            facade, resources = compose(AppConfig(Path(directory)))
            dashboard = facade.queue_snapshot()
            self.assertTrue(dashboard.success, dashboard.message)
            panel = None

            def run(operation, _kind):
                result = operation()
                panel.handle_result(result)

            panel = QueuePanel(facade, run)
            self.addCleanup(panel.close)
            self.addCleanup(resources["repository"].close)
            panel.render(dashboard.queue)
            self.assertEqual(panel.start_mode.currentData(), "auto")
            self.assertFalse(panel.start_manual_button.isEnabled())

            manual_index = panel.start_mode.findData("manual")
            panel.start_mode.setCurrentIndex(manual_index)
            app.processEvents()
            self.assertEqual(panel._snapshot.start_mode, "manual")
            self.assertFalse(panel._snapshot.manual_dispatch_open)
            self.assertTrue(panel.start_manual_button.isEnabled())
            self.assertFalse(panel._snapshot.paused)

            panel.start_manual_button.click()
            app.processEvents()
            self.assertTrue(panel._snapshot.manual_dispatch_open)
            self.assertFalse(panel.start_manual_button.isEnabled())
            self.assertFalse(panel._snapshot.paused)

            panel.pause_resume_button.click()
            app.processEvents()
            self.assertTrue(panel._snapshot.paused)
            self.assertTrue(panel._snapshot.manual_dispatch_open)

            panel.pause_resume_button.click()
            app.processEvents()
            self.assertFalse(panel._snapshot.paused)
            self.assertTrue(panel._snapshot.manual_dispatch_open)


if __name__ == "__main__":
    unittest.main()
