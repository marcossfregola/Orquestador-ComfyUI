import tempfile
from dataclasses import dataclass
import unittest
from pathlib import Path
from unittest.mock import Mock
from orquestador.domain.core import Project, Execution, Chunk, BackendJobRef, DomainError, Lifecycle, OutputRef, Artifact, Phase
from orquestador.adapters.http import HistoryResult, HistoryState
from orquestador.adapters.outputs import OutputCorrelationResult, OutputCorrelationStatus, OutputDescriptor
from orquestador.adapters.physical_outputs import PhysicalOutputEvidence, PhysicalOutputStatus
from orquestador.application.bridge import SubmitAttemptUseCase
from orquestador.application.chunk_execution import ChunkExecutionCoordinator, ChunkExecutionResult
from orquestador.application.robust_chunk_execution import RobustChunkExecutionCoordinator, RobustOutcome
from orquestador.persistence.sqlite import SQLiteProjectRepository
from orquestador.application.f11_1b import F11_1BOrchestrator, InputMaterializationService
from orquestador.application.submit_boundary import SubmitBoundary

class Client:
    def __init__(self): self.n=0
    def submit(self,prompt,client_id=None): self.n+=1; return BackendJobRef(f'job-{self.n}')

class FaultRepo:
    def __init__(self,real,num): self.real,self.num,self.hit=real,num,False
    def save(self,project,executions,*a,**k):
        if not self.hit and any(x.number==self.num and x.state is Lifecycle.FAILED for e in executions for c in e.chunks for x in c.attempts): self.hit=True; raise RuntimeError('injected save failure')
        return self.real.save(project,executions,*a,**k)
    def load(self,*a,**k): return self.real.load(*a,**k)
    def close(self): return self.real.close()

