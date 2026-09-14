import threading
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from orquestador.application.drafts import DraftUseCase
from orquestador.application.queue_operations import QueueOperationsUseCase
from orquestador.application.scheduler import (
    SchedulerBackgroundRunner,
    SchedulerExecutionBoundary,
    SchedulerInstanceLock,
    SchedulerLockError,
    SchedulerTickOutcome,
    SchedulerTickResult,
    SingleExecutionScheduler,
)
from orquestador.application.start_gui_chain import StartGuiChainUseCase, StartPreparationError
from orquestador.adapters.http import HistoryResult, HistoryState
from orquestador.domain import (
    BackendJobRef,
    Evidence,
    Lifecycle,
    OutputRef,
    ProjectId,
    QueueClaimStatus,
    QueueItemState,
)
from orquestador.persistence import CorruptDatabaseError, PersistenceConflict, SQLiteProjectRepository


class _DurableStarter:
    """Controlled engine seam that uses the real scheduler start boundary."""

    def __init__(self, repository, *, terminal=None, pause_during_run=False,
                 fail_before_submit=False, ambiguous_submit=False):
        self.repository = repository
        self.terminal = terminal
        self.pause_during_run = pause_during_run
        self.fail_before_submit = fail_before_submit
        self.ambiguous_submit = ambiguous_submit
        self.calls = []
        self.submits = 0

    def __call__(self, project_id, execution_id, queue_item_id):
        self.calls.append((project_id, execution_id, queue_item_id))
        if self.fail_before_submit:
            raise RuntimeError("pre-submit boundary failed")
        project, executions = self.repository.load(ProjectId(project_id))
        execution = next(item for item in executions if str(item.id) == execution_id)
        execution.transition(Lifecycle.RUNNING)
        self.repository.start_execution_from_active_queue_claim(
            project, execution, queue_item_id
        )
        if self.pause_during_run:
            self.repository.set_queue_paused(True)
        if self.ambiguous_submit:
            chunk = execution.chunks[0]
            attempt = chunk.new_attempt()
            attempt.assign_external_job_ref(BackendJobRef("accepted-but-ambiguous"))
            self.repository.save(project, [execution])
            self.submits += 1
            raise RuntimeError("submit outcome is ambiguous")
        if self.terminal is None:
            return None
        if self.terminal is Lifecycle.SUCCEEDED:
            for index, chunk in enumerate(execution.chunks):
                chunk.transition(Lifecycle.RUNNING)
                attempt = chunk.new_attempt()
                attempt.transition(Lifecycle.RUNNING)
                attempt.transition(
                    Lifecycle.SUCCEEDED,
                    output=OutputRef(f"outputs/fake-{index}.mp4"),
                    evidence=Evidence("controlled scheduler engine result"),
                )
                chunk.transition(Lifecycle.SUCCEEDED)
        execution.transition(self.terminal)
        self.repository.save(project, [execution])


