"""Transactional SQLite persistence."""
import json, os, sqlite3
from pathlib import Path
from orquestador.domain import *
SCHEMA_VERSION=1
class PersistenceError(Exception): pass
class PersistenceConflictError(PersistenceError): pass
PersistenceConflict=PersistenceConflictError
class UnsupportedSchemaVersion(PersistenceError): pass
class PersistenceDataError(PersistenceError): pass
CorruptDatabaseError=PersistenceDataError
def _json(v): return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def _safe(root,v):
 if not isinstance(v,str) or not v.strip(): raise PersistenceError('path must be non-empty')
 p=Path(v)
 if p.is_absolute() or os.path.splitdrive(v)[0] or v.startswith(('\\','/')) or '..' in p.parts: raise PersistenceError('path must be project-relative')
 try:(root/p).resolve().relative_to(root)
 except ValueError: raise PersistenceError('path escapes project root')
 return p.as_posix()
_NEXT={Lifecycle.PENDING:{Lifecycle.RUNNING,Lifecycle.CANCELLED},Lifecycle.RUNNING:{Lifecycle.SUCCEEDED,Lifecycle.FAILED,Lifecycle.CANCELLED}}
def _legal(a,b): return a==b or (a is Lifecycle.UNKNOWN and b is not Lifecycle.PENDING) or b in _NEXT.get(a,set())
class SQLiteProjectRepository:
 migrations={}
 def __init__(self,project_root,db_name='orquestador.sqlite3'):
  self.root=Path(project_root).resolve(); self.root.mkdir(parents=True,exist_ok=True); self.path=self.root/_safe(self.root,db_name); self.path.parent.mkdir(parents=True,exist_ok=True)
  try:self.db=sqlite3.connect(self.path,isolation_level=None)
  except sqlite3.DatabaseError as e: raise PersistenceDataError(str(e))
  self.db.execute('PRAGMA foreign_keys=ON'); self._init()
 @classmethod
 def register_migration(cls,version,fn): cls.migrations[version]=fn
 def _run_migrations(self, migrations=None, target_version=SCHEMA_VERSION):
  """Apply ordered migrations atomically; intended for private/test use."""
  mapping = self.migrations if migrations is None else migrations
  current = self.db.execute('SELECT version FROM schema_version').fetchone()[0]
  if current > target_version: raise UnsupportedSchemaVersion(current)
  if current == target_version: return
  try:
   self.db.execute('BEGIN')
   for version in range(current + 1, target_version + 1):
    fn = mapping.get(version)
    if fn is None: raise PersistenceDataError(f'missing migration {version}')
    fn(self.db)
    self.db.execute('UPDATE schema_version SET version=?', (version,))
   self.db.execute('COMMIT')
  except Exception as e:
   if self.db.in_transaction: self.db.execute('ROLLBACK')
   if isinstance(e, PersistenceError): raise
   raise PersistenceError(str(e)) from e
 def _init(self):
  if self.path.stat().st_size==0:self.db.executescript('BEGIN; CREATE TABLE schema_version(version INTEGER NOT NULL); INSERT INTO schema_version VALUES(1); CREATE TABLE projects(id TEXT PRIMARY KEY,defaults TEXT NOT NULL); CREATE TABLE executions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),defaults TEXT NOT NULL,state TEXT NOT NULL,workflow_profile_ref TEXT); CREATE TABLE chunks(id TEXT PRIMARY KEY,execution_id TEXT NOT NULL REFERENCES executions(id),ord INTEGER NOT NULL,defaults TEXT NOT NULL,state TEXT NOT NULL,UNIQUE(execution_id,ord)); CREATE TABLE attempts(id TEXT PRIMARY KEY,chunk_id TEXT NOT NULL REFERENCES chunks(id),number INTEGER NOT NULL,state TEXT NOT NULL,output TEXT,evidence TEXT,error_id TEXT,output_artifact_id TEXT,external_job_ref TEXT); CREATE TABLE errors(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,execution_id TEXT NOT NULL,chunk_id TEXT NOT NULL,attempt_id TEXT NOT NULL,code TEXT NOT NULL,message TEXT NOT NULL); CREATE TABLE artifacts(id TEXT PRIMARY KEY,project_id TEXT,execution_id TEXT,chunk_id TEXT,attempt_id TEXT,phase TEXT,output TEXT,path TEXT); CREATE TABLE transitions(project_id TEXT,execution_id TEXT,target_chunk_id TEXT PRIMARY KEY,source_chunk_id TEXT,source_attempt_id TEXT,source_output TEXT,frame_index INTEGER,frame_count INTEGER); COMMIT;')
  try:v=self.db.execute('SELECT version FROM schema_version').fetchone()
  except sqlite3.DatabaseError as e: raise PersistenceDataError(str(e))
  if not v:raise PersistenceDataError('missing schema version')
  if v[0]>SCHEMA_VERSION:raise UnsupportedSchemaVersion(v[0])
 def close(self):self.db.close()
 def save(self,p,es,artifacts=(),errors=(),transitions=()):
  try:
   owners={str(a.id):(e,c) for e in es for c in e.chunks for a in c.attempts}
   for ar in artifacts:
    own=owners.get(str(ar.attempt_id))
    if ar.project_id!=p.id or not own or str(own[0].id)!=str(ar.execution_id) or str(own[1].id)!=str(ar.chunk_id): raise PersistenceDataError('artifact provenance')
    old=self.db.execute('SELECT phase,output FROM artifacts WHERE id=?',(str(ar.id),)).fetchone()
    if old and old!=(ar.phase.value,ar.output.uri): raise PersistenceConflictError('immutable artifact conflict')
   self.db.execute('BEGIN'); self.db.execute('INSERT INTO projects VALUES(?,?) ON CONFLICT(id) DO UPDATE SET defaults=excluded.defaults',(str(p.id),_json(dict(p.defaults))))
   for e in es:
    prof=e.workflow_profile_ref.value if e.workflow_profile_ref else None; old=self.db.execute('SELECT state,workflow_profile_ref FROM executions WHERE id=?',(str(e.id),)).fetchone()
    if old and (not _legal(Lifecycle(old[0]),e.state) or old[1]!=prof):raise PersistenceConflictError('execution lifecycle/profile conflict')
    self.db.execute('INSERT INTO executions VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET defaults=excluded.defaults,state=excluded.state,workflow_profile_ref=excluded.workflow_profile_ref',(str(e.id),str(p.id),_json(dict(e.defaults)),e.state.value,prof))
    for c in e.chunks:
     self.db.execute('INSERT INTO chunks VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET defaults=excluded.defaults,state=excluded.state',(str(c.id),str(e.id),c.order,_json(dict(c.defaults)),c.state.value))
     for a in c.attempts:
      oldref=self.db.execute('SELECT external_job_ref FROM attempts WHERE id=?',(str(a.id),)).fetchone()
      if oldref and oldref[0] and a.external_job_ref and oldref[0]!=str(a.external_job_ref): raise PersistenceConflictError('backend job reference conflict')
      self.db.execute('INSERT INTO attempts(id,chunk_id,number,state,output,evidence,error_id,output_artifact_id,external_job_ref) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,output=COALESCE(attempts.output,excluded.output),evidence=COALESCE(attempts.evidence,excluded.evidence),error_id=excluded.error_id,external_job_ref=COALESCE(attempts.external_job_ref,excluded.external_job_ref)',(str(a.id),str(c.id),a.number,a.state.value,a.output.uri if a.output else None,a.evidence.detail if a.evidence else None,str(a.error.id) if a.error else None,None,str(a.external_job_ref) if a.external_job_ref else None))
      if a.error:self.db.execute('INSERT OR IGNORE INTO errors VALUES(?,?,?,?,?,?,?)',(str(a.error.id),str(p.id),str(e.id),str(c.id),str(a.id),a.error.code,a.error.message))
   for a in artifacts:self.db.execute('INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?,?,?,?,?)',(str(a.id),str(a.project_id),str(a.execution_id),str(a.chunk_id),str(a.attempt_id),a.phase.value,a.output.uri,_safe(self.root,a.output.uri)))
   transition_keys={(str(t.execution_id),str(t.source_chunk_id),str(t.source_attempt_id)) for t in transitions}
   has_null={(str(t.execution_id),str(t.source_chunk_id),str(t.source_attempt_id)) for t in transitions if t.target_chunk_id is None}
   for t in transitions:
    # F5 may have persisted a provisional NULL target; F7 upgrades that
    # checkpoint atomically to the immediately-following chunk link.
    if t.target_chunk_id is not None and (str(t.execution_id),str(t.source_chunk_id),str(t.source_attempt_id)) not in has_null:
     self.db.execute('DELETE FROM transitions WHERE execution_id=? AND source_chunk_id=? AND source_attempt_id=? AND target_chunk_id IS NULL',(str(t.execution_id),str(t.source_chunk_id),str(t.source_attempt_id)))
    self.db.execute('INSERT OR REPLACE INTO transitions VALUES(?,?,?,?,?,?,?,?)',(str(t.project_id),str(t.execution_id),str(t.target_chunk_id) if t.target_chunk_id is not None else None,str(t.source_chunk_id),str(t.source_attempt_id),t.source_output.uri,t.source_frame_index,t.frame_count))
   self.db.execute('COMMIT')
  except PersistenceError:
   if self.db.in_transaction:self.db.execute('ROLLBACK')
   raise
  except Exception as e:
   if self.db.in_transaction:self.db.execute('ROLLBACK')
   raise PersistenceError(str(e))
 def load(self,pid):
  row=self.db.execute('SELECT defaults FROM projects WHERE id=?',(str(pid),)).fetchone()
  if not row:raise PersistenceError('project not found')
  p=Project(ProjectId(str(pid)),json.loads(row[0])); es=[]; cm={}; am={}
  for eid,d,s,w in self.db.execute('SELECT id,defaults,state,workflow_profile_ref FROM executions WHERE project_id=?',(str(pid),)):
   e=Execution(p.id,ExecutionId(eid),json.loads(d),Lifecycle(s),[],WorkflowProfileRef(w) if w else None); es.append(e)
   for cid,o,cd,cs in self.db.execute('SELECT id,ord,defaults,state FROM chunks WHERE execution_id=? ORDER BY ord',(eid,)):
    c=Chunk(ChunkId(cid),o,e.id,json.loads(cd),Lifecycle(cs)); e.add_chunk(c); cm[cid]=(e,c)
    for aid,n,st,out,ev,err,oaid,jobref in self.db.execute('SELECT id,number,state,output,evidence,error_id,output_artifact_id,external_job_ref FROM attempts WHERE chunk_id=?',(cid,)):
     er=None
     if err:
      x=self.db.execute('SELECT code,message,project_id,execution_id,chunk_id,attempt_id FROM errors WHERE id=?',(err,)).fetchone()
      if not x or x[2:]!=(str(pid),eid,cid,aid):raise PersistenceDataError('error ownership mismatch')
      er=ErrorRecord(x[0],x[1],ErrorId(err))
     a=Attempt(AttemptId(aid),n,Lifecycle(st),OutputRef(out) if out else None,Evidence(ev) if ev else None,er,BackendJobRef(jobref) if jobref else None); c.attempts.append(a); am[aid]=(e,c,a)
     if err and not self.db.execute('SELECT 1 FROM errors WHERE id=?',(err,)).fetchone(): raise PersistenceDataError('dangling error reference')
     if oaid and not self.db.execute('SELECT 1 FROM artifacts WHERE id=?',(oaid,)).fetchone(): raise PersistenceDataError('dangling artifact reference')
  for eid,pr in self.db.execute('SELECT id,project_id FROM executions'):
   if pr==str(pid) and eid not in {e.id.value for e in es}: raise PersistenceDataError('execution ownership mismatch')
  for erid,pr,ex,ch,at,code,msg in self.db.execute('SELECT id,project_id,execution_id,chunk_id,attempt_id,code,message FROM errors'):
   own=am.get(at)
   if pr!=str(pid) or not own or own[0].id.value!=ex or own[1].id.value!=ch: raise PersistenceDataError('error ownership mismatch')
  arts={}
  for aid,pr,ex,ch,at,ph,out in self.db.execute('SELECT id,project_id,execution_id,chunk_id,attempt_id,phase,output FROM artifacts'):
   own=am.get(at)
   if pr!=str(pid) or not own or own[0].id.value!=ex or own[1].id.value!=ch or own[2].output is None or own[2].output.uri!=out:raise PersistenceDataError('artifact ownership mismatch')
   own[0].artifacts.append(Artifact(ProjectId(pr),ExecutionId(ex),ChunkId(ch),AttemptId(at),Phase(ph),OutputRef(out),ArtifactId(aid)))
   arts[aid]=own
  for aid,_,_,_,_,_,_,oaid in self.db.execute('SELECT id,chunk_id,number,state,output,evidence,error_id,output_artifact_id FROM attempts'):
   if oaid:
    own=am.get(aid); ar=arts.get(oaid)
    if not ar or ar is not own: raise PersistenceDataError('attempt artifact ownership mismatch')
  for pr,ex,tgt,src,sa,out,idx,count in self.db.execute('SELECT project_id,execution_id,target_chunk_id,source_chunk_id,source_attempt_id,source_output,frame_index,frame_count FROM transitions'):
   if pr!=str(pid) or src not in cm or ex!=cm[src][0].id.value:raise PersistenceDataError('transition ownership')
   _,sc=cm[src]; own=am.get(sa)
   if tgt is not None:
    if tgt not in cm or ex!=cm[tgt][0].id.value: raise PersistenceDataError('transition ownership')
    _,tc=cm[tgt]
    if tc.order!=sc.order+1: raise PersistenceDataError('invalid transition provenance')
   if not own or own[1].id.value!=src or own[2].output is None or own[2].output.uri!=out or idx<0 or (count is not None and idx!=count-1):raise PersistenceDataError('invalid transition provenance')
   if tgt is not None: tc.first_frame=TransitionFrame(ProjectId(pr),ExecutionId(ex),ChunkId(src),AttemptId(sa),OutputRef(out),idx,count,ChunkId(tgt))
  return p,es
 def load_transitions(self, execution_id):
  """Read durable transition frames without exposing storage details to application code."""
  rows=self.db.execute('SELECT project_id,execution_id,target_chunk_id,source_chunk_id,source_attempt_id,source_output,frame_index,frame_count FROM transitions WHERE execution_id=? ORDER BY frame_index',(str(execution_id),)).fetchall()
  result=[]
  for pr,ex,tgt,src,sa,out,idx,count in rows:
   if ex != str(execution_id): raise PersistenceDataError('transition execution mismatch')
   src_row=self.db.execute('SELECT execution_id,ord FROM chunks WHERE id=?',(src,)).fetchone()
   att=self.db.execute('SELECT chunk_id,state,output FROM attempts WHERE id=?',(sa,)).fetchone()
   if not src_row or src_row[0]!=ex or not att or att[0]!=src or att[1] != Lifecycle.SUCCEEDED.value or att[2] != out:
    raise PersistenceDataError('invalid transition source provenance')
   if tgt is not None:
    trg=self.db.execute('SELECT execution_id,ord FROM chunks WHERE id=?',(tgt,)).fetchone()
    if not trg or trg[0]!=ex or trg[1] != src_row[1]+1: raise PersistenceDataError('invalid transition target provenance')
   try: safe=_safe(self.root,out)
   except PersistenceError as exc: raise PersistenceDataError(str(exc)) from exc
   # F5 provisional fixtures may not yet have an artifact row; once an
   # artifact is recorded, its durable file must exist and remain contained.
   ar=self.db.execute('SELECT path FROM artifacts WHERE execution_id=? AND chunk_id=? AND attempt_id=? AND output=?',(ex,src,sa,out)).fetchone()
   if ar is not None and ar[0] != safe: raise PersistenceDataError('transition artifact path mismatch')
   result.append(TransitionFrame(ProjectId(pr),ExecutionId(ex),ChunkId(src),AttemptId(sa),OutputRef(out),idx,count,ChunkId(tgt) if tgt is not None else None))
  return result
