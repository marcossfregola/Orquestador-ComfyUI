import sys,unittest
from orquestador.domain import *
class CoreTests(unittest.TestCase):
 def test_distinct_ids_and_nonblank(self):
  self.assertNotEqual(ProjectId('x'),ExecutionId('x')); self.assertRaises(DomainError,ProjectId,' ')
 def test_attempt_success_evidence(self):
  a=Attempt(); a.transition(Lifecycle.RUNNING); self.assertRaises(DomainError,a.transition,Lifecycle.SUCCEEDED,output=OutputRef('o')); a.transition(Lifecycle.SUCCEEDED,output=OutputRef('o'),evidence=Evidence('e'))
 def test_attempt_terminal_unknown_cancel(self):
  a=Attempt(); self.assertRaises(DomainError,a.transition,Lifecycle.UNKNOWN); a.transition(Lifecycle.CANCELLED); self.assertRaises(DomainError,a.transition,Lifecycle.RUNNING)
 def test_chunk_success_and_retry_history(self):
  c=Chunk(); a=c.new_attempt(); a.transition(Lifecycle.RUNNING); a.transition(Lifecycle.FAILED); b=c.new_attempt(); self.assertEqual(b.number,2); self.assertEqual(len(c.attempts),2)
 def test_retry_no_overlap(self):
  c=Chunk(); c.new_attempt(); self.assertRaises(DomainError,c.new_attempt)
 def test_chunk_lifecycle(self):
  c=Chunk(); c.transition(Lifecycle.RUNNING); self.assertRaises(DomainError,c.transition,Lifecycle.SUCCEEDED); a=c.new_attempt(); a.transition(Lifecycle.RUNNING); a.transition(Lifecycle.SUCCEEDED,output=OutputRef('o'),evidence=Evidence('e')); c.transition(Lifecycle.SUCCEEDED); self.assertRaises(DomainError,c.transition,Lifecycle.RUNNING)
 def test_execution_order(self):
  p=Project(); e=Execution(p.id); e.add_chunk(Chunk(order=0)); self.assertRaises(DomainError,e.add_chunk,Chunk(order=2)); self.assertRaises(DomainError,e.add_chunk,Chunk(order=0))
 def test_execution_wrong_project(self):
  e=Execution(ProjectId('p')); self.assertRaises(DomainError,e.add_chunk,Chunk(order=0,execution_id=ExecutionId('other')))
 def test_execution_success_requires_all(self):
  e=Execution(ProjectId('p')); c=Chunk(order=0); e.add_chunk(c); e.transition(Lifecycle.RUNNING); self.assertRaises(DomainError,e.transition,Lifecycle.SUCCEEDED)
 def test_execution_success(self):
  e=Execution(ProjectId('p')); c=Chunk(order=0); e.add_chunk(c); a=c.new_attempt(); a.transition(Lifecycle.RUNNING); a.transition(Lifecycle.SUCCEEDED,output=OutputRef('o'),evidence=Evidence('e')); c.transition(Lifecycle.RUNNING); c.transition(Lifecycle.SUCCEEDED); e.transition(Lifecycle.RUNNING); e.transition(Lifecycle.SUCCEEDED)
 def test_parameters_precedence_immutable(self):
  p=Project(defaults={'x':1,'a':1}); e=Execution(p.id,defaults={'x':2,'b':2}); c=Chunk(defaults={'x':3}); r=c.effective_parameters(p,e.defaults); self.assertEqual(dict(r),{'x':3,'a':1,'b':2})
  with self.assertRaises(TypeError): r['z']=1
 def test_transition_frame_final(self):
  self.assertRaises(DomainError,TransitionFrame,ProjectId('p'),ExecutionId('e'),ChunkId('c'),AttemptId('a'),OutputRef('o'),1,3)
 def test_transition_link(self):
  e=Execution(ProjectId('p')); c1=Chunk(order=0); c2=Chunk(order=1); e.add_chunk(c1); e.add_chunk(c2); a=c1.new_attempt(); a.transition(Lifecycle.RUNNING); o=OutputRef('o'); a.transition(Lifecycle.SUCCEEDED,output=o,evidence=Evidence('e')); f=TransitionFrame(ProjectId('p'),e.id,c1.id,a.id,o,9,10); e.link_transition(c2,f); self.assertIs(c2.first_frame,f)
 def test_transition_wrong_execution_previous(self):
  e=Execution(ProjectId('p')); c1=Chunk(order=0); c2=Chunk(order=1); e.add_chunk(c1); e.add_chunk(c2); f=TransitionFrame(ProjectId('p'),ExecutionId('bad'),c1.id,AttemptId('a'),OutputRef('o'),0); self.assertRaises(DomainError,e.link_transition,c2,f)
 def test_artifact_error_provenance(self):
  a=AttemptId('a'); art=Artifact(ProjectId('p'),ExecutionId('e'),ChunkId('c'),a,Phase.OUTPUT,OutputRef('o')); err=ErrorRecord('x','m'); self.assertEqual(art.attempt_id,a); self.assertIsInstance(err.id,ErrorId)
 def test_opaque_profile(self): self.assertEqual(WorkflowProfileRef('opaque').value,'opaque')
 def test_stdlib_imports(self):
  bad=[m for m in sys.modules if m.startswith('orquestador') and any(x in m for x in ('requests','ffmpeg','PyQt','comfy'))]; self.assertEqual(bad,[])
 def test_input_output_refs(self): self.assertEqual(InputRef('u').uri,'u')
 def test_failure_history(self):
  a=Attempt(); a.transition(Lifecycle.RUNNING); err=ErrorRecord('E','bad'); a.transition(Lifecycle.FAILED,error=err); self.assertEqual(a.error,err)
 def test_cancel_distinct(self):
  a=Attempt(); a.transition(Lifecycle.CANCELLED); self.assertNotEqual(a.state,Lifecycle.FAILED)
if __name__=='__main__': unittest.main()