class F138SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        (self.root / "inputs").mkdir()
        (self.root / "inputs" / "initial.png").write_bytes(b"initial")
        (self.root / "inputs" / "reference.png").write_bytes(b"reference")
        self.repo = SQLiteProjectRepository(self.root)
        self.drafts = DraftUseCase(self.repo)
        self.queue = QueueOperationsUseCase(self.repo)
        self.schedulers = []

    def tearDown(self):
        for scheduler in reversed(self.schedulers):
            try:
                scheduler.stop()
            except Exception:
                pass
        self.repo.close()
        self.temp.cleanup()

    def draft(self, execution_id, *, complete=False):
        defaults = {"label": execution_id}
        if complete:
            defaults = {
                "profile_ref": "minimax-h3-ui",
                "initial_image": "inputs/initial.png",
                "references": ["inputs/reference.png"],
                "chunk_count": 2,
                "prompts": ["one", "two"],
            }
        return self.drafts.create(
            "project",
            execution_id=execution_id,
            defaults=defaults,
            chunks=[{"prompt": "one"}, {"prompt": "two"}],
        )

    def enqueue(self, execution_id, queue_item_id):
        return self.queue.enqueue("project", execution_id, queue_item_id=queue_item_id)

    def scheduler(self, starter, *, readiness=None):
        scheduler = SingleExecutionScheduler(
            self.repo,
            SchedulerExecutionBoundary(starter, readiness=readiness),
            SchedulerInstanceLock(self.root),
        )
        self.schedulers.append(scheduler)
        scheduler.start()
        return scheduler

    def load_execution(self, execution_id):
        project, executions = self.repo.load(ProjectId("project"))
        return project, next(item for item in executions if str(item.id) == execution_id)

    def test_claim_empty_paused_fifo_reorder_and_control_update(self):
        self.assertEqual(self.repo.claim_next_queue_item().status, QueueClaimStatus.EMPTY)
        first = self.draft("first")
        second = self.draft("second")
        third = self.draft("third")
        one = self.enqueue(first.execution_id, "one")
        two = self.enqueue(second.execution_id, "two")
        three = self.enqueue(third.execution_id, "three")
        self.queue.reorder([three.id, one.id, two.id])

        self.queue.pause()
        paused = self.repo.claim_next_queue_item()
        self.assertEqual(paused.status, QueueClaimStatus.PAUSED)
        self.assertEqual(self.repo.get_queue_control().active_queue_item_id, None)
        self.queue.resume()

        claimed = self.repo.claim_next_queue_item()
        self.assertEqual(claimed.status, QueueClaimStatus.CLAIMED)
        self.assertEqual((str(claimed.item.id), claimed.item.state), ("three", QueueItemState.ACTIVE))
        control = self.repo.get_queue_control()
        self.assertEqual(control.active_queue_item_id, claimed.item.id)
        self.assertEqual(control.revision, 3)
        again = self.repo.claim_next_queue_item()
        self.assertEqual(again.status, QueueClaimStatus.ACTIVE_PRESENT)
        self.assertEqual(str(again.active_queue_item_id), "three")
        self.assertEqual(
            [(str(item.id), item.state) for item in self.repo.list_queue_items()],
            [("three", QueueItemState.ACTIVE), ("one", QueueItemState.QUEUED), ("two", QueueItemState.QUEUED)],
        )

    def test_claim_race_between_real_sqlite_connections_has_one_winner(self):
        first = self.draft("first")
        second = self.draft("second")
        self.enqueue(first.execution_id, "first-item")
        self.enqueue(second.execution_id, "second-item")
        barrier = threading.Barrier(2)
        results = []
        errors = []
        result_lock = threading.Lock()

        def claim_in_connection():
            repository = None
            try:
                repository = SQLiteProjectRepository(self.root)
                barrier.wait(timeout=5)
                result = repository.claim_next_queue_item()
                with result_lock:
                    results.append(result)
            except Exception as exc:
                with result_lock:
                    errors.append(exc)
            finally:
                if repository is not None:
                    repository.close()

        threads = [threading.Thread(target=claim_in_connection) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertFalse(errors, errors)
        self.assertEqual(len(results), 2)
        self.assertEqual(
            sorted(result.status for result in results),
            sorted((QueueClaimStatus.CLAIMED, QueueClaimStatus.ACTIVE_PRESENT)),
        )
        items = self.repo.list_queue_items()
        self.assertEqual(sum(item.state is QueueItemState.ACTIVE for item in items), 1)
        self.assertEqual(sum(item.state is QueueItemState.QUEUED for item in items), 1)
        control = self.repo.get_queue_control()
        self.assertEqual(
            str(control.active_queue_item_id),
            str(next(item.id for item in items if item.state is QueueItemState.ACTIVE)),
        )

    def test_claim_inconsistency_and_active_survivor_fail_closed(self):
        draft = self.draft("inconsistent")
        item = self.enqueue(draft.execution_id, "inconsistent-item")
        self.repo.db.execute(
            "UPDATE queue_control SET active_queue_item_id=? WHERE singleton=1",
            (str(item.id),),
        )
        with self.assertRaises(CorruptDatabaseError):
            self.repo.claim_next_queue_item()
        self.repo.db.execute(
            "UPDATE queue_control SET active_queue_item_id=NULL WHERE singleton=1"
        )
        claimed = self.repo.claim_next_queue_item()
        self.assertEqual(claimed.status, QueueClaimStatus.CLAIMED)
        calls = []
        scheduler = self.scheduler(lambda *args: calls.append(args))
        result = scheduler.tick()
        self.assertEqual(result.outcome, SchedulerTickOutcome.RECOVERY_REQUIRED)
        self.assertEqual(calls, [])
        self.assertEqual(self.repo.get_queue_item(item.id).state, QueueItemState.ACTIVE)
        self.assertEqual(str(self.repo.get_queue_control().active_queue_item_id), item.id)

    def test_instance_lock_rejects_second_scheduler_and_releases(self):
        first = SchedulerInstanceLock(self.root)
        second = SchedulerInstanceLock(self.root)
        first.acquire()
        try:
            with self.assertRaises(SchedulerLockError):
                second.acquire()
        finally:
            first.release()
        second.acquire()
        self.assertTrue(second.is_held)
        second.release()
        self.assertFalse(second.is_held)

    def test_start_claimed_reuses_existing_chain_boundary_and_manual_start_stays_blocked(self):
        draft = self.draft("prepared", complete=True)
        item = self.enqueue(draft.execution_id, "prepared-item")

        class Chain:
            def __init__(self):
                self.calls = []

            def run(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                return "chain-result"

        chain = Chain()
        start = StartGuiChainUseCase(self.repo, self.root, chain)
        with self.assertRaises(StartPreparationError):
            start("project", draft.execution_id)
        claim = self.repo.claim_next_queue_item()
        self.assertEqual(claim.status, QueueClaimStatus.CLAIMED)
        with self.assertRaises(StartPreparationError):
            start("project", draft.execution_id, queue_item_id=item.id)
        self.assertEqual(
            start.start_claimed("project", draft.execution_id, item.id),
            "chain-result",
        )
        self.assertEqual(len(chain.calls), 1)
        self.assertEqual(chain.calls[0][1]["queue_item_id"], item.id)
        self.assertEqual(chain.calls[0][0][1].state, Lifecycle.PENDING)

    def test_scheduler_terminalizes_succeeded_failed_and_cancelled_items(self):
        for terminal in (Lifecycle.SUCCEEDED, Lifecycle.FAILED, Lifecycle.CANCELLED):
            with self.subTest(terminal=terminal.value):
                root = self.root / terminal.value
                root.mkdir()
                repository = SQLiteProjectRepository(root)
                drafts = DraftUseCase(repository)
                created = drafts.create(
                    "project",
                    execution_id="execution",
                    defaults={"label": terminal.value},
                    chunks=[{"prompt": "one"}, {"prompt": "two"}],
                )
                QueueOperationsUseCase(repository).enqueue(
                    "project", created.execution_id, queue_item_id="item"
                )
                starter = _DurableStarter(repository, terminal=terminal)
                scheduler = SingleExecutionScheduler(
                    repository,
                    SchedulerExecutionBoundary(starter),
                    SchedulerInstanceLock(root),
                )
                try:
                    scheduler.start()
                    result = scheduler.tick()
                    self.assertEqual(result.outcome, SchedulerTickOutcome.FINISHED)
                    self.assertEqual(repository.get_queue_item("item").state, QueueItemState.FINISHED)
                    self.assertIsNone(repository.get_queue_control().active_queue_item_id)
                    _, execution = self._load(repository, "execution")
                    self.assertEqual(execution.state, terminal)
                finally:
                    scheduler.close()

    @staticmethod
    def _load(repository, execution_id):
        project, executions = repository.load(ProjectId("project"))
        return project, next(item for item in executions if str(item.id) == execution_id)

    def test_next_item_starts_only_after_prior_terminalization_and_pause_preserves_active(self):
        first = self.draft("first")
        second = self.draft("second")
        one = self.enqueue(first.execution_id, "one")
        two = self.enqueue(second.execution_id, "two")
        starter = _DurableStarter(
            self.repo, terminal=Lifecycle.SUCCEEDED, pause_during_run=True
        )
        scheduler = self.scheduler(starter)

        first_result = scheduler.tick()
        self.assertEqual(first_result.outcome, SchedulerTickOutcome.FINISHED)
        self.assertEqual(self.repo.get_queue_item(one.id).state, QueueItemState.FINISHED)
        self.assertTrue(self.repo.get_queue_control().paused)
        self.assertEqual(self.repo.get_queue_item(two.id).state, QueueItemState.QUEUED)
        paused = scheduler.tick()
        self.assertEqual(paused.outcome, SchedulerTickOutcome.PAUSED)
        self.assertEqual(len(starter.calls), 1)
        self.assertEqual(self.repo.get_queue_item(two.id).state, QueueItemState.QUEUED)

        self.queue.resume()
        second_result = scheduler.tick()
        self.assertEqual(second_result.outcome, SchedulerTickOutcome.FINISHED)
        self.assertEqual([call[1] for call in starter.calls], [first.execution_id, second.execution_id])
        self.assertEqual(self.repo.get_queue_item(two.id).state, QueueItemState.FINISHED)

    def test_pause_with_an_existing_active_never_cancels_or_starts_next(self):
        first = self.draft("first")
        second = self.draft("second")
        active = self.enqueue(first.execution_id, "active-item")
        queued = self.enqueue(second.execution_id, "queued-item")
        self.assertEqual(self.repo.claim_next_queue_item().status, QueueClaimStatus.CLAIMED)
        self.queue.pause()
        calls = []
        scheduler = self.scheduler(lambda *args: calls.append(args))

        result = scheduler.tick()
        self.assertEqual(result.outcome, SchedulerTickOutcome.RECOVERY_REQUIRED)
        self.assertEqual(calls, [])
        self.assertEqual(self.repo.get_queue_item(active.id).state, QueueItemState.ACTIVE)
        self.assertEqual(self.repo.get_queue_item(queued.id).state, QueueItemState.QUEUED)
        self.assertEqual(str(self.repo.get_queue_control().active_queue_item_id), str(active.id))

    def test_error_or_ambiguous_submit_never_reinvokes_the_claimed_engine(self):
        for label, starter_kwargs in (
            ("before-submit", {"fail_before_submit": True}),
            ("ambiguous-submit", {"ambiguous_submit": True}),
        ):
            with self.subTest(label=label):
                root = self.root / label
                root.mkdir()
                repository = SQLiteProjectRepository(root)
                drafts = DraftUseCase(repository)
                created = drafts.create(
                    "project", execution_id="execution", defaults={"label": label},
                    chunks=[{"prompt": "one"}, {"prompt": "two"}],
                )
                QueueOperationsUseCase(repository).enqueue(
                    "project", created.execution_id, queue_item_id="item"
                )
                starter = _DurableStarter(repository, **starter_kwargs)
                scheduler = SingleExecutionScheduler(
                    repository,
                    SchedulerExecutionBoundary(starter),
                    SchedulerInstanceLock(root),
                )
                try:
                    scheduler.start()
                    first = scheduler.tick()
                    self.assertEqual(first.outcome, SchedulerTickOutcome.BLOCKED)
                    second = scheduler.tick()
                    self.assertEqual(second.outcome, SchedulerTickOutcome.RECOVERY_REQUIRED)
                    self.assertEqual(len(starter.calls), 1)
                    self.assertEqual(repository.get_queue_item("item").state, QueueItemState.ACTIVE)
                    self.assertEqual(repository.get_queue_control().active_queue_item_id.value, "item")
                    if starter_kwargs.get("ambiguous_submit"):
                        _, execution = self._load(repository, "execution")
                        self.assertEqual(len(execution.chunks[0].attempts), 1)
                        self.assertEqual(
                            execution.chunks[0].attempts[0].external_job_ref,
                            BackendJobRef("accepted-but-ambiguous"),
                        )
                        self.assertEqual(starter.submits, 1)
                finally:
                    scheduler.close()

    def test_readiness_failure_keeps_queued_item_unclaimed(self):
        draft = self.draft("ready")
        item = self.enqueue(draft.execution_id, "ready-item")
        calls = []

        def readiness():
            raise RuntimeError("configured output root is unavailable")

        scheduler = self.scheduler(lambda *args: calls.append(args), readiness=readiness)
        result = scheduler.tick()
        self.assertEqual(result.outcome, SchedulerTickOutcome.BLOCKED)
        self.assertEqual(calls, [])
        self.assertEqual(self.repo.get_queue_item(item.id).state, QueueItemState.QUEUED)
        self.assertIsNone(self.repo.get_queue_control().active_queue_item_id)

    def test_finish_requires_exact_terminal_active_relationship(self):
        draft = self.draft("finish")
        item = self.enqueue(draft.execution_id, "finish-item")
        claim = self.repo.claim_next_queue_item()
        self.assertEqual(claim.status, QueueClaimStatus.CLAIMED)
        with self.assertRaises(PersistenceConflict):
            self.repo.finish_claimed_queue_item(item.id, draft.execution_id)
        self.assertEqual(self.repo.get_queue_item(item.id).state, QueueItemState.ACTIVE)

        project, execution = self.load_execution(draft.execution_id)
        execution.transition(Lifecycle.RUNNING)
        self.repo.start_execution_from_active_queue_claim(project, execution, item.id)
        execution.transition(Lifecycle.FAILED)
        self.repo.save(project, [execution])
        with self.assertRaises(PersistenceConflict):
            self.repo.finish_claimed_queue_item("other-item", draft.execution_id)
        finished = self.repo.finish_claimed_queue_item(item.id, draft.execution_id)
        self.assertEqual(finished.state, QueueItemState.FINISHED)
        self.assertIsNone(self.repo.get_queue_control().active_queue_item_id)

    def test_background_runner_constructs_and_drives_scheduler_off_the_calling_thread(self):
        started = threading.Event()
        closed = threading.Event()
        observed_threads = []
        main_thread = threading.get_ident()

        class FakeScheduler:
            def start(self):
                observed_threads.append(threading.get_ident())

            def tick(self):
                started.set()
                return SchedulerTickResult(SchedulerTickOutcome.IDLE)

            def close(self):
                closed.set()

        runner = SchedulerBackgroundRunner(lambda: FakeScheduler(), poll_interval=0.01)
        runner.start()
        try:
            self.assertTrue(started.wait(2))
            self.assertNotEqual(observed_threads, [main_thread])
        finally:
            self.assertTrue(runner.stop(timeout=2))
        self.assertTrue(closed.wait(2))

    def test_background_runner_propagates_lock_start_failure_without_driving_work(self):
        ticks = []
        closed = []

        class LockBlockedScheduler:
            def start(self):
                raise SchedulerLockError("another scheduler owns the lock")

            def tick(self):
                ticks.append("unexpected")

            def close(self):
                closed.append(True)

        runner = SchedulerBackgroundRunner(lambda: LockBlockedScheduler())
        with self.assertRaises(SchedulerLockError):
            runner.start()
        self.assertEqual(ticks, [])
        self.assertEqual(closed, [True])
        self.assertFalse(runner.running)

    def test_composition_exposes_an_unstarted_scheduler_runtime(self):
        from orquestador.ui.app import AppConfig, compose

        root = self.root / "composition"
        root.mkdir()
        _, resources = compose(AppConfig(root))
        try:
            self.assertIsInstance(resources["scheduler"], SchedulerBackgroundRunner)
            self.assertFalse(resources["scheduler"].running)
        finally:
            resources["scheduler"].stop(timeout=0)
            resources["repository"].close()

    def test_launch_starts_and_stops_scheduler_without_an_output_root(self):
        from orquestador.ui.app import AppConfig, launch

        calls = []

        class Application:
            @classmethod
            def instance(cls):
                return None

            def __init__(self, *_):
                calls.append("application")

            def setOrganizationName(self, _):
                pass

            def setApplicationName(self, _):
                pass

            def exec(self):
                return 17

        class Window:
            def __init__(self, *_):
                calls.append("window")

            def show(self):
                calls.append("show")

        class Scheduler:
            def start(self):
                calls.append("scheduler-start")

            def stop(self):
                calls.append("scheduler-stop")

        class Repository:
            def close(self):
                calls.append("repository-close")

        fake_window_module = SimpleNamespace(MainWindow=Window)
        resources = {"scheduler": Scheduler(), "repository": Repository()}
        with (
            patch.dict("sys.modules", {"orquestador.ui.main_window": fake_window_module}),
            patch("orquestador.ui.app.compose", return_value=(object(), resources)),
            patch("importlib.import_module", return_value=SimpleNamespace(QApplication=Application)),
        ):
            self.assertEqual(launch(AppConfig(self.root)), 17)
        self.assertEqual(
            calls,
            ["application", "scheduler-start", "window", "show", "scheduler-stop", "repository-close"],
        )

    def test_composed_scheduler_smoke_uses_existing_engine_with_simulated_backend(self):
        from orquestador.ui.app import AppConfig, compose

        root = self.root / "composed-smoke"
        output_root = root / "comfy-output"
        (root / "inputs").mkdir(parents=True)
        (root / "inputs" / "initial.png").write_bytes(b"initial")
        (root / "inputs" / "reference.png").write_bytes(b"reference")
        (output_root / "video").mkdir(parents=True)

        class Client:
            submits = []

            def __init__(self, endpoint):
                self.endpoint = endpoint

            def upload_image(self, path, *, subfolder="", overwrite=False, requested_filename=None):
                return {"type": "input", "name": requested_filename, "subfolder": subfolder}

            def submit(self, prompt, **_):
                ref = BackendJobRef(f"scheduler-job-{len(self.submits) + 1}")
                self.submits.append((ref, prompt))
                (output_root / "video" / f"{ref.value}.mp4").write_bytes(b"simulated video")
                return ref

            def history(self, ref):
                return HistoryResult(
                    ref,
                    HistoryState.SUCCEEDED,
                    {"outputs": {"92": {"images": [{
                        "filename": f"{ref.value}.mp4",
                        "subfolder": "video",
                        "type": "output",
                    }]}}},
                )

        class Extractor:
            def extract_last_frame(self, source, destination):
                destination = Path(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"simulated n-minus-one frame")
                return type("Frame", (), {"frame_index": 0, "frame_count": 1})()

        _, resources = compose(
            AppConfig(root, comfyui_output_root=output_root),
            client_factory=lambda endpoint: Client(endpoint),
            extractor_factory=lambda: Extractor(),
        )
        runner = resources["scheduler"]
        try:
            created = DraftUseCase(resources["repository"]).create(
                "project",
                execution_id="scheduled",
                defaults={
                    "profile_ref": "minimax-h3-ui",
                    "initial_image": "inputs/initial.png",
                    "references": ["inputs/reference.png"],
                    "chunk_count": 2,
                    "prompts": ["one", "two"],
                },
                chunks=[{"prompt": "one"}, {"prompt": "two"}],
            )
            QueueOperationsUseCase(resources["repository"]).enqueue(
                "project", created.execution_id, queue_item_id="scheduled-item"
            )
            runner.start()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if resources["repository"].get_queue_item("scheduled-item").state is QueueItemState.FINISHED:
                    break
                time.sleep(0.02)
            self.assertEqual(resources["repository"].get_queue_item("scheduled-item").state, QueueItemState.FINISHED)
            self.assertIsNone(resources["repository"].get_queue_control().active_queue_item_id)
            self.assertEqual(len(Client.submits), 2)
            _, execution = self._load(resources["repository"], "scheduled")
            self.assertEqual(execution.state, Lifecycle.SUCCEEDED)
            self.assertTrue(all(chunk.state is Lifecycle.SUCCEEDED for chunk in execution.chunks))
            self.assertEqual(
                [attempt.external_job_ref for chunk in execution.chunks for attempt in chunk.attempts],
                [BackendJobRef("scheduler-job-1"), BackendJobRef("scheduler-job-2")],
            )
        finally:
            self.assertTrue(runner.stop(timeout=5))
            resources["repository"].close()


if __name__ == "__main__":
    unittest.main()
