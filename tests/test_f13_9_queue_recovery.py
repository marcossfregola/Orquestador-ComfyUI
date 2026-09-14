import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from orquestador.adapters.http import HistoryResult, HistoryState
from orquestador.application.chain_execution import ChainExecutionUseCase, ChainOutcome
from orquestador.application.drafts import DraftUseCase
from orquestador.application.queue_operations import QueueOperationsUseCase
from orquestador.application.queue_recovery import ActiveQueueRecoveryUseCase
from orquestador.application.recover_execution import (
    RecoveryExecutionResult,
    RecoveryOutcome,
    ResumeExecutionUseCase,
)
from orquestador.application.scheduler import (
    SchedulerExecutionBoundary,
    SchedulerInstanceLock,
    SchedulerTickOutcome,
    SingleExecutionScheduler,
)
from orquestador.domain import (
    Artifact,
    BackendJobRef,
    BackendJobObservation,
    BackendJobState,
    Evidence,
    Lifecycle,
    OutputRef,
    Phase,
    ProjectId,
    QueueItemState,
    TransitionFrame,
)
from orquestador.persistence import SQLiteProjectRepository


class _ObservedBackend:
    def __init__(self, repository, state):
        self.repository = repository
        self.state = state
        self.calls = []

    def observe(self, ref):
        self.calls.append(ref)
        project, executions = self.repository.load(ProjectId("project"))
        execution = next(entry for entry in executions if entry.state is not Lifecycle.SUCCEEDED)
        chunk = next(entry for entry in execution.chunks if entry.state is not Lifecycle.SUCCEEDED)
        attempt = chunk.attempts[-1]
        return BackendJobObservation(
            str(project.id), str(execution.id), str(chunk.id), str(attempt.id), self.state, ref
        )


