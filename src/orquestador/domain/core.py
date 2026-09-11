from dataclasses import dataclass,field
from enum import Enum
from types import MappingProxyType
from typing import Any,Mapping
from uuid import uuid4
import re, os
class DomainError(ValueError): pass
@dataclass(frozen=True)
class EntityId:
 value:str
 def __post_init__(self):
  v=str(self.value).strip()
  if not v: raise DomainError('identifier must be nonblank')
  object.__setattr__(self,'value',v)
 def __str__(self): return self.value
class ProjectId(EntityId): pass
class ExecutionId(EntityId): pass
class ChunkId(EntityId): pass
class AttemptId(EntityId): pass
class ArtifactId(EntityId): pass
class ErrorId(EntityId): pass
@dataclass(frozen=True)
class BackendJobRef:
 value:str
 def __post_init__(self):
  if not isinstance(self.value,str): raise DomainError('backend job reference must be a string')
  v=self.value.strip()
  if not v: raise DomainError('backend job reference must be nonblank')
  object.__setattr__(self,'value',v)
 def __str__(self): return self.value
class Lifecycle(str,Enum): PENDING='pending'; RUNNING='running'; SUCCEEDED='succeeded'; FAILED='failed'; CANCELLED='cancelled'; UNKNOWN='unknown'
class Phase(str,Enum): PREPARE='prepare'; EXECUTE='execute'; ASSEMBLE='assemble'; OUTPUT='output'
@dataclass(frozen=True)
class InputRef: uri:str
@dataclass(frozen=True)
class MaterializedInputRef:
 type:str; subfolder:str; name:str; source_sha256:str
 def __post_init__(self):
  if self.type != 'input': raise DomainError('materialized ref type must be input')
  if not isinstance(self.name,str) or not self.name or self.name in {'.','..'} or '/' in self.name or '\\' in self.name or os.path.isabs(self.name) or os.path.splitdrive(self.name)[0] or any(ord(c)<32 or ord(c)==127 for c in self.name): raise DomainError('invalid materialized name')
  if not isinstance(self.subfolder,str) or self.subfolder.startswith(('/','\\')) or os.path.isabs(self.subfolder) or os.path.splitdrive(self.subfolder)[0] or '\\' in self.subfolder or any(x in {'','..'} for x in self.subfolder.split('/')): raise DomainError('invalid materialized subfolder')
  if not isinstance(self.source_sha256,str) or not re.fullmatch(r'[0-9a-fA-F]{64}', self.source_sha256): raise DomainError('invalid source sha256')
  object.__setattr__(self,'source_sha256',self.source_sha256.lower())
 @property
 def load_image_value(self): return f'{self.subfolder}/{self.name}' if self.subfolder else self.name
@dataclass(frozen=True)
class OutputRef: uri:str
@dataclass(frozen=True)
class WorkflowProfileRef: value:str
@dataclass(frozen=True)
class Evidence: detail:str
@dataclass(frozen=True)
class ErrorRecord: code:str; message:str; id:ErrorId=field(default_factory=lambda:ErrorId(str(uuid4())))
@dataclass(frozen=True)
class Artifact:
 project_id:ProjectId; execution_id:ExecutionId; chunk_id:ChunkId; attempt_id:AttemptId; phase:Phase; output:OutputRef; id:ArtifactId=field(default_factory=lambda:ArtifactId(str(uuid4())))
@dataclass(frozen=True)
class TransitionFrame:
 project_id:ProjectId; execution_id:ExecutionId; source_chunk_id:ChunkId; source_attempt_id:AttemptId; source_output:OutputRef; source_frame_index:int; frame_count:int|None=None
 target_chunk_id:ChunkId|None=None
 materialized_ref:MaterializedInputRef|None=None
 def __post_init__(self):
  if self.source_frame_index<0 or (self.frame_count is not None and (self.frame_count<=0 or self.source_frame_index!=self.frame_count-1)): raise DomainError('transition frame must be source frame N-1')
def _map(v): return MappingProxyType(dict(v))
def _uid(c): return field(default_factory=lambda:c(str(uuid4())))
@dataclass
class Project:
 id:ProjectId=_uid(ProjectId); defaults:Mapping[str,Any]=field(default_factory=dict)
 def __post_init__(self): self.defaults=_map(self.defaults)
