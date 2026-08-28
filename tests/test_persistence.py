import unittest, tempfile, sqlite3, os
from pathlib import Path
from orquestador.domain import *
from orquestador.persistence import *

class PersistenceTests(unittest.TestCase):
 def tearDown(self):
  r=getattr(self,'r',None)
  if r: r.close()
 def make(self):
  p=Project(ProjectId('p'),{'a':1}); e=Execution(p.id,ExecutionId('e'),{'b':2}); c=Chunk(ChunkId('c'),0); e.add_chunk(c); a=c.new_attempt(); a.transition(Lifecycle.RUNNING); a.transition(Lifecycle.FAILED,error=ErrorRecord('E','bad')); b=c.new_attempt(); b.transition(Lifecycle.RUNNING); b.transition(Lifecycle.SUCCEEDED,output=OutputRef('out.mp4'),evidence=Evidence('ok')); return p,e,c,a,b
 def test_roundtrip(self):
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
   p,e,c,a,b=self.make(); self.r=r=SQLiteProjectRepository(d); r.save(p,[e]); p2,es=r.load(p.id); self.assertEqual(es[0].chunks[0].attempts[0].state,Lifecycle.FAILED); self.assertEqual(es[0].chunks[0].attempts[1].output.uri,'out.mp4'); r.close()
 def test_schema_fk(self):
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
   self.r=r=SQLiteProjectRepository(d); self.assertEqual(r.db.execute('PRAGMA foreign_keys').fetchone()[0],1); self.assertEqual(r.db.execute('SELECT version FROM schema_version').fetchone()[0],1)
 def test_idempotent_append(self):
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
   p,e,c,a,b=self.make(); self.r=r=SQLiteProjectRepository(d); r.save(p,[e]); r.save(p,[e]); self.assertEqual(r.db.execute('select count(*) from attempts').fetchone()[0],2)
 def test_stale_preserves(self):
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
   p,e,c,a,b=self.make(); self.r=r=SQLiteProjectRepository(d); r.save(p,[e]); e2=Execution(p.id,e.id); e2.add_chunk(Chunk(c.id,0)); r.save(p,[e2]); self.assertEqual(r.db.execute('select count(*) from attempts').fetchone()[0],2)
 def test_path_reject(self):
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
   p,e,c,a,b=self.make(); self.r=r=SQLiteProjectRepository(d); ar=Artifact(p.id,e.id,c.id,b.id,Phase.OUTPUT,OutputRef('../x')); self.assertRaises(PersistenceError,r.save,p,[e],[ar])
 def test_future_reject(self):
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
   self.r=r=SQLiteProjectRepository(d); r.db.execute('update schema_version set version=99'); r.db.commit(); r.close(); self.r=None; self.assertRaises(UnsupportedSchemaVersion,SQLiteProjectRepository,d)
 def test_corrupt_reject(self):
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
   Path(d,'orquestador.sqlite3').write_bytes(b'not sqlite'); self.assertRaises(CorruptDatabaseError,SQLiteProjectRepository,d)
 def test_close_reopen(self):
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
   p,e,*_=self.make(); self.r=r=SQLiteProjectRepository(d); r.save(p,[e]); r.close(); r2=SQLiteProjectRepository(d); self.assertEqual(r2.load(p.id)[0].id,p.id)
 def test_artifact_conflict(self):
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
   p,e,c,a,b=self.make(); self.r=r=SQLiteProjectRepository(d); ar=Artifact(p.id,e.id,c.id,b.id,Phase.OUTPUT,OutputRef('x')); r.save(p,[e],[ar]); ar2=Artifact(ar.project_id,ar.execution_id,ar.chunk_id,ar.attempt_id,Phase.ASSEMBLE,OutputRef('x'),ar.id); self.assertRaises(PersistenceConflict,r.save,p,[e],[ar2])
 def test_error_persist(self):
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
   p,e,*_=self.make(); self.r=r=SQLiteProjectRepository(d); r.save(p,[e]); self.assertEqual(r.db.execute('select count(*) from errors').fetchone()[0],1)
 def test_deterministic_json(self):
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
   p,e,*_=self.make(); self.r=r=SQLiteProjectRepository(d); r.save(p,[e]); self.assertEqual(r.db.execute('select defaults from projects').fetchone()[0],'{"a":1}')
 def test_atomic_failure(self):
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
   p,e,*_=self.make(); self.r=r=SQLiteProjectRepository(d); r.save(p,[e]); bad=Artifact(p.id,e.id,ChunkId('x'),AttemptId('x'),Phase.OUTPUT,OutputRef('/abs')); self.assertRaises(PersistenceError,r.save,p,[e],[bad]); self.assertEqual(r.load(p.id)[0].id,p.id)

if __name__=='__main__': unittest.main()
