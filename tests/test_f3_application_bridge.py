import os, unittest
from pathlib import Path
from dataclasses import FrozenInstanceError
from orquestador.domain import *
from orquestador.domain.recovery import *
from orquestador.persistence.sqlite import SQLiteProjectRepository
from orquestador.adapters.http import *
from orquestador.adapters.events import *
from orquestador.adapters.outputs import *
from orquestador.adapters.cancellation import *
from orquestador.application.bridge import *

class Repo:
 def __init__(self,fail=False): self.fail=fail; self.saved=[]
 def save(self,p,es):
  if self.fail: raise RuntimeError('save failed')
  self.saved.append(es)

class F3ApplicationBridgeTests(unittest.TestCase):
 def setUp(self):
  self.p=Project(ProjectId('p')); self.e=Execution(self.p.id,ExecutionId('e')); self.c=Chunk(ChunkId('c')); self.e.add_chunk(self.c); self.a=self.c.new_attempt(); self.a.transition(Lifecycle.RUNNING); self.ref=BackendJobRef('job-1'); self.a.assign_external_job_ref(self.ref); self.b=ComfyUIJobBridge(Repo())
 def ev(self,s): return map_backend_evidence(execution=self.e,project_id='p',execution_id='e',chunk_id='c',attempt_id=str(self.a.id),job_ref=self.ref,source=s)
 def test_01_bind(self): self.b.bind(self.p,self.e,'c',str(self.a.id),self.ref); self.assertEqual(self.a.external_job_ref,self.ref)
 def test_02_project_mismatch(self):
  with self.assertRaises(ValueError): map_backend_evidence(execution=self.e,project_id='x',execution_id='e',chunk_id='c',attempt_id=str(self.a.id),job_ref=self.ref,source=QueueSnapshot())
 def test_03_execution_mismatch(self):
  with self.assertRaises(ValueError): map_backend_evidence(execution=self.e,project_id='p',execution_id='x',chunk_id='c',attempt_id=str(self.a.id),job_ref=self.ref,source=QueueSnapshot())
 def test_04_chunk_mismatch(self):
  with self.assertRaises(ValueError): map_backend_evidence(execution=self.e,project_id='p',execution_id='e',chunk_id='x',attempt_id=str(self.a.id),job_ref=self.ref,source=QueueSnapshot())
 def test_05_attempt_mismatch(self):
  with self.assertRaises(ValueError): map_backend_evidence(execution=self.e,project_id='p',execution_id='e',chunk_id='c',attempt_id='x',job_ref=self.ref,source=QueueSnapshot())
 def test_06_unbound(self): self.a.external_job_ref=None; self.assertRaises(ValueError, self.ev, QueueSnapshot())
 def test_07_queue_mapping(self):
  self.assertEqual(self.ev(QueueSnapshot(pending=(self.ref,))).state,BackendJobState.QUEUED); self.assertEqual(self.ev(QueueSnapshot(running=(self.ref,))).state,BackendJobState.RUNNING); self.assertEqual(self.ev(QueueSnapshot(running=(self.ref,),pending=(self.ref,))).state,BackendJobState.UNKNOWN)
 def test_08_queue_contradiction(self): self.assertEqual(self.ev(QueueSnapshot(pending=(self.ref,),state=QueueState.RUNNING)).state,BackendJobState.UNKNOWN)
 def test_09_history_mapping(self):
  for hs,bs in [(HistoryState.QUEUED,BackendJobState.QUEUED),(HistoryState.RUNNING,BackendJobState.RUNNING),(HistoryState.SUCCEEDED,BackendJobState.COMPLETED),(HistoryState.FAILED,BackendJobState.FAILED),(HistoryState.NOT_FOUND,BackendJobState.UNKNOWN),(HistoryState.UNKNOWN,BackendJobState.UNKNOWN)]: self.assertEqual(self.ev(HistoryResult(self.ref,hs)).state,bs)
 def test_10_observation_mapping(self):
  for k,s in [(ObservationKind.QUEUED,BackendJobState.QUEUED),(ObservationKind.RUNNING,BackendJobState.RUNNING),(ObservationKind.PROGRESS,BackendJobState.UNKNOWN),(ObservationKind.COMPLETED,BackendJobState.COMPLETED),(ObservationKind.FAILED,BackendJobState.FAILED),(ObservationKind.CANCELLED,BackendJobState.CANCELLED),(ObservationKind.UNKNOWN,BackendJobState.UNKNOWN)]: self.assertEqual(self.ev(ObservationEvent(self.ref,k)).state,s)
 def test_11_progress_detail(self): self.assertIn('nondurable',self.ev(ObservationEvent(self.ref,ObservationKind.PROGRESS)).detail)
 def test_12_output_valid(self): self.assertEqual(self.ev(OutputCorrelationResult(self.ref,OutputCorrelationStatus.VALID,(OutputDescriptor(self.ref,'1','a','','image'),))).logical_outputs[0].filename,'a')
 def test_13_output_conservative(self):
  for s in OutputCorrelationStatus: self.assertEqual(self.ev(OutputCorrelationResult(self.ref,s)).logical_outputs,())
 def test_14_output_ref_mismatch(self): self.assertRaises(ValueError,self.ev,OutputCorrelationResult(BackendJobRef('x'),OutputCorrelationStatus.VALID))
 def test_15_cancel_statuses(self):
  for s in CancellationState: self.assertEqual(map_cancellation_evidence(execution=self.e,project_id='p',execution_id='e',chunk_id='c',attempt_id=str(self.a.id),result=CancellationResult(self.ref,s,CancellationAction.NONE)).state,s)
 def test_16_cancel_issue_phase(self):
  for k in CancellationIssueKind:
   for p in CancellationPhase: self.assertEqual(map_cancellation_evidence(execution=self.e,project_id='p',execution_id='e',chunk_id='c',attempt_id=str(self.a.id),result=CancellationResult(self.ref,CancellationState.UNKNOWN,CancellationAction.NONE,'x',None,k,p)).phase,p)
 def test_17_cancel_side_effect_free(self): self.assertEqual(self.a.state,Lifecycle.RUNNING)
 def test_18_reconcile_pure(self): self.b.reconcile(self.e,backend=self.ev(QueueSnapshot())); self.assertEqual(len(self.c.attempts),1)
 def test_19_wait_no_save(self):
  r=ReconciliationResult('e',Decision.WAIT_FOR_EXTERNAL_JOB,0,0,str(self.a.id),proposed_actions=(Action.WAIT,)); repo=Repo(); ComfyUIJobBridge(repo).apply(self.p,self.e,r); self.assertFalse(repo.saved)
 def test_20_create_append(self):
  self.a.transition(Lifecycle.FAILED); r=ReconciliationResult('e',Decision.RETRY_CURRENT_CHUNK,0,0,str(self.a.id),proposed_actions=(Action.CREATE_NEW_ATTEMPT,)); ComfyUIJobBridge(Repo()).apply(self.p,self.e,r); self.assertEqual(len(self.c.attempts),2)
 def test_21_completion_refuse(self):
  r=ReconciliationResult('e',Decision.RECONCILE_EXTERNAL_COMPLETION,0,0,str(self.a.id),proposed_actions=(Action.MARK_EXTERNAL_COMPLETION_FROM_VERIFIED_EVIDENCE,)); self.assertRaises(ValueError,self.b.apply,self.p,self.e,r)
 def test_22_regenerate_refuse(self):
  r=ReconciliationResult('e',Decision.NEEDS_MANUAL_REVIEW,0,0,str(self.a.id),proposed_actions=(Action.REGENERATE_TRANSITION_FRAME,)); self.assertRaises(ValueError,self.b.apply,self.p,self.e,r)
 def test_23_unknown_action(self): self.assertRaises(ValueError,self.b.apply,self.p,self.e,ReconciliationResult('e',Decision.WAIT_FOR_EXTERNAL_JOB,0,0,None,proposed_actions=('x',)))
 def test_24_bind_rollback(self):
  e=Execution(self.p.id,ExecutionId('z')); c=Chunk(ChunkId('z')); e.add_chunk(c); a=c.new_attempt(); self.assertRaises(RuntimeError,ComfyUIJobBridge(Repo(True)).bind,self.p,e,'z',str(a.id),self.ref); self.assertIsNone(a.external_job_ref)
 def test_25_apply_rollback(self):
  self.a.transition(Lifecycle.FAILED); r=ReconciliationResult('e',Decision.RETRY_CURRENT_CHUNK,0,0,str(self.a.id),proposed_actions=(Action.CREATE_NEW_ATTEMPT,)); self.assertRaises(RuntimeError,ComfyUIJobBridge(Repo(True)).apply,self.p,self.e,r); self.assertEqual(len(self.c.attempts),1)
 def test_26_sqlite_reload(self):
  root=Path(os.environ['ORQ_TEST_TMP']); repo=SQLiteProjectRepository(root,'a.sqlite3'); repo.save(self.p,[self.e]); _,es=SQLiteProjectRepository(root,'a.sqlite3').load('p'); self.assertEqual(es[0].chunks[0].attempts[0].external_job_ref,self.ref); repo.close()
 def test_27_sqlite_ref_conflict(self):
  root=Path(os.environ['ORQ_TEST_TMP']); repo=SQLiteProjectRepository(root,'b.sqlite3'); repo.save(self.p,[self.e]); self.a.external_job_ref=BackendJobRef('other'); self.assertRaises(Exception,repo.save,self.p,[self.e]); repo.close()
 def test_28_frozen(self): self.assertRaises(FrozenInstanceError, setattr, self.ev(QueueSnapshot()),'state',BackendJobState.RUNNING)
 def test_29_taxonomy(self): self.assertEqual(self.ev(ObservationEvent(self.ref,ObservationKind.UNKNOWN,issue_kind=ObservationIssueKind.PROTOCOL)).issue_kind,'protocol')
 def test_30_ref_identity(self): self.assertIs(self.ev(OutputCorrelationResult(self.ref,OutputCorrelationStatus.VALID)).job_ref,self.ref)
 def test_31_history_error_detail(self): self.assertEqual(self.ev(HistoryResult(self.ref,HistoryState.FAILED,error='bad')).detail,'bad')
 def test_32_unsupported_source(self): self.assertRaises(TypeError,self.ev,object())
 def test_33_no_domain_cancelled(self): self.assertNotEqual(self.e.state,Lifecycle.CANCELLED)
 def test_34_output_no_artifact(self): self.assertEqual(self.e.artifacts,[])
 def test_35_queue_empty_unknown(self): self.assertEqual(self.ev(QueueSnapshot(state=QueueState.EMPTY)).state,BackendJobState.UNKNOWN)
 def test_36_history_not_found_unknown(self): self.assertEqual(self.ev(HistoryResult(self.ref,HistoryState.NOT_FOUND)).state,BackendJobState.UNKNOWN)
 def test_37_observation_cancel_backend_only(self): self.assertEqual(self.ev(ObservationEvent(self.ref,ObservationKind.CANCELLED)).state,BackendJobState.CANCELLED); self.assertNotEqual(self.e.state,Lifecycle.CANCELLED)
 def test_38_dto_detail(self): self.assertIsInstance(self.ev(QueueSnapshot()).detail,str)
 def test_39_bind_rejects_foreign_project_before_save_and_mutation(self):
  repo=Repo(); bridge=ComfyUIJobBridge(repo); foreign=Project(ProjectId('foreign'))
  before_ref=self.a.external_job_ref; before_saved=len(repo.saved)
  with self.assertRaises(ValueError): bridge.bind(foreign,self.e,'c',str(self.a.id),BackendJobRef('new'))
  self.assertEqual(len(repo.saved),before_saved); self.assertEqual(self.a.external_job_ref,before_ref); self.assertEqual(self.e.project_id,ProjectId('p'))
 def test_40_bind_matching_project_saves_and_binds(self):
  repo=Repo(); bridge=ComfyUIJobBridge(repo)
  self.assertEqual(bridge.bind(self.p,self.e,'c',str(self.a.id),self.ref),self.ref)
  self.assertEqual(len(repo.saved),1); self.assertEqual(self.a.external_job_ref,self.ref)
 def test_41_block_for_review_is_nonmutating_and_does_not_save(self):
  repo=Repo(); bridge=ComfyUIJobBridge(repo)
  before_attempts=len(self.c.attempts); before_ref=self.a.external_job_ref; before_state=self.a.state
  result=ReconciliationResult('e',Decision.NEEDS_MANUAL_REVIEW,0,0,str(self.a.id),proposed_actions=(Action.BLOCK_FOR_REVIEW,))
  self.assertIs(bridge.apply(self.p,self.e,result),result)
  self.assertEqual(repo.saved,[]); self.assertEqual(len(self.c.attempts),before_attempts); self.assertEqual(self.a.external_job_ref,before_ref); self.assertEqual(self.a.state,before_state)