@dataclass
class Attempt:
 id:AttemptId=_uid(AttemptId); number:int=1; state:Lifecycle=Lifecycle.PENDING; output:OutputRef|None=None; evidence:Evidence|None=None; error:ErrorRecord|None=None; external_job_ref:BackendJobRef|None=None
 def assign_external_job_ref(self, ref:BackendJobRef):
  if not isinstance(ref, BackendJobRef): raise DomainError('invalid backend job reference')
  if self.external_job_ref is not None and self.external_job_ref != ref: raise DomainError('backend job reference conflict')
  self.external_job_ref = ref
 def transition(self,target,*,output=None,evidence=None,error=None):
  allowed={Lifecycle.PENDING:{Lifecycle.RUNNING,Lifecycle.CANCELLED},Lifecycle.RUNNING:{Lifecycle.SUCCEEDED,Lifecycle.FAILED,Lifecycle.CANCELLED}}
  if target not in allowed.get(self.state,set()): raise DomainError(f'illegal attempt transition {self.state}->{target}')
  if target is Lifecycle.SUCCEEDED and (output is None or evidence is None): raise DomainError('success requires output and evidence')
  self.state=target
  if output is not None:self.output=output
  if evidence is not None:self.evidence=evidence
  if error is not None:self.error=error
 def retire_stale_not_found(self, error):
  """Narrow terminal transition for a bound job proven absent from history."""
  if self.state not in {Lifecycle.PENDING, Lifecycle.RUNNING} or self.external_job_ref is None:
   raise DomainError('stale retirement requires a bound pending or running attempt')
  self.state = Lifecycle.FAILED
  self.error = error
@dataclass
class Chunk:
 id:ChunkId=_uid(ChunkId); order:int=0; execution_id:ExecutionId|None=None; defaults:Mapping[str,Any]=field(default_factory=dict); state:Lifecycle=Lifecycle.PENDING; attempts:list[Attempt]=field(default_factory=list); first_frame:TransitionFrame|None=None
 def __post_init__(self):
  if self.order<0: raise DomainError('chunk order must be non-negative')
  self.defaults=_map(self.defaults)
 def new_attempt(self):
  if self.attempts and self.attempts[-1].state not in {Lifecycle.SUCCEEDED,Lifecycle.FAILED,Lifecycle.CANCELLED}: raise DomainError('latest attempt is nonterminal')
  a=Attempt(number=len(self.attempts)+1); self.attempts.append(a); return a
 def transition(self,target):
  allowed={Lifecycle.PENDING:{Lifecycle.RUNNING,Lifecycle.CANCELLED},Lifecycle.RUNNING:{Lifecycle.SUCCEEDED,Lifecycle.FAILED,Lifecycle.CANCELLED}}
  if target not in allowed.get(self.state,set()): raise DomainError(f'illegal chunk transition {self.state}->{target}')
  if target is Lifecycle.SUCCEEDED and not any(a.state is Lifecycle.SUCCEEDED and a.output and a.evidence for a in self.attempts): raise DomainError('chunk success requires successful attempt evidence')
  self.state=target
 def reopen_for_retry(self):
  """Explicitly re-enter execution for an already-bound retry attempt."""
  if self.state is not Lifecycle.FAILED or len(self.attempts) != 2:
   raise DomainError('retry reopening requires a failed chunk with exactly two attempts')
  first, latest = self.attempts
  if first.number != 1 or latest.number != 2 or first.state is not Lifecycle.FAILED:
   raise DomainError('retry reopening requires ordered failed attempts 1 and 2')
  if latest.state is not Lifecycle.PENDING or latest.external_job_ref is None:
   raise DomainError('retry reopening requires a bound pending attempt 2')
  self.state = Lifecycle.PENDING
 def retire_stale_not_found(self):
  """Retire a stale chunk after its bound attempt was explicitly retired."""
  if self.state not in {Lifecycle.PENDING, Lifecycle.RUNNING}:
   raise DomainError('stale retirement requires a pending or running chunk')
  self.state = Lifecycle.FAILED
 def effective_parameters(self,project,execution_defaults): return _map({**project.defaults,**dict(execution_defaults),**self.defaults})
