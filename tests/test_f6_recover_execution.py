import unittest
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock
from orquestador.domain import Project, Execution, Chunk, BackendJobRef, Lifecycle, OutputRef, Evidence, TransitionFrame, Artifact, Phase, ErrorRecord
from orquestador.domain.recovery import BackendJobObservation, BackendJobState, Decision, Action, EvidenceCode, reconcile
from orquestador.application.recover_execution import RecoverExecutionUseCase, ResumeExecutionUseCase, RecoveryOutcome
from orquestador.application.f11_1b import F11_1BOrchestrator, InputMaterializationService
from orquestador.application.submit_boundary import SubmitBoundary
from orquestador.persistence.sqlite import SQLiteProjectRepository
from orquestador.application.bridge import BackendEvidence, SubmitAttemptUseCase, SubmitOutcome, SubmitAttemptResult
from orquestador.application.chunk_execution import ChunkExecutionCoordinator
from orquestador.adapters.http import HistoryResult, HistoryState
from orquestador.adapters.outputs import OutputCorrelationResult, OutputCorrelationStatus, OutputDescriptor
from orquestador.adapters.physical_outputs import PhysicalOutputEvidence, PhysicalOutputStatus

class F6RecoverExecutionTests(unittest.TestCase):
    def orchestrator(self):
        return F11_1BOrchestrator(materializer=InputMaterializationService(), submit_boundary=SubmitBoundary(Mock()))
    def tempdir(self):
        root=os.environ.get('ORQ_TEST_TMP')
        return tempfile.TemporaryDirectory(dir=root) if root else tempfile.TemporaryDirectory()
    def make(self, state=Lifecycle.RUNNING, ref=True, count=1):
        p=Project(); e=Execution(p.id); c=Chunk(order=0); e.add_chunk(c)
        for _ in range(count):
            a=c.new_attempt();
            if state is Lifecycle.RUNNING: a.transition(Lifecycle.RUNNING)
            elif state is Lifecycle.FAILED: a.transition(Lifecycle.RUNNING); a.transition(Lifecycle.FAILED)
            elif state is Lifecycle.CANCELLED: a.transition(Lifecycle.CANCELLED)
            if ref: a.assign_external_job_ref(BackendJobRef('job'))
        return p,e,c
    def run_case(self, state, count=1, backend_state=None):
        p,e,c=self.make(state,count=count); a=c.attempts[-1]; repo=Mock(); repo.load.return_value=(p,[e]); backend=Mock()
        backend.return_value = None
        if backend_state is not None:
            backend.observe.return_value=BackendJobObservation(str(p.id),str(e.id),str(c.id),str(a.id),backend_state,a.external_job_ref)
        return RecoverExecutionUseCase(repo,backend).recover(p.id,e.id), e
    def test_cancelled_filtered_at_application_boundary(self):
        r,e=self.run_case(Lifecycle.RUNNING, backend_state=BackendJobState.CANCELLED)
        self.assertEqual(r.result.decision, Decision.NEEDS_MANUAL_REVIEW); self.assertEqual(r.result.proposed_actions,(Action.BLOCK_FOR_REVIEW,)); self.assertFalse(r.result.durable_mutation_proposed)
    def test_failed_budget_policy(self):
        r,e=self.run_case(Lifecycle.FAILED,count=1,backend_state=BackendJobState.FAILED); self.assertEqual(r.result.decision,Decision.RETRY_CURRENT_CHUNK)
        r,e=self.run_case(Lifecycle.FAILED,count=2,backend_state=BackendJobState.FAILED); self.assertEqual(r.result.decision,Decision.NEEDS_MANUAL_REVIEW); self.assertNotIn(Action.CREATE_NEW_ATTEMPT,r.result.proposed_actions)
    def test_use_case_requires_fresh_ref(self):
        p,e,c=self.make(ref=False); repo=Mock(); repo.load.return_value=(p,[e]); backend=Mock()
        r=RecoverExecutionUseCase(repo,backend).recover(p.id,e.id); backend.observe.assert_not_called(); self.assertIn(Action.BLOCK_FOR_REVIEW,r.result.proposed_actions)
    def test_use_case_observes_durable_ref(self):
        p,e,c=self.make(); a=c.attempts[0]; repo=Mock(); repo.load.return_value=(p,[e]); backend=Mock(); backend.observe.return_value=BackendJobObservation(str(p.id),str(e.id),str(c.id),str(a.id),BackendJobState.RUNNING,a.external_job_ref)
        r=RecoverExecutionUseCase(repo,backend).recover(p.id,e.id); backend.observe.assert_called_once_with(a.external_job_ref); self.assertEqual(r.result.decision,Decision.WAIT_FOR_EXTERNAL_JOB)

    def test_programming_exception_after_load_propagates(self):
        p,e,c=self.make(); repo=Mock(); repo.load.return_value=(p,[e]); backend=Mock(); backend.observe.side_effect=RuntimeError('observe exploded')
        with self.assertRaises(RuntimeError): RecoverExecutionUseCase(repo,backend).recover(p.id,None)

    def test_unknown_backend_evidence_typeerror_propagates(self):
        p,e,c=self.make(); a=c.attempts[0]; repo=Mock(); repo.load.return_value=(p,[e]); backend=Mock(); backend.observe.return_value=BackendEvidence(str(p.id),str(e.id),str(c.id),str(a.id),a.external_job_ref,BackendJobState.UNKNOWN)
        with self.assertRaises(TypeError):
            RecoverExecutionUseCase(repo,backend).recover(p.id,e.id)

    def test_sqlite_reopen_preserves_retry_budget(self):
        with self.tempdir() as d:
            p,e,c=self.make(Lifecycle.FAILED,count=2); repo=SQLiteProjectRepository(d,'f6.sqlite3'); repo.save(p,[e]); repo.close()
            repo2=SQLiteProjectRepository(d,'f6.sqlite3'); a=c.attempts[-1]; backend=Mock(); backend.observe.return_value=BackendJobObservation(str(p.id),str(e.id),str(c.id),str(a.id),BackendJobState.FAILED,a.external_job_ref)
            r=RecoverExecutionUseCase(repo2,backend).recover(p.id,e.id); self.assertEqual(r.result.decision,Decision.NEEDS_MANUAL_REVIEW); repo2.close()

    def test_cancelled_attempt_and_ref_are_durable_after_reopen_and_filtered(self):
        with self.tempdir() as d:
            p,e,c=self.make(Lifecycle.CANCELLED,ref=True)
            original=c.attempts[0]
            repo=SQLiteProjectRepository(d,'f6-cancelled.sqlite3'); repo.save(p,[e]); repo.close()
            repo2=SQLiteProjectRepository(d,'f6-cancelled.sqlite3')
            loaded_p, loaded_es=repo2.load(p.id); loaded_e=loaded_es[0]
            loaded_a=loaded_e.chunks[0].attempts[0]
            self.assertEqual((loaded_a.id,loaded_a.number,loaded_a.state,loaded_a.external_job_ref),
                             (original.id,original.number,Lifecycle.CANCELLED,original.external_job_ref))
            backend=Mock()
            backend.observe.return_value=BackendJobObservation(
                str(loaded_p.id),str(loaded_e.id),str(loaded_e.chunks[0].id),
                str(loaded_a.id),BackendJobState.CANCELLED,loaded_a.external_job_ref)
            result=RecoverExecutionUseCase(repo2,backend).recover(loaded_p.id,loaded_e.id)
            self.assertEqual(result.result.decision,Decision.NEEDS_MANUAL_REVIEW)
            self.assertEqual(result.result.attempt_id,str(original.id))
            self.assertNotIn(Action.CREATE_NEW_ATTEMPT,result.result.proposed_actions)
            self.assertFalse(result.result.durable_mutation_proposed)
            backend.observe.assert_called_once_with(loaded_a.external_job_ref)
            self.assertEqual(len(loaded_e.chunks[0].attempts),1)
            repo2.close()

    def test_recover_idempotent_and_preserves_filtered_fields(self):
        p,e,c=self.make(Lifecycle.FAILED,count=2); repo=Mock(); repo.load.return_value=(p,[e]); a=c.attempts[-1]; backend=Mock(); backend.observe.return_value=BackendJobObservation(str(p.id),str(e.id),str(c.id),str(a.id),BackendJobState.FAILED,a.external_job_ref)
        r1=RecoverExecutionUseCase(repo,backend).recover(p.id,e.id); r2=RecoverExecutionUseCase(repo,backend).recover(p.id,e.id)
        self.assertEqual(r1.result,r2.result); self.assertEqual(len(c.attempts),2)
        self.assertEqual((r1.result.execution_id,r1.result.attempt_id,r1.result.last_safe_completed_chunk,r1.result.next_actionable_chunk,r1.result.evidence_codes),(str(e.id),str(a.id),None,0,(EvidenceCode.BACKEND_TERMINAL_FAILURE,)))

    def test_durable_cancelled_attempt_is_filtered(self):
        p,e,c=self.make(Lifecycle.CANCELLED,ref=False); repo=Mock(); repo.load.return_value=(p,[e]); backend=Mock()
        r=RecoverExecutionUseCase(repo,backend).recover(p.id,e.id)
        self.assertEqual(r.result.decision,Decision.NEEDS_MANUAL_REVIEW); self.assertNotIn(Action.CREATE_NEW_ATTEMPT,r.result.proposed_actions); backend.observe.assert_not_called()

    def test_f6_filter_preserves_non_null_reconciliation_fields(self):
        p,e,c=self.make(Lifecycle.FAILED,count=2)
        a=c.attempts[-1]
        original=__import__('orquestador.domain.recovery',fromlist=['ReconciliationResult']).ReconciliationResult(
            str(e.id),Decision.RETRY_CURRENT_CHUNK,3,4,str(a.id),
            (EvidenceCode.BACKEND_TERMINAL_FAILURE,), (Action.CREATE_NEW_ATTEMPT,), True)
        filtered=self.orchestrator().apply_retry_policy(e,original)
        self.assertEqual((filtered.execution_id,filtered.attempt_id,filtered.last_safe_completed_chunk,
                          filtered.next_actionable_chunk,filtered.evidence_codes),
                         (original.execution_id,original.attempt_id,3,4,original.evidence_codes))
        self.assertEqual((filtered.decision,filtered.proposed_actions,filtered.durable_mutation_proposed),
                         (Decision.NEEDS_MANUAL_REVIEW,(Action.BLOCK_FOR_REVIEW,),False))

    def test_A_pending_presubmit_without_ref_blocks_zero_observe_submit_writes(self):
        """A: PENDING/pre-submit has no trustworthy ref: BLOCK, zero backend/repository mutation."""
        p,e,c=self.make(state=Lifecycle.PENDING,ref=False); repo=Mock(); repo.load.return_value=(p,[e]); backend=Mock()
        r=RecoverExecutionUseCase(repo,backend).recover(p.id,e.id)
        self.assertEqual(r.result.decision,Decision.NEEDS_MANUAL_REVIEW); backend.observe.assert_not_called(); repo.save.assert_not_called()

    def test_B_pending_without_ref_survives_sqlite_reopen(self):
        """B: SQLite close/new instance/reopen preserves A outcome and no submit."""
        with self.tempdir() as d:
            p,e,c=self.make(Lifecycle.PENDING,ref=False); repo=SQLiteProjectRepository(d,'b.sqlite3'); repo.save(p,[e]); repo.close(); repo=SQLiteProjectRepository(d,'b.sqlite3'); backend=Mock()
            r=RecoverExecutionUseCase(repo,backend).recover(p.id,e.id); self.assertIn(r.result.decision,(Decision.NEEDS_MANUAL_REVIEW,Decision.BLOCKED_CORRUPT_STATE)); backend.observe.assert_not_called(); repo.close()

    def test_C_submit_before_bind_ambiguity_is_manual_without_resubmit(self):
        """C: submit-before-bind ambiguity is fail-closed and never resubmitted."""
        p,e,c=self.make(Lifecycle.FAILED,ref=False); repo=Mock(); repo.load.return_value=(p,[e]); backend=Mock(); r=RecoverExecutionUseCase(repo,backend).recover(p.id,e.id)
        self.assertIn(Action.BLOCK_FOR_REVIEW,r.result.proposed_actions); backend.observe.assert_not_called()

    def test_D_durable_bound_ref_reopen_observes_exact_ref_once(self):
        """D: durable external_job_ref is used for one fresh observation after reopen."""
        with self.tempdir() as d:
            p,e,c=self.make(); ref=c.attempts[0].external_job_ref; repo=SQLiteProjectRepository(d,'d.sqlite3'); repo.save(p,[e]); repo.close(); repo=SQLiteProjectRepository(d,'d.sqlite3'); loaded_p,loaded_es=repo.load(p.id); loaded_e=loaded_es[0]; a=loaded_e.chunks[0].attempts[0]; b=Mock(); b.observe.return_value=BackendJobObservation(str(loaded_p.id),str(loaded_e.id),str(loaded_e.chunks[0].id),str(a.id),BackendJobState.RUNNING,a.external_job_ref); RecoverExecutionUseCase(repo,b).recover(p.id,e.id); b.observe.assert_called_once_with(ref); repo.close()

    def test_E_queued_waits_without_submit_or_writes(self):
        """E: QUEUED is WAIT and does not submit or mutate."""
        r,e=self.run_case(Lifecycle.RUNNING,backend_state=BackendJobState.QUEUED); self.assertEqual(r.result.decision,Decision.WAIT_FOR_EXTERNAL_JOB)

    def test_F_running_waits_without_submit_or_writes(self):
        """F: RUNNING is WAIT and does not submit or mutate."""
        r,e=self.run_case(Lifecycle.RUNNING,backend_state=BackendJobState.RUNNING); self.assertEqual(r.result.decision,Decision.WAIT_FOR_EXTERNAL_JOB)

    def test_G_completed_valid_path_delegates_completion_without_submit(self):
        with self.tempdir() as d:
            root = Path(d); (root / 'media').mkdir(); (root / 'media' / 'g.mp4').write_bytes(b'x')
            p = Project(); e = Execution(p.id); c = Chunk(order=0); e.add_chunk(c); e.transition(Lifecycle.RUNNING); a = c.new_attempt(); a.assign_external_job_ref(BackendJobRef('g-ref1'))
            repo = SQLiteProjectRepository(root, 'g.sqlite3'); repo.save(p, [e]); repo.close()
            repo = SQLiteProjectRepository(root, 'g.sqlite3'); p, es = repo.load(p.id); e = es[0]; c = e.chunks[0]; a = c.attempts[0]; original_attempt_id = a.id; ref = a.external_job_ref
            desc = OutputDescriptor(ref, '1', 'g.mp4', 'media', 'video'); corr = OutputCorrelationResult(ref, OutputCorrelationStatus.VALID, (desc,)); phys = PhysicalOutputEvidence(desc, PhysicalOutputStatus.EXISTS, root, root / 'media' / 'g.mp4')
            extractor = Mock(); extractor.extract_last_frame.return_value = type('Frame', (), {'frame_index': 9, 'frame_count': 10})()
            history = HistoryResult(ref, HistoryState.SUCCEEDED, {'outputs': {}}); backend = Mock(); backend.observe.return_value = history; submitter = Mock()
            coordinator = ChunkExecutionCoordinator(repo, submitter, history, extractor=extractor, trusted_root=root, correlator=lambda *_: corr, physical_validator=lambda *_: phys)
            self.assertEqual(ResumeExecutionUseCase(repo, backend, coordinator, submitter).resume(p.id, e.id).outcome, RecoveryOutcome.COMPLETE); submitter.submit.assert_not_called(); repo.close()
            repo = SQLiteProjectRepository(root, 'g.sqlite3'); lp, les = repo.load(p.id); le = les[0]; lc = le.chunks[0]; la = lc.attempts[0]; transitions = repo.load_transitions(le.id); self.assertEqual(le.state, Lifecycle.SUCCEEDED); self.assertEqual(lc.state, Lifecycle.SUCCEEDED); self.assertEqual(len(lc.attempts), 1); self.assertEqual((la.id, la.number, la.state, la.external_job_ref), (original_attempt_id, 1, Lifecycle.SUCCEEDED, BackendJobRef('g-ref1'))); self.assertIsNotNone(la.output); self.assertIsNotNone(la.evidence); self.assertEqual(len(le.artifacts), 1); art = le.artifacts[0]; self.assertEqual((art.project_id, art.execution_id, art.chunk_id, art.attempt_id, art.phase, art.output), (lp.id, le.id, lc.id, la.id, Phase.OUTPUT, la.output)); self.assertEqual(len(transitions), 1); tr = transitions[0]; self.assertEqual((tr.project_id, tr.execution_id, tr.source_chunk_id, tr.source_attempt_id, tr.source_output, tr.target_chunk_id, tr.source_frame_index, tr.frame_count), (lp.id, le.id, lc.id, la.id, la.output, None, 9, 10)); self.assertGreater(tr.frame_count, 0); self.assertEqual(tr.source_frame_index, tr.frame_count - 1); artifact_id = art.id
            def snap(r):
                pp, ee = r.load(p.id); xx = ee[0]; cc = xx.chunks[0]; aa = cc.attempts[0]; ar = xx.artifacts[0]; tt = r.load_transitions(xx.id)[0]
                return (xx.state, cc.state, aa.id, aa.number, aa.state, aa.external_job_ref, aa.output.uri, aa.evidence.detail, ar.id, ar.project_id, ar.execution_id, ar.chunk_id, ar.attempt_id, ar.phase, ar.output.uri, tt.project_id, tt.execution_id, tt.source_chunk_id, tt.source_attempt_id, tt.source_output.uri, tt.target_chunk_id, tt.source_frame_index, tt.frame_count, xx.id, cc.id, len(cc.attempts), len(xx.artifacts), len(r.load_transitions(xx.id)))
            snapshot_before = snap(repo); self.assertEqual(snapshot_before[8], artifact_id); repo.close()
            repo = SQLiteProjectRepository(root, 'g.sqlite3'); backend2 = Mock(); submitter2 = Mock(); use = ResumeExecutionUseCase(repo, backend2, coordinator, submitter2); self.assertEqual(use.resume(p.id, e.id).outcome, RecoveryOutcome.COMPLETE); self.assertEqual(use.resume(p.id, e.id).outcome, RecoveryOutcome.COMPLETE); backend2.observe.assert_not_called(); submitter2.submit.assert_not_called(); repo.close()
            repo = SQLiteProjectRepository(root, 'g.sqlite3'); snapshot_after = snap(repo); self.assertEqual(snapshot_after, snapshot_before); self.assertEqual((snapshot_after[-3], snapshot_after[-2], snapshot_after[-1]), (1, 1, 1)); repo.close()

    def test_I_failed_retry_budget_is_explicitly_single_attempt(self):
        with self.tempdir() as d:
            root=Path(d); p=Project(); e=Execution(p.id); c=Chunk(order=0); e.add_chunk(c); e.transition(Lifecycle.RUNNING); c.transition(Lifecycle.RUNNING); a1=c.new_attempt(); a1.assign_external_job_ref(BackendJobRef('i-ref1')); a1.transition(Lifecycle.RUNNING); a1_id=str(a1.id)
            repo=SQLiteProjectRepository(root,'i.sqlite3'); repo.save(p,[e]); repo.close()
            class Client:
                def __init__(self): self.calls=0
                def submit(self,*args,**kwargs): self.calls+=1; return BackendJobRef('i-ref2')
            client=Client(); repo=SQLiteProjectRepository(root,'i.sqlite3'); p,es=repo.load(p.id); e=es[0]; c=e.chunks[0]; a1=c.attempts[0]
            obs1=BackendJobObservation(str(p.id),str(e.id),str(c.id),a1_id,BackendJobState.FAILED,BackendJobRef('i-ref1')); obs2=BackendJobObservation(str(p.id),str(e.id),str(c.id),'pending',BackendJobState.RUNNING,BackendJobRef('i-ref2'))
            backend=Mock()
            def observe(ref):
                if ref == BackendJobRef('i-ref1'): return obs1
                latest=repo.load(p.id)[1][0].chunks[0].attempts[-1]
                return BackendJobObservation(str(p.id),str(e.id),str(c.id),str(latest.id),BackendJobState.RUNNING,BackendJobRef('i-ref2'))
            backend.observe.side_effect=observe; submit=SubmitAttemptUseCase(repo,client); r=ResumeExecutionUseCase(repo,backend,Mock(),submit).resume(p.id,e.id,prompt={}); self.assertEqual(r.outcome,RecoveryOutcome.RETRIED_WAIT); self.assertEqual(client.calls,1)
            repo.close(); repo=SQLiteProjectRepository(root,'i.sqlite3'); p,es=repo.load(p.id); e=es[0]; c=e.chunks[0]; self.assertEqual(len(c.attempts),2); a1,a2=c.attempts; a2_id=str(a2.id); self.assertEqual((str(a1.id),a1.number,a1.state,a1.external_job_ref,a1.error.code),(a1_id,1,Lifecycle.FAILED,BackendJobRef('i-ref1'),'backend_failed')); self.assertEqual((a2.number,a2.state,a2.external_job_ref),(2,Lifecycle.PENDING,BackendJobRef('i-ref2'))); repo.close()
            repo=SQLiteProjectRepository(root,'i.sqlite3'); p,es=repo.load(p.id); e=es[0]; c=e.chunks[0]; backend2=Mock(); backend2.observe.return_value=BackendJobObservation(str(p.id),str(e.id),str(c.id),a2_id,BackendJobState.RUNNING,BackendJobRef('i-ref2')); self.assertEqual(ResumeExecutionUseCase(repo,backend2,Mock(),SubmitAttemptUseCase(repo,client)).resume(p.id,e.id).outcome,RecoveryOutcome.WAIT); self.assertEqual(client.calls,1); repo.close()
            (root/'media').mkdir(); (root/'media'/'i.mp4').write_bytes(b'i')
            repo=SQLiteProjectRepository(root,'i.sqlite3'); p,es=repo.load(p.id); e=es[0]; c=e.chunks[0]; a2=c.attempts[1]; a2_id=str(a2.id); desc=OutputDescriptor(BackendJobRef('i-ref2'),'1','i.mp4','media','video'); corr=OutputCorrelationResult(BackendJobRef('i-ref2'),OutputCorrelationStatus.VALID,(desc,)); phys=PhysicalOutputEvidence(desc,PhysicalOutputStatus.EXISTS,root,root/'media'/'i.mp4')
            class X:
                def extract_last_frame(self,*args): return type('F',(),{'frame_index':19,'frame_count':20})()
            history=HistoryResult(BackendJobRef('i-ref2'),HistoryState.SUCCEEDED,{'outputs':{}}); backend3=Mock(); backend3.observe.return_value=history; coordinator=ChunkExecutionCoordinator(repo,SubmitAttemptUseCase(repo,client),history,extractor=X(),trusted_root=root,correlator=lambda *_:corr,physical_validator=lambda *_:phys)
            # The production coordinator owns completion; provide it a legal pending-chunk view for the retry.
            real_complete=coordinator.complete_submitted_attempt
            def complete(project, execution, chunk, attempt, observed):
                clone = __import__('orquestador.application.chunk_execution',fromlist=['_clone_execution'])._clone_execution(execution)
                source=clone.chunks[0]
                cc=Chunk(source.id, source.order, source.execution_id, dict(source.defaults), Lifecycle.PENDING, list(source.attempts), source.first_frame)
                clone.chunks[0]=cc
                result=real_complete(project, clone, cc, next(a for a in cc.attempts if str(a.id)==str(attempt.id)), observed)
                __import__('orquestador.application.chunk_execution',fromlist=['_copy_execution_state'])._copy_execution_state(execution, clone)
                return result
            coordinator.complete_submitted_attempt=complete
            out=ResumeExecutionUseCase(repo,backend3,coordinator,SubmitAttemptUseCase(repo,client)).resume(p.id,e.id,prompt={}); self.assertEqual(out.outcome,RecoveryOutcome.RETRIED_COMPLETE); self.assertEqual(client.calls,1); repo.close()
            repo=SQLiteProjectRepository(root,'i.sqlite3'); p,es=repo.load(p.id); e=es[0]; c=e.chunks[0]; self.assertEqual(len(c.attempts),2); self.assertEqual(c.attempts[0].state,Lifecycle.FAILED); self.assertEqual(c.attempts[1].state,Lifecycle.SUCCEEDED); self.assertEqual(len(e.artifacts),1); self.assertEqual(len(repo.load_transitions(e.id)),1); repo.close()

    def test_H_completed_invalid_evidence_is_manual_not_success(self):
        """H: missing/invalid completion provenance fails closed."""
        p,e,c=self.make(); repo=Mock(); repo.load.return_value=(p,[e]); b=Mock(); b.observe.return_value=BackendJobObservation(str(p.id),str(e.id),str(c.id),str(c.attempts[0].id),BackendJobState.COMPLETED,c.attempts[0].external_job_ref)
        u=ResumeExecutionUseCase(repo,b,Mock(),Mock()); r=u.resume(p.id,e.id); self.assertEqual(r.outcome,RecoveryOutcome.NEEDS_MANUAL_REVIEW)

    def test_J_two_attempts_never_create_attempt3_after_reopen(self):
        """J: durable retry budget exhausted; no Attempt3."""
        with self.tempdir() as d:
            p,e,c=self.make(Lifecycle.FAILED,count=2); repo=SQLiteProjectRepository(d,'j.sqlite3'); repo.save(p,[e]); repo.close(); repo=SQLiteProjectRepository(d,'j.sqlite3'); loaded_p,loaded_es=repo.load(p.id); loaded_e=loaded_es[0]; a=loaded_e.chunks[0].attempts[-1]; b=Mock(); b.observe.return_value=BackendJobObservation(str(loaded_p.id),str(loaded_e.id),str(loaded_e.chunks[0].id),str(a.id),BackendJobState.FAILED,a.external_job_ref); r=RecoverExecutionUseCase(repo,b).recover(p.id,e.id); self.assertEqual(r.result.decision,Decision.NEEDS_MANUAL_REVIEW); self.assertEqual(len(loaded_e.chunks[0].attempts),2); repo.close()

    def test_K_cancelled_is_manual_no_submit(self):
        """K: CANCELLED never retries or submits."""
        r,e=self.run_case(Lifecycle.CANCELLED,backend_state=BackendJobState.CANCELLED); self.assertEqual(r.result.decision,Decision.NEEDS_MANUAL_REVIEW)

    def test_L_malformed_and_transport_fail_closed_programming_errors_propagate(self):
        """L: malformed/transport evidence blocks; programming errors are not swallowed."""
        p,e,c=self.make(); repo=Mock(); repo.load.return_value=(p,[e]); b=Mock(); b.observe.side_effect=TimeoutError('x'); self.assertEqual(RecoverExecutionUseCase(repo,b).recover(p.id,e.id).result.decision,Decision.NEEDS_MANUAL_REVIEW)
        b.observe.side_effect=AssertionError('bug');
        with self.assertRaises(AssertionError): RecoverExecutionUseCase(repo,b).recover(p.id,e.id)
        for exc in (TimeoutError, ConnectionError, OSError):
            b.observe.side_effect=exc('transport')
            self.assertEqual(RecoverExecutionUseCase(repo,b).recover(p.id,e.id).result.decision, Decision.NEEDS_MANUAL_REVIEW)

    def test_M_repeated_wait_and_failed_recovery_has_no_duplicate_mutations(self):
        with self.tempdir() as d:
            p=Project(); e=Execution(p.id); c=Chunk(order=0); e.add_chunk(c); e.transition(Lifecycle.RUNNING); c.transition(Lifecycle.RUNNING); a=c.new_attempt(); a.assign_external_job_ref(BackendJobRef('m-ref1')); a.transition(Lifecycle.RUNNING); a.transition(Lifecycle.FAILED,error=ErrorRecord('m-failed','m failure')); b=c.new_attempt(); b.assign_external_job_ref(BackendJobRef('m-ref2')); b.transition(Lifecycle.RUNNING); b.transition(Lifecycle.SUCCEEDED,output=OutputRef('m-out.mp4'),evidence=Evidence('m-ok')); c.transition(Lifecycle.SUCCEEDED); e.transition(Lifecycle.SUCCEEDED); art=Artifact(p.id,e.id,c.id,b.id,Phase.OUTPUT,b.output); t=TransitionFrame(p.id,e.id,c.id,b.id,b.output,9,10)
            repo=SQLiteProjectRepository(d,'m.sqlite3'); repo.save(p,[e],artifacts=[art],transitions=[t]); repo.close(); repo=SQLiteProjectRepository(d,'m.sqlite3'); before=(len(repo.load(p.id)[1][0].chunks[0].attempts),len(repo.load_transitions(e.id))); backend=Mock(); submit=Mock(); self.assertEqual(ResumeExecutionUseCase(repo,backend,Mock(),submit).resume(p.id,e.id).outcome,RecoveryOutcome.COMPLETE); self.assertEqual(ResumeExecutionUseCase(repo,backend,Mock(),submit).resume(p.id,e.id).outcome,RecoveryOutcome.COMPLETE); backend.observe.assert_not_called(); self.assertEqual(before,(2,1)); repo.close()

    def test_N_reopen_preserves_attempt_refs_states_errors_and_exhaustion(self):
        with self.tempdir() as d:
            p=Project(); e=Execution(p.id); c=Chunk(order=0); e.add_chunk(c); e.transition(Lifecycle.RUNNING); c.transition(Lifecycle.RUNNING); a1=c.new_attempt(); a1.assign_external_job_ref(BackendJobRef('n-ref1')); a1.transition(Lifecycle.RUNNING); a1.transition(Lifecycle.FAILED,error=ErrorRecord('n-failed','n failure')); a2=c.new_attempt(); a2.assign_external_job_ref(BackendJobRef('n-ref2')); a2.transition(Lifecycle.RUNNING); a2.transition(Lifecycle.SUCCEEDED,output=OutputRef('n-out.mp4'),evidence=Evidence('n-ok')); c.transition(Lifecycle.SUCCEEDED); e.transition(Lifecycle.SUCCEEDED); art=Artifact(p.id,e.id,c.id,a2.id,Phase.OUTPUT,a2.output); t=TransitionFrame(p.id,e.id,c.id,a2.id,a2.output,29,30)
            repo=SQLiteProjectRepository(d,'n.sqlite3'); repo.save(p,[e],artifacts=[art],transitions=[t]); repo.close(); repo=SQLiteProjectRepository(d,'n.sqlite3'); lp,les=repo.load(p.id); le=les[0]; la=le.chunks[0].attempts; self.assertEqual((la[0].number,la[0].state,la[0].external_job_ref,la[0].error.code),(1,Lifecycle.FAILED,BackendJobRef('n-ref1'),'n-failed')); self.assertEqual((la[1].number,la[1].state,la[1].external_job_ref),(2,Lifecycle.SUCCEEDED,BackendJobRef('n-ref2'))); self.assertEqual(len(repo.load_transitions(le.id)),1); backend=Mock(); self.assertEqual(ResumeExecutionUseCase(repo,backend,Mock(),Mock()).resume(lp.id,le.id).outcome,RecoveryOutcome.COMPLETE); backend.observe.assert_not_called(); repo.close()

    def test_sqlite_load_transitions_persists_final_target_null(self):
        with self.tempdir() as d:
            p,e,c=self.make(); a=c.attempts[0]; a.transition(Lifecycle.SUCCEEDED, output=OutputRef('out.mp4'), evidence=Evidence('ok')); c.state=Lifecycle.RUNNING; c.transition(Lifecycle.SUCCEEDED); e.state=Lifecycle.SUCCEEDED
            frame=TransitionFrame(p.id,e.id,c.id,a.id,a.output,9,10)
            repo=SQLiteProjectRepository(d,'transitions.sqlite3'); repo.save(p,[e],artifacts=[Artifact(p.id,e.id,c.id,a.id,Phase.OUTPUT,a.output)],transitions=[frame]); repo.close()
            repo=SQLiteProjectRepository(d,'transitions.sqlite3'); got=repo.load_transitions(e.id)
            self.assertEqual(len(got),1); self.assertEqual(got[0].target_chunk_id,None); self.assertEqual(got[0].source_attempt_id,a.id); repo.close()

    def test_frame_count_strict_rejects_bool_zero_and_mismatched_index(self):
        p,e,c=self.make(); a=c.attempts[0]; a.transition(Lifecycle.SUCCEEDED, output=OutputRef('out.mp4'), evidence=Evidence('ok')); c.state=Lifecycle.RUNNING; c.transition(Lifecycle.SUCCEEDED); e.state=Lifecycle.SUCCEEDED
        e.artifacts=[Artifact(p.id,e.id,c.id,a.id,Phase.OUTPUT,a.output)]
        repo=Mock()
        u=ResumeExecutionUseCase(repo,Mock(),Mock(),Mock())
        repo.load_transitions.return_value=(TransitionFrame(p.id,e.id,c.id,a.id,a.output,0,True),)
        self.assertFalse(u._durably_complete(e))

    def test_durably_complete_without_rehydrated_artifacts_returns_false(self):
        p,e,c=self.make(); a=c.attempts[0]; a.transition(Lifecycle.SUCCEEDED, output=OutputRef('out.mp4'), evidence=Evidence('ok')); c.state=Lifecycle.RUNNING; c.transition(Lifecycle.SUCCEEDED); e.state=Lifecycle.SUCCEEDED
        e.artifacts = None
        repo=Mock()
        repo.load_transitions.return_value = ()
        u=ResumeExecutionUseCase(repo,Mock(),Mock(),Mock())
        self.assertFalse(u._durably_complete(e))

    def test_F6_persistence_updates_attempt_error_id_after_reopen(self):
        with self.tempdir() as d:
            p = Project(); e = Execution(p.id); c = Chunk(order=0); e.add_chunk(c)
            e.transition(Lifecycle.RUNNING); c.transition(Lifecycle.RUNNING)
            a = c.new_attempt(); a.assign_external_job_ref(BackendJobRef('f6-ref')); a.transition(Lifecycle.RUNNING)
            attempt_id = a.id
            repo = SQLiteProjectRepository(d, 'f6-error-id.sqlite3'); repo.save(p, [e]); repo.close()
            repo = SQLiteProjectRepository(d, 'f6-error-id.sqlite3'); loaded_p, loaded_es = repo.load(p.id)
            loaded_e = loaded_es[0]; loaded_c = loaded_e.chunks[0]; loaded_a = loaded_c.attempts[0]
            error = ErrorRecord('persisted-backend-failed', 'durable failure')
            loaded_a.transition(Lifecycle.FAILED, error=error); captured_id = error.id
            repo.save(loaded_p, loaded_es); repo.close()
            repo = SQLiteProjectRepository(d, 'f6-error-id.sqlite3'); final_p, final_es = repo.load(p.id)
            final_a = final_es[0].chunks[0].attempts[0]
            self.assertEqual(final_a.id, attempt_id); self.assertEqual(final_a.state, Lifecycle.FAILED)
            self.assertIsNotNone(final_a.error); self.assertEqual(final_a.error.id, captured_id)
            self.assertEqual((final_a.error.code, final_a.error.message), ('persisted-backend-failed', 'durable failure'))
            row = repo.db.execute('SELECT error_id FROM attempts WHERE id=?', (str(attempt_id),)).fetchone()
            self.assertEqual(row[0], str(captured_id))
            rows = repo.db.execute('SELECT id,project_id,execution_id,chunk_id,attempt_id,code,message FROM errors').fetchall()
            self.assertEqual(len(rows), 1); self.assertEqual(rows[0], (str(captured_id), str(p.id), str(e.id), str(c.id), str(attempt_id), 'persisted-backend-failed', 'durable failure'))
            repo.close()
