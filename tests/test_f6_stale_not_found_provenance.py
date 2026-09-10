import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock

from orquestador.domain import (Project, Execution, Chunk, BackendJobRef, Lifecycle,
                                OutputRef, Evidence, Artifact, Phase, TransitionFrame,
                                MaterializedInputRef)
from orquestador.adapters.http import HistoryResult, HistoryState
from orquestador.domain.recovery import BackendJobObservation, BackendJobState
from orquestador.application.bridge import SubmitAttemptResult, SubmitOutcome
from orquestador.application.submit_boundary import SubmitBoundary
from orquestador.application.recover_execution import ResumeExecutionUseCase, RetryExecutionUseCase, RecoveryOutcome
from orquestador.persistence.sqlite import SQLiteProjectRepository
from orquestador.application.chunk_execution import ChunkExecutionCoordinator
from orquestador.adapters.outputs import OutputCorrelationResult, OutputCorrelationStatus, OutputDescriptor
from orquestador.adapters.physical_outputs import PhysicalOutputEvidence, PhysicalOutputStatus
from orquestador.profiles.minimax_h3 import H3_PROFILE


class StaleNotFoundRecoveryTests(unittest.TestCase):
    def tempdir(self):
        root = os.environ.get('ORQ_TEST_TMP', r'C:\Codex\Orquestador-Test-Temp')
        Path(root).mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(dir=root)

    def test_integrated_restart_not_found_retry_reuses_attempt2_and_completes_once(self):
        """Restart/reopen + stale History 404 + explicit retry is one durable flow."""
        with self.tempdir() as d:
            root = Path(d); (root / 'media').mkdir()
            (root / 'media' / 'chunk2.mp4').write_bytes(b'fake-output')
            project = Project(); execution = Execution(project.id)
            project.defaults = execution.defaults = {
                'profile_ref': H3_PROFILE.name, 'initial_image': 'inputs/initial.png',
                'references': [f'inputs/ref{i}.png' for i in range(6)],
                'prompts': ['prompt 0', 'prompt 1'], 'chunk_count': 2,
            }
            predecessor = Chunk(order=0); target = Chunk(order=1)
            execution.add_chunk(predecessor); execution.add_chunk(target)
            execution.transition(Lifecycle.RUNNING); predecessor.transition(Lifecycle.RUNNING)
            prev = predecessor.new_attempt(); prev.assign_external_job_ref(BackendJobRef('prev-ref'))
            prev.transition(Lifecycle.RUNNING); prev.transition(Lifecycle.SUCCEEDED, output=OutputRef('media/chunk1.mp4'), evidence=Evidence('ok'))
            predecessor.transition(Lifecycle.SUCCEEDED); target.transition(Lifecycle.RUNNING)
            attempt1 = target.new_attempt(); attempt1.assign_external_job_ref(BackendJobRef('stale-ref')); attempt1.transition(Lifecycle.RUNNING)
            artifact = Artifact(project.id, execution.id, predecessor.id, prev.id, Phase.OUTPUT, prev.output)
            predecessor_frame = TransitionFrame(project.id, execution.id, predecessor.id, prev.id, prev.output, 9, 10, target.id,
                                                MaterializedInputRef('input', 'transitions', 'prev.png', '0' * 64))
            repo = SQLiteProjectRepository(root, 'integrated.sqlite3')
            repo.save(project, [execution], artifacts=[artifact], transitions=[predecessor_frame]); repo.close()

            # Restart/reopen, then definitively retire Attempt 1 and persist unbound Attempt 2.
            repo = SQLiteProjectRepository(root, 'integrated.sqlite3'); lp, les = repo.load(project.id); le = les[0]
            backend = Mock(); backend.observe.return_value = HistoryResult(BackendJobRef('stale-ref'), HistoryState.NOT_FOUND, {})
            first = ResumeExecutionUseCase(repo, backend, Mock(), Mock()).resume(lp.id, le.id)
            self.assertEqual(first.outcome, RecoveryOutcome.NEEDS_MANUAL_REVIEW)
            repo.close(); repo = SQLiteProjectRepository(root, 'integrated.sqlite3'); _, es = repo.load(project.id); le = es[0]
            target = le.chunks[1]; attempt2_id = target.attempts[1].id
            self.assertEqual([(a.number, a.state, a.external_job_ref) for a in target.attempts], [(1, Lifecycle.FAILED, BackendJobRef('stale-ref')), (2, Lifecycle.PENDING, None)])
            repo.close()

            # Explicit retry after another reopen binds and observes the same Attempt 2.
            repo = SQLiteProjectRepository(root, 'integrated.sqlite3'); lp, les = repo.load(project.id); le = les[0]; target = le.chunks[1]
            transport = Mock(); transport.submit.return_value = BackendJobRef('retry-ref')
            submitter = SubmitBoundary(transport, repository=repo); backend = Mock()
            backend.observe.return_value = BackendJobObservation(str(lp.id), str(le.id), str(target.id), str(attempt2_id), BackendJobState.RUNNING, BackendJobRef('retry-ref'))
            resume = ResumeExecutionUseCase(repo, backend, Mock(), submitter)
            retried = RetryExecutionUseCase(repo, resume).retry(lp.id, le.id)
            self.assertEqual((retried.outcome, retried.attempt_id), (RecoveryOutcome.RETRIED_WAIT, str(attempt2_id)))
            submitted_prompt = transport.submit.call_args.args[0]
            self.assertIsInstance(submitted_prompt, dict)
            self.assertTrue(submitted_prompt)
            repo.close()

            # Completion after reopen uses the same bound Attempt 2 and adds one target output transition.
            repo = SQLiteProjectRepository(root, 'integrated.sqlite3'); lp, les = repo.load(project.id); le = les[0]; target = le.chunks[1]; attempt2 = target.attempts[1]
            desc = OutputDescriptor(BackendJobRef('retry-ref'), '1', 'chunk2.mp4', 'media', 'video')
            corr = OutputCorrelationResult(BackendJobRef('retry-ref'), OutputCorrelationStatus.VALID, (desc,))
            phys = PhysicalOutputEvidence(desc, PhysicalOutputStatus.EXISTS, root, root / 'media' / 'chunk2.mp4')
            extractor = Mock(); extractor.extract_last_frame.return_value = type('Frame', (), {'frame_index': 19, 'frame_count': 20})()
            history = HistoryResult(BackendJobRef('retry-ref'), HistoryState.SUCCEEDED, {'outputs': {}})
            backend = Mock(); backend.observe.return_value = history
            coordinator = ChunkExecutionCoordinator(repo, Mock(), history, extractor=extractor, trusted_root=root, correlator=lambda *_: corr, physical_validator=lambda *_: phys)
            completed = ResumeExecutionUseCase(repo, backend, coordinator, Mock()).resume(lp.id, le.id)
            self.assertEqual((completed.outcome, completed.attempt_id), (RecoveryOutcome.RETRIED_COMPLETE, str(attempt2_id)))
            repo.close()

            repo = SQLiteProjectRepository(root, 'integrated.sqlite3'); _, es = repo.load(project.id); final = es[0]
            self.assertEqual(len(final.chunks[1].attempts), 2); self.assertEqual(final.chunks[1].attempts[1].state, Lifecycle.SUCCEEDED)
            transitions = repo.load_transitions(final.id)
            self.assertEqual(sum(str(t.source_chunk_id) == str(final.chunks[0].id) for t in transitions), 1)
            self.assertEqual(sum(str(t.source_chunk_id) == str(final.chunks[1].id) for t in transitions), 1)
            repo.close()
    def make(self, *, wrong_project=False, wrong_execution=False, pending=False, bind=True):
        project = Project()
        execution = Execution(project.id)
        predecessor = Chunk(order=0)
        target = Chunk(order=1)
        execution.add_chunk(predecessor); execution.add_chunk(target)
        execution.transition(Lifecycle.RUNNING)
        predecessor.transition(Lifecycle.RUNNING)
        previous = predecessor.new_attempt()
        previous.assign_external_job_ref(BackendJobRef('previous'))
        previous.transition(Lifecycle.RUNNING)
        previous.transition(Lifecycle.SUCCEEDED, output=OutputRef('prev.mp4'), evidence=Evidence('ok'))
        predecessor.transition(Lifecycle.SUCCEEDED)
        if not pending: target.transition(Lifecycle.RUNNING)
        current = target.new_attempt()
        if bind: current.assign_external_job_ref(BackendJobRef('stale'))
        if pending: pass
        else: current.transition(Lifecycle.RUNNING)
        artifact = Artifact(Project().id if wrong_project else project.id,
                            execution.id if not wrong_execution else Execution(project.id).id,
                            predecessor.id, previous.id, Phase.OUTPUT, previous.output)
        frame = TransitionFrame(project.id, execution.id, predecessor.id, previous.id,
                                 previous.output, 9, 10, target.id)
        execution.artifacts = [artifact]
        repo = Mock(); repo.load.return_value = (project, [execution]); repo.load_transitions.return_value = (frame,)
        return project, execution, predecessor, target, current, repo

    def use(self, repo, execution, source, submit=True):
        backend = Mock()
        if submit:
            def observe(ref):
                if str(ref) == 'stale': return source
                latest = execution.chunks[1].attempts[-1]
                return BackendJobObservation(str(execution.project_id), str(execution.id),
                    str(execution.chunks[1].id), str(latest.id), BackendJobState.QUEUED, ref)
            backend.observe.side_effect = observe
        else:
            backend.observe.return_value = source
        submitter = Mock()
        def do_submit(project, e, chunk_id, prompt):
            a2 = e.chunks[1].new_attempt(); a2.assign_external_job_ref(BackendJobRef('retry'))
            return SubmitAttemptResult(SubmitOutcome.SUCCEEDED, str(a2.id), a2.external_job_ref)
        submitter.submit.side_effect = do_submit
        return ResumeExecutionUseCase(repo, backend, Mock(), submitter), submitter

    def test_valid_not_found_creates_only_attempt2_and_preserves_predecessor(self):
        p,e,prev,target,current,repo = self.make()
        use, submit = self.use(repo, e, HistoryResult(current.external_job_ref, HistoryState.NOT_FOUND, {}))
        result = use.resume(p.id, e.id)
        self.assertEqual(result.outcome, RecoveryOutcome.NEEDS_MANUAL_REVIEW)
        self.assertEqual([a.number for a in target.attempts], [1, 2])
        self.assertEqual(e.state, Lifecycle.FAILED)
        self.assertEqual(target.state, Lifecycle.FAILED)
        self.assertIsNone(target.attempts[1].external_job_ref)
        submit.submit.assert_not_called()
        self.assertEqual(prev.attempts[0].state, Lifecycle.SUCCEEDED)
        self.assertEqual(len(e.artifacts), 1)

    def test_repeated_not_found_recovery_does_not_create_attempt3(self):
        p,e,prev,target,current,repo = self.make()
        use, submit = self.use(repo, e, HistoryResult(current.external_job_ref, HistoryState.NOT_FOUND, {}))
        self.assertEqual(use.resume(p.id, e.id).outcome, RecoveryOutcome.NEEDS_MANUAL_REVIEW)
        self.assertEqual(use.resume(p.id, e.id).outcome, RecoveryOutcome.NEEDS_MANUAL_REVIEW)
        self.assertEqual(len(target.attempts), 2)

    def test_wrong_artifact_provenance_blocks_manual_review(self):
        p,e,prev,target,current,repo = self.make(wrong_project=True)
        use, submit = self.use(repo, e, HistoryResult(current.external_job_ref, HistoryState.NOT_FOUND, {}))
        self.assertEqual(use.resume(p.id, e.id).outcome, RecoveryOutcome.NEEDS_MANUAL_REVIEW)
        submit.submit.assert_not_called()

    def test_unknown_history_remains_manual_review(self):
        p,e,prev,target,current,repo = self.make()
        use, submit = self.use(repo, e, HistoryResult(current.external_job_ref, HistoryState.UNKNOWN, {}), submit=False)
        self.assertEqual(use.resume(p.id, e.id).outcome, RecoveryOutcome.NEEDS_MANUAL_REVIEW)
        submit.submit.assert_not_called()

    def test_pending_bound_not_found_creates_only_attempt2(self):
        p,e,prev,target,current,repo = self.make(pending=True)
        use, submit = self.use(repo, e, HistoryResult(current.external_job_ref, HistoryState.NOT_FOUND, {}))
        result = use.resume(p.id, e.id)
        self.assertEqual(result.outcome, RecoveryOutcome.NEEDS_MANUAL_REVIEW)
        self.assertEqual([a.number for a in target.attempts], [1, 2])
        self.assertEqual(e.state, Lifecycle.FAILED)
        self.assertEqual(target.state, Lifecycle.FAILED)
        self.assertIsNone(target.attempts[1].external_job_ref)
        submit.submit.assert_not_called()
        self.assertEqual(prev.attempts[0].state, Lifecycle.SUCCEEDED)

    def test_pending_without_ref_is_manual_review(self):
        p,e,prev,target,current,repo = self.make(pending=True, bind=False)
        use, submit = self.use(repo, e, HistoryResult(BackendJobRef('ignored'), HistoryState.NOT_FOUND, {}), submit=False)
        result = use.resume(p.id, e.id)
        self.assertEqual(result.outcome, RecoveryOutcome.NEEDS_MANUAL_REVIEW)
        submit.submit.assert_not_called()

    def test_explicit_retry_reuses_exact_unbound_attempt2(self):
        p,e,prev,target,current,repo = self.make()
        use, submit = self.use(repo, e, HistoryResult(current.external_job_ref, HistoryState.NOT_FOUND, {}))
        first = use.resume(p.id, e.id)
        attempt2 = target.attempts[1]
        submit.submit_existing_pending_attempt.return_value = SubmitAttemptResult(
            SubmitOutcome.SUCCEEDED, str(attempt2.id), BackendJobRef('retry'))
        retry = RetryExecutionUseCase(repo, use)
        result = retry.retry(p.id, e.id, prompt={})
        self.assertEqual(result.outcome, RecoveryOutcome.RETRIED_WAIT)
        self.assertEqual(result.attempt_id, str(attempt2.id))
        self.assertEqual(len(target.attempts), 2)
        submit.submit.assert_not_called()

    def test_submit_boundary_retry_binds_same_attempt_without_transport_repository(self):
        p, e, prev, target, current, repo = self.make()
        current.transition(Lifecycle.FAILED)
        attempt2 = target.new_attempt()
        transport = Mock()
        transport.submit.return_value = BackendJobRef('retry')
        boundary = SubmitBoundary(transport, repository=repo)
        result = boundary.submit_existing_pending_attempt(p, e, target.id, attempt2.id, {})
        self.assertEqual(result.outcome, SubmitOutcome.SUCCEEDED)
        self.assertEqual(result.attempt_id, str(attempt2.id))
        self.assertEqual(attempt2.external_job_ref, BackendJobRef('retry'))
        self.assertEqual(len(target.attempts), 2)

    def test_not_found_without_rehydrated_artifacts_fails_closed(self):
        p,e,prev,target,current,repo = self.make()
        e.artifacts = None
        use, submit = self.use(repo, e, HistoryResult(current.external_job_ref, HistoryState.NOT_FOUND, {}))
        result = use.resume(p.id, e.id)
        self.assertEqual(result.outcome, RecoveryOutcome.NEEDS_MANUAL_REVIEW)
        self.assertIn('artifact', result.reason)
        submit.submit.assert_not_called()

    def test_retry_without_reconstructable_prompt_fails_closed_before_transport(self):
        p, e, prev, target, current, repo = self.make()
        backend = Mock()
        backend.observe.return_value = HistoryResult(current.external_job_ref, HistoryState.NOT_FOUND, {})
        ResumeExecutionUseCase(repo, backend, Mock(), Mock()).resume(p.id, e.id)
        transport = Mock()
        submitter = SubmitBoundary(transport, repository=repo)
        resume = ResumeExecutionUseCase(repo, Mock(), Mock(), submitter)
        with self.assertRaisesRegex(ValueError, 'retry prompt reconstruction failed'):
            RetryExecutionUseCase(repo, resume).retry(p.id, e.id)
        transport.submit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
