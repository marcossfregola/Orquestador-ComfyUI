"""Transactional SQLite persistence."""
import json, os, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from orquestador.domain import *
SCHEMA_VERSION=7
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
def _legal(a,b,*,allow_retry_reopen=False):
 return (a==b or (a is Lifecycle.UNKNOWN and b is not Lifecycle.PENDING)
         or (allow_retry_reopen and a is Lifecycle.FAILED and b in {Lifecycle.RUNNING,Lifecycle.PENDING})
         or b in _NEXT.get(a,set()))
class SQLiteProjectRepository:
 migrations={2: lambda db: [db.execute(f'ALTER TABLE transitions ADD COLUMN {c} TEXT NULL') for c in ('materialized_type','materialized_subfolder','materialized_name','materialized_source_sha256')]}
 def __init__(self,project_root,db_name='orquestador.sqlite3'):
  self.root=Path(project_root).resolve(); self.root.mkdir(parents=True,exist_ok=True); self.path=self.root/_safe(self.root,db_name); self.path.parent.mkdir(parents=True,exist_ok=True)
  try:self.db=sqlite3.connect(self.path,isolation_level=None)
  except sqlite3.DatabaseError as e: raise PersistenceDataError(str(e))
  self.db.execute('PRAGMA foreign_keys=ON'); self._init()
 @staticmethod
 def _migrate_execution_numbers(db):
  db.execute('ALTER TABLE executions ADD COLUMN execution_number INTEGER')
  project_id = None; number = 0
  for eid, current_project_id in db.execute('SELECT id,project_id FROM executions ORDER BY project_id,id'):
   if current_project_id != project_id:
    project_id, number = current_project_id, 0
   number += 1
   db.execute('UPDATE executions SET execution_number=? WHERE id=?', (number, eid))
  db.execute('CREATE UNIQUE INDEX executions_project_execution_number ON executions(project_id,execution_number)')
 migrations[3]=_migrate_execution_numbers.__func__
 @staticmethod
 def _migrate_queue(db):
  db.execute("CREATE TABLE queue_items(id TEXT PRIMARY KEY,execution_id TEXT NOT NULL REFERENCES executions(id),position INTEGER NOT NULL CHECK(position >= 0),state TEXT NOT NULL CHECK(state IN ('queued','active','finished','removed','skipped')),created_at TEXT NOT NULL,updated_at TEXT NOT NULL,terminal_reason TEXT NULL,CHECK((state IN ('queued','active','finished') AND terminal_reason IS NULL) OR (state IN ('removed','skipped') AND terminal_reason IS NOT NULL AND length(trim(terminal_reason)) > 0)),UNIQUE(position))")
  db.execute("CREATE UNIQUE INDEX queue_items_one_live_per_execution ON queue_items(execution_id) WHERE state IN ('queued','active')")
  db.execute("CREATE UNIQUE INDEX queue_items_at_most_one_active ON queue_items(state) WHERE state='active'")
  db.execute("CREATE TABLE queue_control(singleton INTEGER PRIMARY KEY CHECK(singleton=1),paused INTEGER NOT NULL CHECK(paused IN (0,1)),active_queue_item_id TEXT NULL REFERENCES queue_items(id),revision INTEGER NOT NULL CHECK(revision >= 0))")
  db.execute('INSERT INTO queue_control(singleton,paused,active_queue_item_id,revision) VALUES(1,0,NULL,0)')
 migrations[4]=_migrate_queue.__func__
 @staticmethod
 def _migrate_global_defaults(db):
  from orquestador.domain.config import GlobalDefaults
  db.execute('CREATE TABLE global_defaults(singleton INTEGER PRIMARY KEY CHECK(singleton=1),mapping TEXT NOT NULL,config_version INTEGER NOT NULL)')
  db.execute('INSERT INTO global_defaults(singleton,mapping,config_version) VALUES(1,?,1)', (_json(GlobalDefaults().to_mapping()),))
 migrations[5]=_migrate_global_defaults.__func__
 @staticmethod
 def _migrate_technical_presets(db):
  db.execute("CREATE TABLE IF NOT EXISTS technical_presets(id TEXT PRIMARY KEY,name TEXT NOT NULL,name_key TEXT NOT NULL UNIQUE,mapping TEXT NOT NULL,config_version INTEGER NOT NULL,is_default INTEGER NOT NULL CHECK(is_default IN (0,1)),created_at TEXT NOT NULL,updated_at TEXT NOT NULL,CHECK(length(trim(name)) > 0),CHECK(config_version=1))")
  db.execute("CREATE UNIQUE INDEX IF NOT EXISTS technical_presets_one_default ON technical_presets(is_default) WHERE is_default=1")
 migrations[6]=_migrate_technical_presets.__func__
 @staticmethod
 def _migrate_chunk_templates(db):
  db.execute("CREATE TABLE chunk_templates(id TEXT PRIMARY KEY,name TEXT NOT NULL,name_key TEXT NOT NULL UNIQUE,prompts TEXT NOT NULL,template_version INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,CHECK(length(trim(name)) > 0),CHECK(template_version=1))")
 migrations[7]=_migrate_chunk_templates.__func__
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
  if v[0] < SCHEMA_VERSION: self._run_migrations()
  # Repair/complete v2 columns for databases marked current but created by
  # older fixtures; this is idempotent and preserves all legacy rows.
  cols={r[1] for r in self.db.execute('PRAGMA table_info(transitions)')}
  for c in ('materialized_type','materialized_subfolder','materialized_name','materialized_source_sha256'):
   if c not in cols: self.db.execute(f'ALTER TABLE transitions ADD COLUMN {c} TEXT NULL')
 def load_global_defaults(self):
  from orquestador.domain.config import GlobalDefaults, GenerationConfigError
  try:
   rows=self.db.execute('SELECT mapping,config_version FROM global_defaults WHERE singleton=1').fetchall()
   if len(rows) != 1 or rows[0][1] != 1: raise PersistenceDataError('invalid global defaults version')
   return GlobalDefaults.from_mapping(json.loads(rows[0][0]))
  except (json.JSONDecodeError, TypeError, GenerationConfigError) as exc: raise PersistenceDataError('invalid global defaults') from exc
  except sqlite3.DatabaseError as exc: raise PersistenceDataError(str(exc)) from exc
 def save_global_defaults(self, defaults):
  from orquestador.domain.config import GlobalDefaults
  if not isinstance(defaults, GlobalDefaults): raise PersistenceDataError('invalid global defaults')
  try:
   self.db.execute('BEGIN')
   changed=self.db.execute('UPDATE global_defaults SET mapping=?,config_version=1 WHERE singleton=1',(_json(defaults.to_mapping()),)).rowcount
   if changed != 1: raise PersistenceDataError('missing global defaults')
   self.db.execute('COMMIT')
  except Exception as exc:
   if self.db.in_transaction:self.db.execute('ROLLBACK')
   if isinstance(exc,PersistenceError): raise
   raise PersistenceError(str(exc)) from exc
  return defaults
 def _technical_preset_rows(self):
  try:
   rows=self.db.execute('SELECT id,name,name_key,mapping,config_version,is_default,created_at,updated_at FROM technical_presets ORDER BY name_key,id').fetchall()
   # The partial index protects normal writes; explicit validation also makes
   # malformed/restored databases fail closed before their data is projected.
   if any(type(row[5]) is not int or row[5] not in (0,1) for row in rows): raise PersistenceDataError('invalid technical preset default')
   if sum(row[5] for row in rows) > 1: raise PersistenceDataError('duplicate technical preset default')
   return rows
  except (IndexError,TypeError) as exc: raise PersistenceDataError('invalid technical preset row') from exc
  except sqlite3.DatabaseError as exc: raise PersistenceDataError(str(exc)) from exc
 def list_technical_presets(self): return self._technical_preset_rows()
 def get_technical_preset(self,preset_id):
  rows=[row for row in self._technical_preset_rows() if row[0]==str(preset_id)]
  if len(rows)!=1: raise PersistenceError('technical preset not found')
  return rows[0]
 def list_chunk_templates(self):
  try:
   return self.db.execute('SELECT id,name,name_key,prompts,template_version,created_at,updated_at FROM chunk_templates ORDER BY name_key,id').fetchall()
  except sqlite3.DatabaseError as exc: raise PersistenceDataError(str(exc)) from exc
 def get_chunk_template(self,template_id):
  try:
   rows=self.db.execute('SELECT id,name,name_key,prompts,template_version,created_at,updated_at FROM chunk_templates WHERE id=?',(str(template_id),)).fetchall()
  except sqlite3.DatabaseError as exc: raise PersistenceDataError(str(exc)) from exc
  if len(rows)!=1: raise PersistenceError('chunk template not found')
  return rows[0]
 def close(self):self.db.close()
 def _queue_execution_is_editable_virgin(self, execution_id):
  row=self.db.execute('SELECT state FROM executions WHERE id=?',(str(execution_id),)).fetchone()
  if not row or row[0] != Lifecycle.PENDING.value: return False
  checks=(
   ('SELECT 1 FROM chunks WHERE execution_id=? AND state<>?',(str(execution_id),Lifecycle.PENDING.value)),
   ('SELECT 1 FROM attempts a JOIN chunks c ON c.id=a.chunk_id WHERE c.execution_id=?',(str(execution_id),)),
   ('SELECT 1 FROM transitions WHERE execution_id=?',(str(execution_id),)),
   ('SELECT 1 FROM artifacts WHERE execution_id=?',(str(execution_id),)),
   ('SELECT 1 FROM errors WHERE execution_id=?',(str(execution_id),)),
  )
  return not any(self.db.execute(query,args).fetchone() for query,args in checks)
 @staticmethod
 def _queue_time(value):
  if not isinstance(value,datetime) or value.tzinfo is None: raise PersistenceDataError('invalid queue timestamp')
  return value.astimezone(timezone.utc).isoformat()
 @staticmethod
 def _queue_item_from_row(row):
  try:
   created=datetime.fromisoformat(row[4]); updated=datetime.fromisoformat(row[5])
   return QueueItem(ExecutionId(row[1]),row[2],QueueItemId(row[0]),QueueItemState(row[3]),created,updated,row[6])
  except Exception as exc: raise PersistenceDataError('invalid queue item row') from exc
 def save_queue_item(self,item):
  if not isinstance(item,QueueItem): raise PersistenceDataError('invalid queue item')
  try:
   old=self.db.execute('SELECT id,execution_id,position,state,created_at,updated_at,terminal_reason FROM queue_items WHERE id=?',(str(item.id),)).fetchone()
   if old is None:
    if item.state is not QueueItemState.QUEUED: raise PersistenceConflictError('new queue item must be queued')
    if not self._queue_execution_is_editable_virgin(item.execution_id): raise PersistenceConflictError('queue execution is not editable virgin')
    self.db.execute('INSERT INTO queue_items VALUES(?,?,?,?,?,?,?)',(str(item.id),str(item.execution_id),item.position,item.state.value,self._queue_time(item.created_at),self._queue_time(item.updated_at),item.terminal_reason))
   else:
    prior=self._queue_item_from_row(old)
    if prior.execution_id != item.execution_id or prior.position != item.position or prior.created_at != item.created_at: raise PersistenceConflictError('queue item identity is immutable')
    if item.updated_at < prior.updated_at: raise PersistenceConflictError('queue item timestamp regression')
    allowed={QueueItemState.QUEUED:{QueueItemState.ACTIVE,QueueItemState.REMOVED,QueueItemState.SKIPPED},QueueItemState.ACTIVE:{QueueItemState.FINISHED}}
    if item.state not in allowed.get(prior.state,set()): raise PersistenceConflictError('queue item state conflict')
    if item.state is QueueItemState.FINISHED:
     execution=self.db.execute('SELECT state FROM executions WHERE id=?',(str(item.execution_id),)).fetchone()
     if not execution or execution[0] not in {Lifecycle.SUCCEEDED.value,Lifecycle.FAILED.value,Lifecycle.CANCELLED.value}: raise PersistenceConflictError('finished queue item requires terminal execution')
    self.db.execute('UPDATE queue_items SET state=?,updated_at=?,terminal_reason=? WHERE id=?',(item.state.value,self._queue_time(item.updated_at),item.terminal_reason,str(item.id)))
  except sqlite3.IntegrityError as exc: raise PersistenceConflictError(str(exc)) from exc
  return item
 def list_queue_items(self,*,states=None):
  values=None if states is None else tuple(QueueItemState(s).value for s in states)
  if values == (): return []
  query='SELECT id,execution_id,position,state,created_at,updated_at,terminal_reason FROM queue_items'
  args=()
  if values:
   query+=' WHERE state IN (%s)' % ','.join('?'*len(values)); args=values
  query+=' ORDER BY position,id'
  return [self._queue_item_from_row(row) for row in self.db.execute(query,args)]
 def get_queue_item(self,queue_item_id):
  row=self.db.execute('SELECT id,execution_id,position,state,created_at,updated_at,terminal_reason FROM queue_items WHERE id=?',(str(queue_item_id),)).fetchone()
  return None if row is None else self._queue_item_from_row(row)
 def has_live_queue_item(self,execution_id):
  """Return whether an execution has durable queued/active work, or fail closed."""
  try: rows=self.db.execute('SELECT state FROM queue_items WHERE execution_id=?',(str(execution_id),)).fetchall()
  except sqlite3.DatabaseError as exc: raise PersistenceDataError('queue state read failed') from exc
  try: return any(QueueItemState(row[0]) in {QueueItemState.QUEUED,QueueItemState.ACTIVE} for row in rows)
  except (TypeError, ValueError) as exc: raise PersistenceDataError('invalid queue item state') from exc
 def get_queue_control(self):
  row=self.db.execute('SELECT paused,active_queue_item_id,revision FROM queue_control WHERE singleton=1').fetchone()
  if row is None: raise PersistenceDataError('missing queue control')
  if row[1] is not None:
    item=self.db.execute('SELECT state FROM queue_items WHERE id=?',(row[1],)).fetchone()
    if not item or item[0] != QueueItemState.ACTIVE.value: raise PersistenceDataError('queue control active item is not active')
  try:return QueueControl(bool(row[0]),QueueItemId(row[1]) if row[1] is not None else None,row[2])
  except Exception as exc: raise PersistenceDataError('invalid queue control') from exc
 def save_queue_control(self,control):
  if not isinstance(control,QueueControl): raise PersistenceDataError('invalid queue control')
  if control.active_queue_item_id is not None:
   row=self.db.execute('SELECT state FROM queue_items WHERE id=?',(str(control.active_queue_item_id),)).fetchone()
   if not row or row[0] != QueueItemState.ACTIVE.value: raise PersistenceConflictError('queue control active item is not active')
  try:self.db.execute('UPDATE queue_control SET paused=?,active_queue_item_id=?,revision=? WHERE singleton=1',(int(control.paused),str(control.active_queue_item_id) if control.active_queue_item_id else None,control.revision))
  except sqlite3.IntegrityError as exc: raise PersistenceConflictError(str(exc)) from exc
  return control
 def save(self,p,es,artifacts=(),errors=(),transitions=(),*,allow_retry_reopen=False,_in_transaction=False):
  try:
   owners={str(a.id):(e,c) for e in es for c in e.chunks for a in c.attempts}
   for ar in artifacts:
    own=owners.get(str(ar.attempt_id))
    if ar.project_id!=p.id or not own or str(own[0].id)!=str(ar.execution_id) or str(own[1].id)!=str(ar.chunk_id): raise PersistenceDataError('artifact provenance')
    old=self.db.execute('SELECT phase,output FROM artifacts WHERE id=?',(str(ar.id),)).fetchone()
    if old and old!=(ar.phase.value,ar.output.uri): raise PersistenceConflictError('immutable artifact conflict')
   if not _in_transaction: self.db.execute('BEGIN')
   self.db.execute('INSERT INTO projects VALUES(?,?) ON CONFLICT(id) DO UPDATE SET defaults=excluded.defaults',(str(p.id),_json(dict(p.defaults))))
   for e in es:
    prof=e.workflow_profile_ref.value if e.workflow_profile_ref else None; old=self.db.execute('SELECT state,workflow_profile_ref,execution_number FROM executions WHERE id=?',(str(e.id),)).fetchone()
    if old and (not _legal(Lifecycle(old[0]),e.state,allow_retry_reopen=allow_retry_reopen) or old[1]!=prof):raise PersistenceConflictError('execution lifecycle/profile conflict')
    if old:
     e.execution_number=old[2]
    elif e.execution_number is None:
     e.execution_number=self.db.execute('SELECT COALESCE(MAX(execution_number),0)+1 FROM executions WHERE project_id=?',(str(p.id),)).fetchone()[0]
    self.db.execute('INSERT INTO executions(id,project_id,defaults,state,workflow_profile_ref,execution_number) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET defaults=excluded.defaults,state=excluded.state,workflow_profile_ref=excluded.workflow_profile_ref',(str(e.id),str(p.id),_json(dict(e.defaults)),e.state.value,prof,e.execution_number))
    # Generic save never infers deletion from an incomplete aggregate.
    ids=[str(c.id) for c in e.chunks]
    if ids:
     # Partial aggregates may only rewrite their own rows; never steal an
     # ordinal belonging to an omitted historical chunk.
     occupied={r[0] for r in self.db.execute('SELECT ord FROM chunks WHERE execution_id=? AND id NOT IN (%s)' % ','.join('?'*len(ids)), (str(e.id), *ids))}
     if any(c.order in occupied for c in e.chunks): raise PersistenceConflictError('partial sequence ordinal collision')
     self.db.execute('UPDATE chunks SET ord=ord+1000000 WHERE execution_id=? AND id IN (%s)' % ','.join('?'*len(ids)), (str(e.id), *ids))
    for c in e.chunks:
     if str(c.execution_id) != str(e.id): raise PersistenceConflictError('chunk execution ownership mismatch')
     existing=self.db.execute('SELECT execution_id FROM chunks WHERE id=?',(str(c.id),)).fetchone()
     if existing and existing[0] != str(e.id): raise PersistenceConflictError('chunk id belongs to another execution')
     self.db.execute('INSERT INTO chunks VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET ord=excluded.ord,defaults=excluded.defaults,state=excluded.state',(str(c.id),str(e.id),c.order,_json(dict(c.defaults)),c.state.value))
     for a in c.attempts:
      old_attempt=self.db.execute('SELECT state,external_job_ref FROM attempts WHERE id=?',(str(a.id),)).fetchone()
      if old_attempt and Lifecycle(old_attempt[0]) is Lifecycle.FAILED and a.state in {Lifecycle.RUNNING,Lifecycle.PENDING}:
       raise PersistenceConflictError('attempt lifecycle conflict')
      oldref=old_attempt[1] if old_attempt else None
      if oldref and a.external_job_ref and oldref!=str(a.external_job_ref): raise PersistenceConflictError('backend job reference conflict')
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
    m=getattr(t,'materialized_ref',None)
    self.db.execute('INSERT OR REPLACE INTO transitions(project_id,execution_id,target_chunk_id,source_chunk_id,source_attempt_id,source_output,frame_index,frame_count,materialized_type,materialized_subfolder,materialized_name,materialized_source_sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(str(t.project_id),str(t.execution_id),str(t.target_chunk_id) if t.target_chunk_id is not None else None,str(t.source_chunk_id),str(t.source_attempt_id),t.source_output.uri,t.source_frame_index,t.frame_count, getattr(m,'type',None),getattr(m,'subfolder',None),getattr(m,'name',None),getattr(m,'source_sha256',None)))
   if not _in_transaction: self.db.execute('COMMIT')
  except PersistenceError:
   if self.db.in_transaction and not _in_transaction:self.db.execute('ROLLBACK')
   raise
  except Exception as e:
   if self.db.in_transaction and not _in_transaction:self.db.execute('ROLLBACK')
   raise PersistenceError(str(e))
 def save_preparation_sequence(self, project, execution, *, allow_retry_reopen=False):
  eid=str(execution.id); self.db.execute('BEGIN')
  try:
   row=self.db.execute('SELECT state FROM executions WHERE id=?',(eid,)).fetchone()
   if row and Lifecycle(row[0]) is not Lifecycle.PENDING: raise PersistenceConflictError('preparation sequence is not virgin')
   # This is the durable half of the draft gate.  The application checks the
   # same condition before it builds a replacement sequence; checking again
   # inside this transaction prevents a queued execution from being edited by
   # a concurrent caller.
   if self.db.execute("SELECT 1 FROM queue_items WHERE execution_id=? AND state IN ('queued','active')",(eid,)).fetchone(): raise PersistenceConflictError('preparation sequence has live queue item')
   if self.db.execute('SELECT 1 FROM transitions WHERE execution_id=?',(eid,)).fetchone(): raise PersistenceConflictError('preparation sequence has transitions')
   if self.db.execute('SELECT 1 FROM chunks WHERE execution_id=? AND state<>?',(eid,Lifecycle.PENDING.value)).fetchone(): raise PersistenceConflictError('preparation sequence has non-pending chunk')
   if self.db.execute('SELECT 1 FROM attempts a JOIN chunks c ON c.id=a.chunk_id WHERE c.execution_id=?',(eid,)).fetchone(): raise PersistenceConflictError('preparation sequence has attempts')
   if self.db.execute('SELECT 1 FROM artifacts WHERE execution_id=?',(eid,)).fetchone() or self.db.execute('SELECT 1 FROM errors WHERE execution_id=?',(eid,)).fetchone(): raise PersistenceConflictError('preparation sequence has artifacts or errors')
   # Inline generic persistence while retaining transaction ownership.
   self.db.execute('UPDATE chunks SET ord=ord+1000000 WHERE execution_id=?',(eid,))
   self.save(project,[execution],allow_retry_reopen=allow_retry_reopen,_in_transaction=True)
   keep={str(c.id) for c in execution.chunks}
   for (cid,) in self.db.execute('SELECT id FROM chunks WHERE execution_id=?',(eid,)).fetchall():
    if cid not in keep: self.db.execute('DELETE FROM chunks WHERE id=?',(cid,))
   self.db.execute('COMMIT')
  except Exception:
   if self.db.in_transaction:self.db.execute('ROLLBACK')
   raise
 def load(self,pid):
  row=self.db.execute('SELECT defaults FROM projects WHERE id=?',(str(pid),)).fetchone()
  if not row:raise PersistenceError('project not found')
  p=Project(ProjectId(str(pid)),json.loads(row[0])); es=[]; cm={}; am={}
  for eid,d,s,w,n in self.db.execute('SELECT id,defaults,state,workflow_profile_ref,execution_number FROM executions WHERE project_id=? ORDER BY execution_number',(str(pid),)):
   e=Execution(p.id,ExecutionId(eid),json.loads(d),Lifecycle(s),[],WorkflowProfileRef(w) if w else None,execution_number=n); es.append(e)
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
  for erid,pr,ex,ch,at,code,msg in self.db.execute('SELECT id,project_id,execution_id,chunk_id,attempt_id,code,message FROM errors WHERE project_id=?',(str(pid),)):
   own=am.get(at)
   if pr!=str(pid) or not own or own[0].id.value!=ex or own[1].id.value!=ch: raise PersistenceDataError('error ownership mismatch')
  arts={}
  for aid,pr,ex,ch,at,ph,out in self.db.execute('SELECT id,project_id,execution_id,chunk_id,attempt_id,phase,output FROM artifacts WHERE project_id=?',(str(pid),)):
   own=am.get(at)
   if pr!=str(pid) or not own or own[0].id.value!=ex or own[1].id.value!=ch or own[2].output is None or own[2].output.uri!=out:raise PersistenceDataError('artifact ownership mismatch')
   own[0].artifacts.append(Artifact(ProjectId(pr),ExecutionId(ex),ChunkId(ch),AttemptId(at),Phase(ph),OutputRef(out),ArtifactId(aid)))
   arts[aid]=own
  for aid,_,_,_,_,_,_,oaid in self.db.execute('SELECT a.id,a.chunk_id,a.number,a.state,a.output,a.evidence,a.error_id,a.output_artifact_id FROM attempts a JOIN chunks c ON c.id=a.chunk_id JOIN executions e ON e.id=c.execution_id WHERE e.project_id=?',(str(pid),)):
   if oaid:
    own=am.get(aid); ar=arts.get(oaid)
    if not ar or ar is not own: raise PersistenceDataError('attempt artifact ownership mismatch')
  for pr,ex,tgt,src,sa,out,idx,count,mtype,msub,mname,msha in self.db.execute('SELECT project_id,execution_id,target_chunk_id,source_chunk_id,source_attempt_id,source_output,frame_index,frame_count,materialized_type,materialized_subfolder,materialized_name,materialized_source_sha256 FROM transitions WHERE project_id=?',(str(pid),)):
   if pr!=str(pid) or src not in cm or ex!=cm[src][0].id.value:raise PersistenceDataError('transition ownership')
   _,sc=cm[src]; own=am.get(sa)
   if tgt is not None:
    if tgt not in cm or ex!=cm[tgt][0].id.value: raise PersistenceDataError('transition ownership')
    _,tc=cm[tgt]
    if tc.order!=sc.order+1: raise PersistenceDataError('invalid transition provenance')
   if not own or own[1].id.value!=src or own[2].output is None or own[2].output.uri!=out or idx<0 or (count is not None and idx!=count-1):raise PersistenceDataError('invalid transition provenance')
   vals=(mtype,msub,mname,msha)
   if all(v is None for v in vals): mref=None
   elif any(v is None for v in vals): raise PersistenceDataError('partial materialized reference')
   else:
    try: mref=MaterializedInputRef(mtype,msub,mname,msha)
    except Exception as exc: raise PersistenceDataError('invalid materialized reference') from exc
   if tgt is not None: tc.first_frame=TransitionFrame(ProjectId(pr),ExecutionId(ex),ChunkId(src),AttemptId(sa),OutputRef(out),idx,count,ChunkId(tgt),mref)
  return p,es
 def list_project_ids(self):
  """Return durable project identities only; product classification lives in application."""
  return [ProjectId(row[0]) for row in self.db.execute('SELECT id FROM projects ORDER BY id')]
 def load_transitions(self, execution_id):
  """Read durable transition frames without exposing storage details to application code."""
  rows=self.db.execute('SELECT project_id,execution_id,target_chunk_id,source_chunk_id,source_attempt_id,source_output,frame_index,frame_count,materialized_type,materialized_subfolder,materialized_name,materialized_source_sha256 FROM transitions WHERE execution_id=? ORDER BY frame_index',(str(execution_id),)).fetchall()
  result=[]
  for pr,ex,tgt,src,sa,out,idx,count,mtype,msub,mname,msha in rows:
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
   vals=(mtype,msub,mname,msha)
   if all(v is None for v in vals): mref=None
   elif any(v is None for v in vals): raise PersistenceDataError('partial materialized reference')
   else:
    try: mref=MaterializedInputRef(mtype,msub,mname,msha)
    except Exception as exc: raise PersistenceDataError('invalid materialized reference') from exc
   result.append(TransitionFrame(ProjectId(pr),ExecutionId(ex),ChunkId(src),AttemptId(sa),OutputRef(out),idx,count,ChunkId(tgt) if tgt is not None else None,mref))
  return result
