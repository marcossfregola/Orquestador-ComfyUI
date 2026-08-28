import unittest,tempfile,sqlite3,hashlib
from orquestador.domain import *
from orquestador.persistence import *
from orquestador.persistence.sqlite import PersistenceDataError

class Corruption(unittest.TestCase):
 def setUp(self):
  self.d=tempfile.TemporaryDirectory(); self.r=SQLiteProjectRepository(self.d.name)
  self.p=Project(ProjectId('p')); self.e=Execution(self.p.id,ExecutionId('e')); self.c0=Chunk(ChunkId('c0'),0); self.c1=Chunk(ChunkId('c1'),1); self.e.add_chunk(self.c0); self.e.add_chunk(self.c1); self.a=self.c0.new_attempt(); self.a.transition(Lifecycle.RUNNING); self.a.transition(Lifecycle.SUCCEEDED,output=OutputRef('o'),evidence=Evidence('x')); self.ar=Artifact(self.p.id,self.e.id,self.c0.id,self.a.id,Phase.OUTPUT,OutputRef('o'),ArtifactId('ar')); self.t=TransitionFrame(self.p.id,self.e.id,self.c0.id,self.a.id,OutputRef('o'),0,1,self.c1.id); self.r.save(self.p,[self.e],[self.ar],transitions=[self.t]); self.r.close()
 def tearDown(self):
  try:self.r.close()
  except Exception:pass
  self.d.cleanup()
 def corrupt(self,sql,args=()):
  db=sqlite3.connect(self.r.path); db.execute('PRAGMA foreign_keys=OFF'); db.execute(sql,args); db.commit(); db.close(); self.r=SQLiteProjectRepository(self.d.name)
 def bad(self,sql,args=()): self.corrupt(sql,args); self.assertRaises(PersistenceDataError,self.r.load,self.p.id)
 def test_artifact_dangling_attempt(self): self.bad('update artifacts set attempt_id="x"')
 def test_artifact_wrong_chunk(self): self.bad('update artifacts set chunk_id="c1"')
 def test_artifact_wrong_attempt(self): self.bad('update artifacts set attempt_id="x"')
 def test_error_dangling_attempt(self): self.corrupt('insert into errors values("er","p","e","c0","x","E","m")'); self.assertRaises(PersistenceDataError,self.r.load,'p')
 def test_error_wrong_chunk_attempt(self): self.corrupt('insert into errors values("er","p","e","c1","'+self.a.id.value+'","E","m")'); self.assertRaises(PersistenceDataError,self.r.load,'p')
 def test_attempt_dangling_output_artifact(self): self.bad('update attempts set output_artifact_id="x"')
 def test_attempt_cross_artifact(self): self.bad('update attempts set output_artifact_id="x"')
 def test_attempt_dangling_error(self): self.bad('update attempts set error_id="x"')
 def test_attempt_cross_error(self): self.bad('update attempts set error_id="x"')
 def test_transition_dangling_target(self): self.bad('update transitions set target_chunk_id="x"')
 def test_transition_dangling_source(self): self.bad('update transitions set source_chunk_id="x"')
 def test_transition_nonadjacent(self): self.bad('update transitions set source_chunk_id="c1"')
 def test_transition_source_attempt_wrong_chunk(self): self.bad('update transitions set source_attempt_id="x"')
 def test_transition_source_output_wrong_attempt(self): self.bad('update transitions set source_output="bad"')
 def test_transition_invalid_n_minus_one(self): self.bad('update transitions set frame_index=1')
 def test_roundtrip_transition_exact(self):
  self.r=SQLiteProjectRepository(self.d.name); p,es=self.r.load('p'); got=es[0].chunks[1].first_frame; self.assertEqual(got,self.t)
 def test_failed_load_does_not_replace_file(self):
  self.corrupt('update transitions set frame_index=1'); h=hashlib.sha256(open(self.r.path,'rb').read()).hexdigest(); self.assertRaises(PersistenceDataError,self.r.load,'p'); self.assertEqual(h,hashlib.sha256(open(self.r.path,'rb').read()).hexdigest())

if __name__=='__main__': unittest.main()
