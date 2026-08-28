from dataclasses import dataclass,field
from enum import Enum
from types import MappingProxyType
from typing import Any,Mapping
from uuid import uuid4
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
  v=str(self.value).strip()
  if not v: raise DomainError('backend job reference must be nonblank')
  object.__setattr__(self,'value',v)
 def __str__(self): return self.value
class Lifecycle(str,Enum): PENDING='pending'; RUNNING='running'; SUCCEEDED='succeeded'; FAILED='failed'; CANCELLED='cancelled'; UNKNOWN='unknown'
class Phase(str,Enum): PREPARE='prepare'; EXECUTE='execute'; ASSEMBLE='assemble'; OUTPUT='output'
@dataclass(frozen=True)
class InputRef: uri:str
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
 def effective_parameters(self,project,execution_defaults): return _map({**project.defaults,**dict(execution_defaults),**self.defaults})
@dataclass
class Execution:
 project_id:ProjectId; id:ExecutionId=_uid(ExecutionId); defaults:Mapping[str,Any]=field(default_factory=dict); state:Lifecycle=Lifecycle.PENDING; chunks:list[Chunk]=field(default_factory=list); workflow_profile_ref:WorkflowProfileRef|None=None; artifacts:list[Artifact]=field(default_factory=list); errors:list[ErrorRecord]=field(default_factory=list)
 def __post_init__(self): self.defaults=_map(self.defaults)
 def add_chunk(self,chunk):
  if chunk.execution_id not in (None,self.id): raise DomainError('chunk belongs to another execution')
  if chunk.order!=len(self.chunks): raise DomainError('chunk orders must be contiguous and zero-based')
  chunk.execution_id=self.id; self.chunks.append(chunk)
 def transition(self,target):
  allowed={Lifecycle.PENDING:{Lifecycle.RUNNING,Lifecycle.CANCELLED},Lifecycle.RUNNING:{Lifecycle.SUCCEEDED,Lifecycle.FAILED,Lifecycle.CANCELLED}}
  if target not in allowed.get(self.state,set()): raise DomainError(f'illegal execution transition {self.state}->{target}')
  if target is Lifecycle.SUCCEEDED and (not self.chunks or any(c.state is not Lifecycle.SUCCEEDED for c in self.chunks)): raise DomainError('execution requires all chunks succeeded')
  self.state=target
 def link_transition(self,chunk,frame):
  if chunk not in self.chunks or chunk.order==0 or frame.execution_id!=self.id: raise DomainError('invalid transition execution/chunk')
  prev=self.chunks[chunk.order-1]
  if frame.source_chunk_id!=prev.id or not any(a.id==frame.source_attempt_id and a.state is Lifecycle.SUCCEEDED and a.output==frame.source_output for a in prev.attempts): raise DomainError('transition requires immediately previous successful attempt')
  chunk.first_frame=frame
