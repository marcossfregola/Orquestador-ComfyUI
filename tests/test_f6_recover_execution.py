import unittest
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock
from orquestador.domain import Project, Execution, Chunk, BackendJobRef, Lifecycle
from orquestador.domain.recovery import BackendJobObservation, BackendJobState, Decision, Action, EvidenceCode, reconcile
from orquestador.application.recover_execution import RecoverExecutionUseCase, _apply_f6_retry_policy
from orquestador.persistence.sqlite import SQLiteProjectRepository
from orquestador.application.bridge import BackendEvidence

class F6RecoverExecutionTests(unittest.TestCase):
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

    def test_exception_after_load_preserves_durable_execution_id(self):
        p,e,c=self.make(); repo=Mock(); repo.load.return_value=(p,[e]); backend=Mock(); backend.observe.side_effect=RuntimeError('observe exploded')
        r=RecoverExecutionUseCase(repo,backend).recover(p.id,None)
        self.assertEqual(r.result.decision, Decision.NEEDS_MANUAL_REVIEW); self.assertEqual(r.result.execution_id,str(e.id)); self.assertIn('observe exploded',r.cause); self.assertEqual(len(c.attempts),1)

    def test_unknown_backend_fails_closed_without_retry(self):
        p,e,c=self.make(); a=c.attempts[0]; repo=Mock(); repo.load.return_value=(p,[e]); backend=Mock(); backend.observe.return_value=BackendEvidence(str(p.id),str(e.id),str(c.id),str(a.id),a.external_job_ref,BackendJobState.UNKNOWN)
        r=RecoverExecutionUseCase(repo,backend).recover(p.id,e.id)
        self.assertEqual(r.result.decision,Decision.NEEDS_MANUAL_REVIEW); self.assertNotIn(Action.CREATE_NEW_ATTEMPT,r.result.proposed_actions)

    def test_sqlite_reopen_preserves_retry_budget(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('ORQ_TEST_TMP', tempfile.gettempdir())) as d:
            p,e,c=self.make(Lifecycle.FAILED,count=2); repo=SQLiteProjectRepository(d,'f6.sqlite3'); repo.save(p,[e]); repo.close()
            repo2=SQLiteProjectRepository(d,'f6.sqlite3'); a=c.attempts[-1]; backend=Mock(); backend.observe.return_value=BackendJobObservation(str(p.id),str(e.id),str(c.id),str(a.id),BackendJobState.FAILED,a.external_job_ref)
            r=RecoverExecutionUseCase(repo2,backend).recover(p.id,e.id); self.assertEqual(r.result.decision,Decision.NEEDS_MANUAL_REVIEW); repo2.close()

    def test_cancelled_attempt_and_ref_are_durable_after_reopen_and_filtered(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('ORQ_TEST_TMP', tempfile.gettempdir())) as d:
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
        filtered=_apply_f6_retry_policy(e,original)
        self.assertEqual((filtered.execution_id,filtered.attempt_id,filtered.last_safe_completed_chunk,
                          filtered.next_actionable_chunk,filtered.evidence_codes),
                         (original.execution_id,original.attempt_id,3,4,original.evidence_codes))
        self.assertEqual((filtered.decision,filtered.proposed_actions,filtered.durable_mutation_proposed),
                         (Decision.NEEDS_MANUAL_REVIEW,(Action.BLOCK_FOR_REVIEW,),False))