class RobustContractTests(unittest.TestCase):
    def setUp(self):
        Path('C:\\Temp\\orq-f5-final-tests').mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir='C:\\Temp\\orq-f5-final-tests'); self.root=Path(self.tmp.name); (self.root/'out.mp4').write_bytes(b'x')
        self.repo=SQLiteProjectRepository(self.root); self.project=Project(); self.execution=Execution(self.project.id); self.chunk=Chunk(order=0); self.execution.add_chunk(self.chunk); self.repo.save(self.project,[self.execution])
    def tearDown(self):
        try:self.repo.close()
        except Exception:pass
        self.tmp.cleanup()
    def make(self,states,repo=None):
        repo=repo or self.repo; client=Client(); submit=SubmitAttemptUseCase(repo,client); q=list(states)
        def monitor(ref,**kw): return HistoryResult(ref,q.pop(0),error='failed' if q==[] else None)
        def corr(h,ref): return OutputCorrelationResult(ref,OutputCorrelationStatus.VALID,(OutputDescriptor(ref,'node','out.mp4','','video'),))
        def physical(d,root): return PhysicalOutputEvidence(d,PhysicalOutputStatus.EXISTS,Path(root),self.root/'out.mp4')
        extractor=Mock(); extractor.extract_last_frame.return_value=type('F',(),{'frame_index':0,'frame_count':1})()
        core=ChunkExecutionCoordinator(repo,submit,monitor,extractor=extractor,trusted_root=self.root,correlator=corr,physical_validator=physical)
        return RobustChunkExecutionCoordinator(core,sleeper=lambda _:None,poll_interval=.01),client
    def reopen(self): self.repo.close(); self.repo=SQLiteProjectRepository(self.root); return self.repo.load(self.project.id)[1][0]
    def policy(self, robust):
        return F11_1BOrchestrator(materializer=InputMaterializationService(), submit_boundary=SubmitBoundary(Mock()), robust=robust)
    def test_first_attempt_success_is_durable_sqlite(self):
        u,c=self.make([HistoryState.SUCCEEDED]); self.assertEqual(u.execute(self.project,self.execution,self.chunk.id,{}).outcome,RobustOutcome.COMPLETED); self.assertEqual(c.n,1); p,e=self.repo.load(self.project.id); x=e[0].chunks[0]; a=x.attempts[0]; self.assertEqual((x.state,a.state,a.external_job_ref.value), (Lifecycle.SUCCEEDED,Lifecycle.SUCCEEDED,'job-1')); arts=[z for z in p and e[0].artifacts if z.attempt_id==a.id and z.phase is Phase.OUTPUT]; self.assertEqual(len(arts),1); self.assertEqual(arts[0].output,a.output); row=self.repo.db.execute('SELECT source_attempt_id,frame_index,frame_count FROM transitions').fetchone(); self.assertEqual(row,(str(a.id),0,1)); self.assertEqual(row[1],row[2]-1)
    def test_invalid_output_root_after_composition_blocks_robust_submit(self):
        u,c=self.make([HistoryState.SUCCEEDED]); u.coordinator.comfyui_output_root=self.root/'missing-output-root'; r=u.execute(self.project,self.execution,self.chunk.id,{})
        self.assertEqual(r.outcome,RobustOutcome.BLOCKED); self.assertEqual(c.n,0); self.assertEqual(len(self.chunk.attempts),0)
    def test_failed_retry_success_is_durable_sqlite(self):
        u,c=self.make([HistoryState.FAILED,HistoryState.SUCCEEDED]); policy = self.policy(u); self.assertEqual(policy.execute_chunk_with_policy(self.project,self.execution,self.chunk.id,{}).outcome,RobustOutcome.COMPLETED); self.assertEqual(c.n,2); p,e=self.repo.load(self.project.id); x=e[0].chunks[0]; self.assertEqual([a.number for a in x.attempts],[1,2]); self.assertEqual(x.attempts[0].state,Lifecycle.FAILED); self.assertEqual(x.attempts[1].state,Lifecycle.SUCCEEDED); self.assertTrue(any(z.attempt_id==x.attempts[1].id and z.phase is Phase.OUTPUT for z in e[0].artifacts)); row=self.repo.db.execute('SELECT source_attempt_id,frame_index,frame_count FROM transitions').fetchone(); self.assertEqual(row[0],str(x.attempts[1].id)); self.assertEqual(row[1],row[2]-1)
    def test_failed_retry_failed_is_durable_sqlite(self):
        u,c=self.make([HistoryState.FAILED,HistoryState.FAILED]); policy = self.policy(u); self.assertEqual(policy.execute_chunk_with_policy(self.project,self.execution,self.chunk.id,{}).outcome,RobustOutcome.FAILED); self.assertEqual(c.n,2); x=self.reopen().chunks[0]; self.assertEqual(len(x.attempts),2); self.assertTrue(all(a.state is Lifecycle.FAILED for a in x.attempts))
    def test_invalid_timeout_raises_before_attempt_and_reopen_is_durable(self):
        self.project.defaults={'orchestration_timeout_seconds':0}; u,c=self.make([HistoryState.FAILED]); self.assertRaises(DomainError,u.execute,self.project,self.execution,self.chunk.id,{}); self.assertEqual(c.n,0); self.assertEqual(len(self.reopen().chunks[0].attempts),0)
    def test_first_failed_save_failure_blocks_retry_and_reopen_shows_no_retry(self):
        self.repo.close(); self.repo=FaultRepo(SQLiteProjectRepository(self.root),1); u,c=self.make([HistoryState.FAILED,HistoryState.SUCCEEDED],self.repo); policy = self.policy(u); self.assertEqual(policy.execute_chunk_with_policy(self.project,self.execution,self.chunk.id,{}).outcome,RobustOutcome.BLOCKED); self.assertEqual(c.n,1); x=self.reopen().chunks[0]; self.assertEqual(len(x.attempts),1); self.assertEqual(x.attempts[0].state,Lifecycle.PENDING); self.assertIsNotNone(x.attempts[0].external_job_ref)
    def test_second_failed_save_failure_is_blocked_and_reopen_is_truthful(self):
        self.repo.close(); self.repo=FaultRepo(SQLiteProjectRepository(self.root),2); u,c=self.make([HistoryState.FAILED,HistoryState.FAILED],self.repo); policy = self.policy(u); self.assertEqual(policy.execute_chunk_with_policy(self.project,self.execution,self.chunk.id,{}).outcome,RobustOutcome.BLOCKED); self.assertEqual(c.n,2); x=self.reopen().chunks[0]; self.assertEqual(len(x.attempts),2); self.assertEqual(x.attempts[0].state,Lifecycle.FAILED); self.assertEqual(x.attempts[1].state,Lifecycle.PENDING)

    def _bounded(self, state, *, clock=None, sleeper=None, submitter=None, complete=None):
        self.execution.defaults={'orchestration_timeout_seconds':1}
        u,c=self.make([state],self.repo); core=u.coordinator
        if submitter is not None: core.submitter=submitter
        if complete is not None: core.complete_submitted_attempt=complete
        u.clock=clock or (lambda: 0.0); u.sleeper=sleeper or (lambda _: None); u.poll_interval=.01
        return u,c

    def test_running_reaches_deadline_without_retry(self):
        t=[0.0]; u,c=self._bounded(HistoryState.RUNNING,clock=lambda:t[0],sleeper=lambda _:t.__setitem__(0,t[0]+.01)); r=u.execute(self.project,self.execution,self.chunk.id,{}); self.assertEqual(r.outcome,RobustOutcome.NEEDS_MANUAL_REVIEW); self.assertEqual(c.n,1); self.assertEqual(len(self.chunk.attempts),1)

    def test_nonterminal_or_unknown_states_never_retry(self):
        for state in (HistoryState.QUEUED,HistoryState.NOT_FOUND,HistoryState.UNKNOWN):
            with self.subTest(state=state):
                self.tearDown(); self.setUp(); t=[0.0]; u,c=self._bounded(state,clock=lambda:t[0],sleeper=lambda _:t.__setitem__(0,t[0]+.01)); r=u.execute(self.project,self.execution,self.chunk.id,{}); self.assertEqual(r.outcome,RobustOutcome.NEEDS_MANUAL_REVIEW); self.assertEqual(c.n,1); self.assertEqual(len(self.chunk.attempts),1)

    def test_monitor_exception_never_retries(self):
        self.execution.defaults={'orchestration_timeout_seconds':1}; u,c=self.make([HistoryState.RUNNING]); u.coordinator.monitor=lambda **kw: (_ for _ in ()).throw(RuntimeError('deterministic')); r=u.execute(self.project,self.execution,self.chunk.id,{}); self.assertEqual(r.outcome,RobustOutcome.NEEDS_MANUAL_REVIEW); self.assertEqual(c.n,1); self.assertEqual(len(self.chunk.attempts),1)

    def test_submit_non_success_outcomes_never_retry(self):
        from orquestador.application.bridge import SubmitAttemptResult, SubmitOutcome
        for outcome in (SubmitOutcome.INVALID_REF,SubmitOutcome.AMBIGUOUS,SubmitOutcome.BIND_FAILED):
            with self.subTest(outcome=outcome):
                self.tearDown(); self.setUp(); self.execution.defaults={'orchestration_timeout_seconds':1}; calls=[]
                class S:
                    def submit(_, *a, **k): calls.append(1); return SubmitAttemptResult(outcome,'x')
                u,c=self.make([HistoryState.RUNNING]); u.coordinator.submitter=S(); r=u.execute(self.project,self.execution,self.chunk.id,{}); self.assertNotEqual(r.outcome,RobustOutcome.COMPLETED); self.assertEqual(len(calls),1); self.assertEqual(len(self.chunk.attempts),0)

    def test_completion_failure_after_backend_success_never_retries(self):
        self.execution.defaults={'orchestration_timeout_seconds':1}; u,c=self.make([HistoryState.SUCCEEDED]); u.coordinator.complete_submitted_attempt=lambda *a,**k: ChunkExecutionResult(False,'invalid physical evidence',str(a[3].id)); r=u.execute(self.project,self.execution,self.chunk.id,{}); self.assertNotEqual(r.outcome,RobustOutcome.COMPLETED); self.assertEqual(c.n,1)

    def test_frozen_clock_terminates_fail_closed(self):
        self.execution.defaults={'orchestration_timeout_seconds':1}; u,c=self._bounded(HistoryState.RUNNING,clock=lambda:0.0,sleeper=lambda _:None); r=u.execute(self.project,self.execution,self.chunk.id,{}); self.assertEqual(r.outcome,RobustOutcome.NEEDS_MANUAL_REVIEW); self.assertEqual(c.n,1)

    def test_nonpositive_poll_interval_is_rejected(self):
        u,c=self.make([HistoryState.RUNNING]);
        with self.assertRaises(ValueError): RobustChunkExecutionCoordinator(u.coordinator,poll_interval=0)
        with self.assertRaises(ValueError): RobustChunkExecutionCoordinator(u.coordinator,poll_interval=-1)