@dataclass
class Execution:
 project_id:ProjectId; id:ExecutionId=_uid(ExecutionId); defaults:Mapping[str,Any]=field(default_factory=dict); state:Lifecycle=Lifecycle.PENDING; chunks:list[Chunk]=field(default_factory=list); workflow_profile_ref:WorkflowProfileRef|None=None; artifacts:list[Artifact]=field(default_factory=list); errors:list[ErrorRecord]=field(default_factory=list)
 def __post_init__(self): self.defaults=_map(self.defaults)
 def add_chunk(self,chunk):
  if chunk.execution_id not in (None,self.id): raise DomainError('chunk belongs to another execution')
  if chunk.order!=len(self.chunks): raise DomainError('chunk orders must be contiguous and zero-based')
  chunk.execution_id=self.id; self.chunks.append(chunk)
 def _editable(self):
  if self.artifacts or self.errors or self.state is not Lifecycle.PENDING or any(c.attempts or c.first_frame is not None or c.state is not Lifecycle.PENDING for c in self.chunks):
   raise DomainError('chunk sequence is locked after runtime evidence')
 def reorder_chunks(self, order):
  self._editable(); ids=list(order)
  if len(ids)!=len(self.chunks) or set(map(str,ids))!={str(c.id) for c in self.chunks}: raise DomainError('invalid chunk order')
  by={str(c.id):c for c in self.chunks}; self.chunks=[by[str(i)] for i in ids]
  for n,c in enumerate(self.chunks): c.order=n
 def duplicate_chunk(self, chunk_id):
  self._editable(); src=next((c for c in self.chunks if str(c.id)==str(chunk_id)),None)
  if src is None: raise DomainError('chunk not found')
  copy=Chunk(order=src.order+1, execution_id=self.id, defaults=dict(src.defaults)); self.chunks.insert(src.order+1,copy)
  for n,c in enumerate(self.chunks): c.order=n
  return copy
 def remove_chunk(self, chunk_id):
  self._editable()
  if len(self.chunks)<=2: raise DomainError('minimum two chunks required')
  before=len(self.chunks); self.chunks=[c for c in self.chunks if str(c.id)!=str(chunk_id)]
  if len(self.chunks)==before: raise DomainError('chunk not found')
  for n,c in enumerate(self.chunks): c.order=n
 def transition(self,target):
  allowed={Lifecycle.PENDING:{Lifecycle.RUNNING,Lifecycle.CANCELLED},Lifecycle.RUNNING:{Lifecycle.SUCCEEDED,Lifecycle.FAILED,Lifecycle.CANCELLED}}
  if target not in allowed.get(self.state,set()): raise DomainError(f'illegal execution transition {self.state}->{target}')
  if target is Lifecycle.SUCCEEDED and (not self.chunks or any(c.state is not Lifecycle.SUCCEEDED for c in self.chunks)): raise DomainError('execution requires all chunks succeeded')
  self.state=target
 def reopen_for_retry(self):
  """Re-enter a durably failed execution for its single bounded retry."""
  if self.state is not Lifecycle.FAILED:
   raise DomainError('retry reopening requires a failed execution')
  self.state = Lifecycle.RUNNING
 def link_transition(self,chunk,frame):
  if chunk not in self.chunks or chunk.order==0 or frame.execution_id!=self.id: raise DomainError('invalid transition execution/chunk')
  prev=self.chunks[chunk.order-1]
  if frame.source_chunk_id!=prev.id or not any(a.id==frame.source_attempt_id and a.state is Lifecycle.SUCCEEDED and a.output==frame.source_output for a in prev.attempts): raise DomainError('transition requires immediately previous successful attempt')
  chunk.first_frame=frame

ORCHESTRATION_TIMEOUT_DEFAULT_SECONDS = 1800
ORCHESTRATION_TIMEOUT_KEY = 'orchestration_timeout_seconds'

def resolve_orchestration_timeout_seconds(project: Project, execution: Execution, chunk: Chunk) -> int:
 """Resolve and validate the orchestration deadline from effective defaults.

 The effective source precedence is project, execution, then chunk defaults.
 This function is pure and does not mutate any supplied entity or attempt.
 """
 value = chunk.effective_parameters(project, execution.defaults).get(
  ORCHESTRATION_TIMEOUT_KEY, ORCHESTRATION_TIMEOUT_DEFAULT_SECONDS
 )
 if type(value) is not int or value <= 0:
  raise DomainError(
   f'{ORCHESTRATION_TIMEOUT_KEY} must be a positive integer number of seconds'
  )
 return value
