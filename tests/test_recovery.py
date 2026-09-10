import unittest
from orquestador.domain import *

class RecoveryTests(unittest.TestCase):
 def make(self,n=1):
  p=Project(ProjectId('p')); e=Execution(p.id,ExecutionId('e'))
  for i in range(n): e.add_chunk(Chunk(ChunkId(f'c{i}'),i))
  return p,e
 def success(self,e,i=0):
  c=e.chunks[i]; a=c.new_attempt(); a.transition(Lifecycle.RUNNING); o=OutputRef(f'o{i}'); a.transition(Lifecycle.SUCCEEDED,output=o,evidence=Evidence('ok')); c.transition(Lifecycle.RUNNING); c.transition(Lifecycle.SUCCEEDED); return a,o
 def obs(self,e,i,a,o): return (ArtifactObservation('p','e',f'c{i}',str(a.id),o,True,True),)
 def test_pending_retry(self):
  _,e=self.make(); r=reconcile(e); self.assertEqual(r.decision,Decision.RETRY_CURRENT_CHUNK)
 def test_running_unknown_manual(self):
  _,e=self.make(); c=e.chunks[0]; a=c.new_attempt(); a.transition(Lifecycle.RUNNING); r=reconcile(e); self.assertEqual(r.decision,Decision.NEEDS_MANUAL_REVIEW)
 def test_running_active_wait(self):
  _,e=self.make(); c=e.chunks[0]; a=c.new_attempt(); a.transition(Lifecycle.RUNNING); j=BackendJobObservation('p','e','c0',str(a.id),BackendJobState.RUNNING); self.assertEqual(reconcile(e,jobs=(j,)).decision,Decision.WAIT_FOR_EXTERNAL_JOB)
 def test_running_queued_wait(self):
  _,e=self.make(); a=e.chunks[0].new_attempt(); a.transition(Lifecycle.RUNNING); j=BackendJobObservation('p','e','c0',str(a.id),BackendJobState.QUEUED); self.assertEqual(reconcile(e,jobs=(j,)).decision,Decision.WAIT_FOR_EXTERNAL_JOB)
 def test_running_failed_retry(self):
  _,e=self.make(); a=e.chunks[0].new_attempt(); a.transition(Lifecycle.RUNNING); j=BackendJobObservation('p','e','c0',str(a.id),BackendJobState.FAILED); r=reconcile(e,jobs=(j,)); self.assertEqual(r.decision,Decision.RETRY_CURRENT_CHUNK); self.assertIn(Action.CREATE_NEW_ATTEMPT,r.proposed_actions)
 def test_cancelled_retry(self):
  _,e=self.make(); a=e.chunks[0].new_attempt(); a.transition(Lifecycle.CANCELLED); self.assertEqual(reconcile(e).decision,Decision.RETRY_CURRENT_CHUNK)
 def test_success_missing_output_block(self):
  _,e=self.make(); self.success(e); self.assertEqual(reconcile(e).decision,Decision.BLOCKED_CORRUPT_STATE)
 def test_pending_bound_lost_job_reaches_retry_without_output_requirement(self):
  _,e=self.make(2); a0,o0=self.success(e,0); ob=self.obs(e,0,a0,o0)[0]
  t=TransitionObservation('p','e','c0',str(a0.id),'c1',True,True,o0)
  e.chunks[1].transition(Lifecycle.RUNNING)
  a1=e.chunks[1].new_attempt(); a1.assign_external_job_ref(BackendJobRef('lost'))
  job=BackendJobObservation('p','e','c1',str(a1.id),BackendJobState.UNKNOWN,BackendJobRef('lost'))
  r=reconcile(e,artifacts=(ob,),jobs=(job,),transitions=(t,))
  self.assertEqual(r.decision,Decision.RETRY_CURRENT_CHUNK)
  self.assertIn(Action.CREATE_NEW_ATTEMPT,r.proposed_actions)
  self.assertNotIn(EvidenceCode.MISSING_OUTPUT,r.evidence_codes)
 def test_success_corrupt_output_block(self):
  _,e=self.make(); a,o=self.success(e); ob=ArtifactObservation('p','e','c0',str(a.id),o,True,False); self.assertEqual(reconcile(e,artifacts=(ob,)).decision,Decision.BLOCKED_CORRUPT_STATE)
 def test_wrong_provenance_block(self):
  _,e=self.make(); a,o=self.success(e); ob=ArtifactObservation('p','other','c0',str(a.id),o,True,True); self.assertEqual(reconcile(e,artifacts=(ob,)).decision,Decision.BLOCKED_CORRUPT_STATE)
 def test_artifact_wrong_attempt_block(self):
  _,e=self.make(); a,o=self.success(e); ob=ArtifactObservation('p','e','c0','wrong',o,True,True); self.assertEqual(reconcile(e,artifacts=(ob,)).decision,Decision.BLOCKED_CORRUPT_STATE)
 def test_transition_wrong_source_block(self):
  _,e=self.make(2); a,o=self.success(e,0); ob=self.obs(e,0,a,o)[0]; t=TransitionObservation('p','e','wrong',str(a.id),'c1',True,True,o); self.assertEqual(reconcile(e,artifacts=(ob,),transitions=(t,)).decision,Decision.NEEDS_MANUAL_REVIEW)
 def test_final_success_needs_no_transition(self):
  _,e=self.make(); a,o=self.success(e); self.assertEqual(reconcile(e,artifacts=self.obs(e,0,a,o)).decision,Decision.COMPLETE)
 def test_failed_history_preserved(self):
  _,e=self.make(); a=e.chunks[0].new_attempt(); a.transition(Lifecycle.CANCELLED); reconcile(e); self.assertEqual(len(e.chunks[0].attempts),1)
 def test_backend_identity_mismatch_not_applied(self):
  _,e=self.make(); a=e.chunks[0].new_attempt(); a.transition(Lifecycle.RUNNING); j=BackendJobObservation('p','e','other',str(a.id),BackendJobState.RUNNING); self.assertEqual(reconcile(e,jobs=(j,)).decision,Decision.NEEDS_MANUAL_REVIEW)
 def test_result_mutation_flag(self):
  _,e=self.make(); self.assertTrue(reconcile(e).durable_mutation_proposed)
 def test_nonfinal_missing_transition(self):
  _,e=self.make(2); a,o=self.success(e,0); ob=self.obs(e,0,a,o)[0]; r=reconcile(e,artifacts=(ob,)); self.assertEqual(r.decision,Decision.NEEDS_MANUAL_REVIEW); self.assertIn(Action.REGENERATE_TRANSITION_FRAME,r.proposed_actions)
 def test_nonfinal_corrupt_transition(self):
  _,e=self.make(2); a,o=self.success(e,0); ob=self.obs(e,0,a,o)[0]; t=TransitionObservation('p','e','c0',str(a.id),'c1',True,False,o); self.assertEqual(reconcile(e,artifacts=(ob,),transitions=(t,)).decision,Decision.NEEDS_MANUAL_REVIEW)
 def test_continue_after_transition(self):
  _,e=self.make(2); a,o=self.success(e,0); ob=self.obs(e,0,a,o)[0]; t=TransitionObservation('p','e','c0',str(a.id),'c1',True,True,o); r=reconcile(e,artifacts=(ob,),transitions=(t,)); self.assertEqual(r.next_actionable_chunk,1)
 def test_gap_not_skipped(self):
  _,e=self.make(3); a,o=self.success(e,0); ob=self.obs(e,0,a,o)[0]; t=TransitionObservation('p','e','c0',str(a.id),'c1',True,True,o); r=reconcile(e,artifacts=(ob,),transitions=(t,)); self.assertEqual(r.next_actionable_chunk,1)
 def test_complete_chain(self):
  _,e=self.make(2); a0,o0=self.success(e,0); a1,o1=self.success(e,1); obs=self.obs(e,0,a0,o0)+self.obs(e,1,a1,o1); t=TransitionObservation('p','e','c0',str(a0.id),'c1',True,True,o0); self.assertEqual(reconcile(e,artifacts=obs,transitions=(t,)).decision,Decision.COMPLETE)
 def test_deterministic(self):
  _,e=self.make(); a,o=self.success(e); ob=self.obs(e,0,a,o); self.assertEqual(reconcile(e,artifacts=ob),reconcile(e,artifacts=ob))
 def test_input_unchanged(self):
  _,e=self.make(); before=e.chunks[0].state; reconcile(e); self.assertEqual(e.chunks[0].state,before)
 def test_identity_fields(self):
  _,e=self.make(); r=reconcile(e); self.assertEqual(r.execution_id,'e')
 def test_no_percentages(self): self.assertFalse(hasattr(reconcile(self.make()[1]),'percent'))
 def test_external_completed_unverified(self):
  _,e=self.make(); a=e.chunks[0].new_attempt(); a.transition(Lifecycle.RUNNING); j=BackendJobObservation('p','e','c0',str(a.id),BackendJobState.COMPLETED); self.assertEqual(reconcile(e,jobs=(j,)).decision,Decision.NEEDS_MANUAL_REVIEW)
 def test_retry_does_not_rewrite(self):
  _,e=self.make(); a=e.chunks[0].new_attempt(); a.transition(Lifecycle.CANCELLED); r=reconcile(e); self.assertEqual(a.state,Lifecycle.CANCELLED); self.assertIn(Action.CREATE_NEW_ATTEMPT,r.proposed_actions)

if __name__=='__main__': unittest.main()
