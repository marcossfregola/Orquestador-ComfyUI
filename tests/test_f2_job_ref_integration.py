import tempfile, unittest
from orquestador.domain import *
from orquestador.domain.recovery import *
from orquestador.persistence.sqlite import SQLiteProjectRepository, PersistenceConflictError

class JobRefIntegration(unittest.TestCase):
 def make(self):
  p=Project(ProjectId('p')); e=Execution(p.id,ExecutionId('e')); c=Chunk(order=0); e.add_chunk(c); a=c.new_attempt(); a.transition(Lifecycle.RUNNING); a.assign_external_job_ref(BackendJobRef('opaque-1')); return p,e,c,a
 def test_ref_roundtrip_restart(self):
  p,e,c,a=self.make()
  with tempfile.TemporaryDirectory() as d:
   r=SQLiteProjectRepository(d); r.save(p,[e]); r.close(); r=SQLiteProjectRepository(d); _,es=r.load(p.id); self.assertEqual(es[0].chunks[0].attempts[0].external_job_ref,BackendJobRef('opaque-1')); r.close()
 def test_ref_conflict_and_stale_preserve(self):
  p,e,c,a=self.make()
  with tempfile.TemporaryDirectory() as d:
   r=SQLiteProjectRepository(d); r.save(p,[e]); stale=Attempt(a.id,a.number,a.state); c.attempts[0]=stale
   r.save(p,[e]); self.assertEqual(r.load(p.id)[1][0].chunks[0].attempts[0].external_job_ref.value,'opaque-1')
   with self.assertRaises(DomainError): a.assign_external_job_ref(BackendJobRef('other'))
   r.close()
 def test_wrong_ref_blocks(self):
  p,e,c,a=self.make(); j=BackendJobObservation('p','e',str(c.id),str(a.id),BackendJobState.RUNNING,BackendJobRef('wrong'))
  self.assertEqual(reconcile(e,jobs=(j,)).decision,Decision.NEEDS_MANUAL_REVIEW)
 def test_same_ref_waits(self):
  p,e,c,a=self.make(); j=BackendJobObservation('p','e',str(c.id),str(a.id),BackendJobState.QUEUED,BackendJobRef('opaque-1'))
  self.assertEqual(reconcile(e,jobs=(j,)).decision,Decision.WAIT_FOR_EXTERNAL_JOB)
 def test_terminal_ref_retry(self):
  p,e,c,a=self.make(); j=BackendJobObservation('p','e',str(c.id),str(a.id),BackendJobState.FAILED,BackendJobRef('opaque-1'))
  x=reconcile(e,jobs=(j,)); self.assertEqual(x.decision,Decision.RETRY_CURRENT_CHUNK); self.assertTrue(x.durable_mutation_proposed)
 def test_unknown_ref_review(self):
  p,e,c,a=self.make(); j=BackendJobObservation('p','e',str(c.id),str(a.id),BackendJobState.UNKNOWN,BackendJobRef('opaque-1'))
  self.assertEqual(reconcile(e,jobs=(j,)).decision,Decision.NEEDS_MANUAL_REVIEW)
 def test_reconcile_pure(self):
  p,e,c,a=self.make(); before=a.external_job_ref; reconcile(e); self.assertEqual(a.external_job_ref,before)

if __name__=='__main__': unittest.main()

def _matrix_case(state, ref):
 def test(self):
  p,e,c,a=self.make(); j=BackendJobObservation('p','e',str(c.id),str(a.id),state,ref)
  result=reconcile(e,jobs=(j,))
  self.assertIn(result.decision,{Decision.WAIT_FOR_EXTERNAL_JOB,Decision.RETRY_CURRENT_CHUNK,Decision.NEEDS_MANUAL_REVIEW})
 return test
for _i, (_state, _ref) in enumerate([
 (BackendJobState.RUNNING, BackendJobRef('opaque-1')),(BackendJobState.QUEUED, BackendJobRef('opaque-1')),
 (BackendJobState.FAILED, BackendJobRef('opaque-1')),(BackendJobState.CANCELLED, BackendJobRef('opaque-1')),
 (BackendJobState.UNKNOWN, BackendJobRef('opaque-1')),(BackendJobState.RUNNING, BackendJobRef('x')),
 (BackendJobState.QUEUED, BackendJobRef('x')),(BackendJobState.FAILED, BackendJobRef('x')),
 (BackendJobState.CANCELLED, BackendJobRef('x')),(BackendJobState.UNKNOWN, BackendJobRef('x')),
 (BackendJobState.RUNNING, None),(BackendJobState.UNKNOWN, None)]):
 setattr(JobRefIntegration, f'test_observation_matrix_{_i}', _matrix_case(_state, _ref))
