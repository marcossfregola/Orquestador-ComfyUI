import unittest,tempfile
from pathlib import Path
from orquestador.domain import *
from orquestador.persistence import *

class Extra(unittest.TestCase):
 def test_migration_registry(self):
  fn=lambda db:None; SQLiteProjectRepository.register_migration(2,fn); self.assertIs(SQLiteProjectRepository.migrations[2],fn)
 def test_unknown_lifecycle(self): self.assertEqual(Lifecycle.UNKNOWN.value,'unknown')
 def test_output_path_nested(self):
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
   r=SQLiteProjectRepository(d); self.assertEqual(r.path.parent.resolve(),Path(d).resolve()); r.close()
 def test_profile_roundtrip_value(self):
  p,e,c,a=self.base(); e.workflow_profile_ref=WorkflowProfileRef('x'); self.assertEqual(e.workflow_profile_ref.value,'x')
 def test_attempt_numbers(self): p,e,c,a=self.base(); self.assertEqual(a.number,1)
 def test_chunk_order(self): p,e,c,a=self.base(); self.assertEqual(c.order,0)
 def test_error_identity(self): er=ErrorRecord('x','y'); self.assertEqual(er.code,'x')
 def test_artifact_phase(self): p,e,c,a=self.base(); self.assertEqual(Phase.OUTPUT.value,'output')
 def test_transition_optional_count(self): p,e,c,a=self.base(); self.assertIsNone(TransitionFrame(p.id,e.id,c.id,a.id,a.output,0).frame_count)
 def test_project_defaults(self): self.assertEqual(dict(self.base()[0].defaults),{})
 def base(self):
  p=Project(ProjectId('p')); e=Execution(p.id,ExecutionId('e')); c=Chunk(ChunkId('c'),0); e.add_chunk(c); a=c.new_attempt(); a.transition(Lifecycle.RUNNING); a.transition(Lifecycle.SUCCEEDED,output=OutputRef('o'),evidence=Evidence('x')); return p,e,c,a
 def test_profile_none(self): self.assertIsNone(self.base()[1].workflow_profile_ref)
 def test_profile_value(self): self.assertEqual(WorkflowProfileRef('opaque').value,'opaque')
 def test_drive_path(self):
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:self.assertRaises(PersistenceError,SQLiteProjectRepository,d,'C:\\x.db')
 def test_unc_path(self):
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:self.assertRaises(PersistenceError,SQLiteProjectRepository,d,'\\\\srv\\x.db')
 def test_empty_path(self):
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:self.assertRaises(PersistenceError,SQLiteProjectRepository,d,'')
 def test_parent_path(self):
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:self.assertRaises(PersistenceError,SQLiteProjectRepository,d,'..\\x.db')
 def test_nested_path(self):
  with tempfile.TemporaryDirectory() as d:
   r=SQLiteProjectRepository(d,'sub/x.db'); self.assertTrue(Path(d,'sub','x.db').exists()); r.close()
 def test_transition_n_minus_one(self):
  p,e,c,a=self.base(); self.assertRaises(DomainError,TransitionFrame,p.id,e.id,c.id,a.id,a.output,1,1)
 def test_lifecycle_backward(self):
  p,e,c,a=self.base(); e.transition(Lifecycle.RUNNING); self.assertRaises(DomainError,e.transition,Lifecycle.PENDING)
 def test_chunk_backward(self):
  p,e,c,a=self.base(); c.transition(Lifecycle.RUNNING); self.assertRaises(DomainError,c.transition,Lifecycle.PENDING)
 def test_artifact_cross_chunk(self):
  p,e,c,a=self.base(); c2=Chunk(ChunkId('c2'),1); e.add_chunk(c2); ar=Artifact(p.id,e.id,c2.id,a.id,Phase.OUTPUT,OutputRef('x')); r=SQLiteProjectRepository(tempfile.mkdtemp()); self.assertRaises(PersistenceError,r.save,p,[e],[ar])
 def test_schema_version(self):
  with tempfile.TemporaryDirectory() as d:
   r=SQLiteProjectRepository(d); self.assertEqual(r.db.execute('select version from schema_version').fetchone()[0],1); r.close()
 def test_fk_enabled(self):
  with tempfile.TemporaryDirectory() as d:
   r=SQLiteProjectRepository(d); self.assertEqual(r.db.execute('pragma foreign_keys').fetchone()[0],1); r.close()