class F139QueueRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.output_root = self.root / "comfy-output"
        self.output_root.mkdir()
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
        try:
            self.repo.close()
        except Exception:
            pass
        self.temp.cleanup()

    def _queue_two(self):
        first = self.drafts.create(
            "project", execution_id="first", defaults={"label": "first"},
            chunks=[{"prompt": "one"}, {"prompt": "two"}],
        )
        second = self.drafts.create(
            "project", execution_id="second", defaults={"label": "second"},
            chunks=[{"prompt": "one"}, {"prompt": "two"}],
        )
        active = self.queue.enqueue("project", first.execution_id, queue_item_id="active")
        queued = self.queue.enqueue("project", second.execution_id, queue_item_id="queued")
        claimed = self.repo.claim_next_queue_item()
        self.assertEqual(str(claimed.item.id), str(active.id))
        return active, queued

    def _load(self, execution_id="first"):
        project, executions = self.repo.load(ProjectId("project"))
        return project, next(entry for entry in executions if str(entry.id) == execution_id)

    def _make_running_attempt(self, *, ref=BackendJobRef("known-job")):
        project, execution = self._load()
        execution.transition(Lifecycle.RUNNING)
        self.repo.start_execution_from_active_queue_claim(project, execution, "active")
        chunk = execution.chunks[0]
        chunk.transition(Lifecycle.RUNNING)
        attempt = chunk.new_attempt()
        if ref is not None:
            attempt.assign_external_job_ref(ref)
        self.repo.save(project, [execution])
        return self._load()

    def _resume(self, backend, submit_boundary=None):
        return ResumeExecutionUseCase(
            self.repo, backend, coordinator=None,
            submitter=submit_boundary if submit_boundary is not None else Mock(),
            output_root=self.output_root,
        )

    def _scheduler(self, start_claimed, resume_claimed, *, validator=None):
        if validator is None:
            validator = self._resume(None).is_durably_complete
        recovery = ActiveQueueRecoveryUseCase(
            self.repo, start_claimed, resume_claimed,
            completion_validator=validator,
        )
        scheduler = SingleExecutionScheduler(
            self.repo,
            SchedulerExecutionBoundary(start_claimed, reconcile_active=recovery.reconcile),
            SchedulerInstanceLock(self.root),
        )
        scheduler.start()
        self.schedulers.append(scheduler)
        return scheduler

    def _durable_success(self, *, terminal=True):
        project, execution = self._load()
        execution.transition(Lifecycle.RUNNING)
        self.repo.start_execution_from_active_queue_claim(project, execution, "active")
        artifacts = []
        transitions = []
        for index, chunk in enumerate(execution.chunks):
            chunk.transition(Lifecycle.RUNNING)
            attempt = chunk.new_attempt()
            attempt.transition(Lifecycle.RUNNING)
            output = OutputRef(f"outputs/recovered-{index}.mp4")
            path = self.root / output.uri
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"durable video")
            attempt.transition(Lifecycle.SUCCEEDED, output=output, evidence=Evidence("verified"))
            chunk.transition(Lifecycle.SUCCEEDED)
            artifacts.append(Artifact(project.id, execution.id, chunk.id, attempt.id, Phase.OUTPUT, output))
            target = execution.chunks[index + 1].id if index + 1 < len(execution.chunks) else None
            transitions.append(TransitionFrame(
                project.id, execution.id, chunk.id, attempt.id, output, 0, 1, target,
            ))
        if terminal:
            execution.transition(Lifecycle.SUCCEEDED)
        self.repo.save(project, [execution], artifacts=artifacts, transitions=transitions)

    def test_terminal_success_survives_restart_and_releases_before_next_claim(self):
        active, queued = self._queue_two()
        self._durable_success(terminal=True)
        self.repo.close()
        self.repo = SQLiteProjectRepository(self.root)

        calls = []
        scheduler = self._scheduler(
            lambda *args: calls.append(("start", args)),
            lambda *args: calls.append(("resume", args)),
        )
        result = scheduler.tick()

        self.assertEqual(result.outcome, SchedulerTickOutcome.FINISHED)
        self.assertEqual(self.repo.get_queue_item(active.id).state, QueueItemState.FINISHED)
        self.assertEqual(self.repo.get_queue_item(queued.id).state, QueueItemState.QUEUED)
        self.assertEqual(calls, [])

    def test_durable_outputs_promote_lost_success_transition_without_backend_submit(self):
        active, queued = self._queue_two()
        self._durable_success(terminal=False)
        calls = []
        scheduler = self._scheduler(
            lambda *args: calls.append(("start", args)),
            lambda *args: calls.append(("resume", args)),
        )

        result = scheduler.tick()

        self.assertEqual(result.outcome, SchedulerTickOutcome.FINISHED)
        _, execution = self._load()
        self.assertEqual(execution.state, Lifecycle.SUCCEEDED)
        self.assertEqual(self.repo.get_queue_item(active.id).state, QueueItemState.FINISHED)
        self.assertEqual(self.repo.get_queue_item(queued.id).state, QueueItemState.QUEUED)
        self.assertEqual(calls, [])

    def test_bound_live_job_waits_without_submit_or_next_claim(self):
        active, queued = self._queue_two()
        _, execution = self._make_running_attempt()
        backend = _ObservedBackend(self.repo, BackendJobState.RUNNING)
        submit = Mock()
        resume = self._resume(backend, submit)
        starts = []
        scheduler = self._scheduler(
            lambda *args: starts.append(args),
            lambda project_id, execution_id, queue_item_id: resume.resume(
                project_id, execution_id, allow_submit=False
            ),
            validator=resume.is_durably_complete,
        )

        result = scheduler.tick()

        self.assertEqual(result.outcome, SchedulerTickOutcome.RECOVERY_REQUIRED)
        self.assertEqual(backend.calls, [execution.chunks[0].attempts[0].external_job_ref])
        submit.submit.assert_not_called()
        self.assertEqual(starts, [])
        self.assertEqual(self.repo.get_queue_item(active.id).state, QueueItemState.ACTIVE)
        self.assertEqual(self.repo.get_queue_item(queued.id).state, QueueItemState.QUEUED)

    def test_unbound_attempt_is_ambiguous_and_never_restarts_or_submits(self):
        active, queued = self._queue_two()
        self._make_running_attempt(ref=None)
        calls = []
        scheduler = self._scheduler(
            lambda *args: calls.append(("start", args)),
            lambda *args: calls.append(("resume", args)),
        )

        result = scheduler.tick()

        self.assertEqual(result.outcome, SchedulerTickOutcome.RECOVERY_REQUIRED)
        self.assertIn("no external_job_ref", result.reason)
        self.assertEqual(calls, [])
        self.assertEqual(self.repo.get_queue_item(active.id).state, QueueItemState.ACTIVE)
        self.assertEqual(self.repo.get_queue_item(queued.id).state, QueueItemState.QUEUED)

    def test_paused_active_defers_reconciliation_and_keeps_next_queued(self):
        active, queued = self._queue_two()
        self.queue.pause()
        calls = []
        scheduler = self._scheduler(
            lambda *args: calls.append(("start", args)),
            lambda *args: calls.append(("resume", args)),
        )

        result = scheduler.tick()

        self.assertEqual(result.outcome, SchedulerTickOutcome.RECOVERY_REQUIRED)
        self.assertIn("paused", result.reason)
        self.assertEqual(calls, [])
        self.assertEqual(self.repo.get_queue_item(active.id).state, QueueItemState.ACTIVE)
        self.assertEqual(self.repo.get_queue_item(queued.id).state, QueueItemState.QUEUED)

    def test_queue_recovery_chain_passes_no_submit_authority_to_existing_resume(self):
        self._queue_two()
        project, execution = self._make_running_attempt()
        calls = []

        class Recovery:
            def resume(self, project_id, execution_id, **kwargs):
                calls.append((project_id, execution_id, kwargs))
                return RecoveryExecutionResult(RecoveryOutcome.WAIT, str(execution_id))

        result = ChainExecutionUseCase(self.repo, coordinator=None, recovery=Recovery()).run(
            project, execution, [{}, {}], queue_item_id="active", queue_recovery=True,
        )

        self.assertEqual(result.outcome, ChainOutcome.WAIT)
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0][2]["allow_submit"], False)

    def test_pre_submit_survivors_start_or_continue_only_once(self):
        for label, running in (("claimed", False), ("started", True)):
            with self.subTest(label=label):
                root = self.root / label
                root.mkdir()
                repository = SQLiteProjectRepository(root)
                try:
                    drafts = DraftUseCase(repository)
                    queue = QueueOperationsUseCase(repository)
                    first = drafts.create("project", execution_id="first", defaults={"label": label}, chunks=[{"prompt": "one"}, {"prompt": "two"}])
                    second = drafts.create("project", execution_id="second", defaults={"label": "next"}, chunks=[{"prompt": "one"}, {"prompt": "two"}])
                    queue.enqueue("project", first.execution_id, queue_item_id="active")
                    queued = queue.enqueue("project", second.execution_id, queue_item_id="queued")
                    repository.claim_next_queue_item()
                    if running:
                        project, execution = repository.load(ProjectId("project"))
                        execution = next(entry for entry in execution if str(entry.id) == "first")
                        execution.transition(Lifecycle.RUNNING)
                        repository.start_execution_from_active_queue_claim(project, execution, "active")
                    starts = []
                    submits = []

                    def bind_first_attempt(project_id, execution_id, queue_item_id, *, start=False):
                        project, executions = repository.load(ProjectId(project_id))
                        execution = next(entry for entry in executions if str(entry.id) == str(execution_id))
                        if start:
                            execution.transition(Lifecycle.RUNNING)
                            repository.start_execution_from_active_queue_claim(project, execution, queue_item_id)
                            starts.append(execution_id)
                        chunk = execution.chunks[0]
                        if not chunk.attempts:
                            chunk.transition(Lifecycle.RUNNING)
                            attempt = chunk.new_attempt()
                            attempt.assign_external_job_ref(BackendJobRef(f"{label}-job"))
                            repository.save(project, [execution])
                            submits.append(execution_id)
                        return SimpleNamespace(outcome="wait")

                    resume = ResumeExecutionUseCase(repository, None, None, None)
                    reconciliation = ActiveQueueRecoveryUseCase(
                        repository,
                        lambda *args: bind_first_attempt(*args, start=True),
                        lambda *args: bind_first_attempt(*args, start=False),
                        completion_validator=resume.is_durably_complete,
                    )
                    scheduler = SingleExecutionScheduler(
                        repository,
                        SchedulerExecutionBoundary(
                            lambda *args: bind_first_attempt(*args, start=True),
                            reconcile_active=reconciliation.reconcile,
                        ),
                        SchedulerInstanceLock(root),
                    )
                    scheduler.start()
                    try:
                        self.assertEqual(scheduler.tick().outcome, SchedulerTickOutcome.RECOVERY_REQUIRED)
                        self.assertEqual(scheduler.tick().outcome, SchedulerTickOutcome.RECOVERY_REQUIRED)
                    finally:
                        scheduler.stop()
                    self.assertEqual(starts, [] if running else ["first"])
                    self.assertEqual(submits, ["first"])
                    self.assertEqual(repository.get_queue_item(queued.id).state, QueueItemState.QUEUED)
                finally:
                    try:
                        repository.close()
                    except Exception:
                        pass

    def test_unattempted_next_chunk_reenters_existing_chain_after_prior_chunk(self):
        self._queue_two()
        project, execution = self._load()
        execution.transition(Lifecycle.RUNNING)
        self.repo.start_execution_from_active_queue_claim(project, execution, "active")
        first = execution.chunks[0]
        first.transition(Lifecycle.RUNNING)
        attempt = first.new_attempt()
        attempt.transition(Lifecycle.RUNNING)
        attempt.transition(
            Lifecycle.SUCCEEDED,
            output=OutputRef("outputs/previous.mp4"), evidence=Evidence("previous durable result"),
        )
        first.transition(Lifecycle.SUCCEEDED)
        self.repo.save(project, [execution])
        calls = []
        scheduler = self._scheduler(
            lambda *args: self.fail("a non-virgin active execution must not restart"),
            lambda *args: calls.append(args) or SimpleNamespace(outcome="wait"),
        )

        result = scheduler.tick()

        self.assertEqual(result.outcome, SchedulerTickOutcome.RECOVERY_REQUIRED)
        self.assertEqual(len(calls), 1)

    def test_missing_backend_job_stays_active_for_manual_review_without_retry(self):
        active, queued = self._queue_two()
        _, execution = self._make_running_attempt()

        class MissingBackend:
            def __init__(self):
                self.calls = []

            def observe(self, ref):
                self.calls.append(ref)
                return HistoryResult(ref, HistoryState.NOT_FOUND)

        backend = MissingBackend()
        submit = Mock()
        resume = self._resume(backend, submit)
        scheduler = self._scheduler(
            lambda *args: self.fail("missing job must not restart a claimed execution"),
            lambda project_id, execution_id, queue_item_id: resume.resume(
                project_id, execution_id, allow_submit=False
            ),
            validator=resume.is_durably_complete,
        )

        result = scheduler.tick()

        self.assertEqual(result.outcome, SchedulerTickOutcome.RECOVERY_REQUIRED)
        self.assertIn("stale job recovery", result.reason)
        self.assertEqual(backend.calls, [execution.chunks[0].attempts[0].external_job_ref])
        submit.submit.assert_not_called()
        self.assertEqual(self.repo.get_queue_item(active.id).state, QueueItemState.ACTIVE)
        self.assertEqual(self.repo.get_queue_item(queued.id).state, QueueItemState.QUEUED)

    def test_stale_bound_second_chunk_stages_only_explicit_retry_and_holds_active(self):
        active, queued = self._queue_two()
        project, execution = self._load()
        execution.transition(Lifecycle.RUNNING)
        self.repo.start_execution_from_active_queue_claim(project, execution, active.id)
        first = execution.chunks[0]
        first.transition(Lifecycle.RUNNING)
        previous = first.new_attempt()
        previous.transition(Lifecycle.RUNNING)
        output = OutputRef("outputs/predecessor.mp4")
        path = self.root / output.uri
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"predecessor")
        previous.transition(Lifecycle.SUCCEEDED, output=output, evidence=Evidence("predecessor verified"))
        first.transition(Lifecycle.SUCCEEDED)
        artifact = Artifact(project.id, execution.id, first.id, previous.id, Phase.OUTPUT, output)
        transition = TransitionFrame(project.id, execution.id, first.id, previous.id, output, 0, 1, execution.chunks[1].id)
        self.repo.save(project, [execution], artifacts=[artifact], transitions=[transition])
        project, execution = self._load()
        current = execution.chunks[1]
        current.transition(Lifecycle.RUNNING)
        attempt = current.new_attempt()
        attempt.assign_external_job_ref(BackendJobRef("stale-second-job"))
        self.repo.save(project, [execution])

        class MissingBackend:
            def observe(self, ref):
                return HistoryResult(ref, HistoryState.NOT_FOUND)

        submit = Mock()
        resume = self._resume(MissingBackend(), submit)
        scheduler = self._scheduler(
            lambda *args: self.fail("stale job must not restart the chain"),
            lambda project_id, execution_id, queue_item_id: resume.resume(
                project_id, execution_id, allow_submit=False
            ),
            validator=resume.is_durably_complete,
        )

        result = scheduler.tick()

        self.assertEqual(result.outcome, SchedulerTickOutcome.RECOVERY_REQUIRED)
        self.assertIn("explicit Retry required", result.reason)
        _, recovered = self._load()
        attempts = recovered.chunks[1].attempts
        self.assertEqual([entry.state for entry in attempts], [Lifecycle.FAILED, Lifecycle.PENDING])
        self.assertEqual(attempts[-1].external_job_ref, None)
        submit.submit.assert_not_called()
        self.assertEqual(self.repo.get_queue_item(active.id).state, QueueItemState.ACTIVE)
        self.assertEqual(self.repo.get_queue_item(queued.id).state, QueueItemState.QUEUED)

    def test_observed_failed_or_cancelled_job_is_terminalized_without_auto_retry(self):
        for state, expected in (
            (BackendJobState.FAILED, Lifecycle.FAILED),
            (BackendJobState.CANCELLED, Lifecycle.CANCELLED),
        ):
            with self.subTest(state=state.value):
                root = self.root / state.value
                root.mkdir()
                output_root = root / "comfy-output"
                output_root.mkdir()
                repository = SQLiteProjectRepository(root)
                try:
                    drafts = DraftUseCase(repository)
                    queue = QueueOperationsUseCase(repository)
                    first = drafts.create("project", execution_id="first", defaults={"label": state.value}, chunks=[{"prompt": "one"}, {"prompt": "two"}])
                    second = drafts.create("project", execution_id="second", defaults={"label": "next"}, chunks=[{"prompt": "one"}, {"prompt": "two"}])
                    active = queue.enqueue("project", first.execution_id, queue_item_id="active")
                    queued = queue.enqueue("project", second.execution_id, queue_item_id="queued")
                    repository.claim_next_queue_item()
                    project, executions = repository.load(ProjectId("project"))
                    execution = next(entry for entry in executions if str(entry.id) == "first")
                    execution.transition(Lifecycle.RUNNING)
                    repository.start_execution_from_active_queue_claim(project, execution, active.id)
                    chunk = execution.chunks[0]
                    chunk.transition(Lifecycle.RUNNING)
                    attempt = chunk.new_attempt()
                    attempt.assign_external_job_ref(BackendJobRef(f"{state.value}-job"))
                    repository.save(project, [execution])
                    backend = _ObservedBackend(repository, state)
                    submit = Mock()
                    resume = ResumeExecutionUseCase(repository, backend, None, submit, output_root)
                    reconciliation = ActiveQueueRecoveryUseCase(
                        repository,
                        lambda *args: self.fail("bound job must not restart a claimed execution"),
                        lambda project_id, execution_id, queue_item_id: resume.resume(
                            project_id, execution_id, allow_submit=False
                        ),
                        completion_validator=resume.is_durably_complete,
                    )
                    scheduler = SingleExecutionScheduler(
                        repository,
                        SchedulerExecutionBoundary(
                            lambda *args: self.fail("bound job must not start"),
                            reconcile_active=reconciliation.reconcile,
                        ),
                        SchedulerInstanceLock(root),
                    )
                    scheduler.start()
                    try:
                        result = scheduler.tick()
                    finally:
                        scheduler.stop()
                    self.assertEqual(result.outcome, SchedulerTickOutcome.FINISHED)
                    _, refreshed = repository.load(ProjectId("project"))
                    recovered = next(entry for entry in refreshed if str(entry.id) == "first")
                    self.assertEqual(recovered.state, expected)
                    self.assertEqual(repository.get_queue_item(active.id).state, QueueItemState.FINISHED)
                    self.assertEqual(repository.get_queue_item(queued.id).state, QueueItemState.QUEUED)
                    submit.submit.assert_not_called()
                finally:
                    try:
                        repository.close()
                    except Exception:
                        pass
