"""Validated GUI preparation with immutable imports."""
from pathlib import Path
from uuid import uuid4
from hashlib import sha256
from ..domain.core import Project,ProjectId,Execution,ExecutionId,Chunk,WorkflowProfileRef
from ..profiles.minimax_h3 import H3_PROFILE
from ..persistence.sqlite import PersistenceError
class PreparationError(ValueError): pass
class PrepareGuiUseCase:
 def __init__(self,repository,root,snapshot): self.repository,self.root,self.snapshot=repository,Path(root).resolve(),snapshot
 def _src(self,v,label):
  if not isinstance(v,str) or not v.strip(): raise PreparationError(f'{label} is required')
  p=Path(v.strip()); p=p if p.is_absolute() else self.root/p
  try:p=p.resolve(strict=True)
  except (OSError,RuntimeError) as e: raise PreparationError(f'{label} does not exist or is inaccessible') from e
  if not p.is_file(): raise PreparationError(f'{label} must be a file')
  try:d=p.read_bytes()
  except OSError as e: raise PreparationError(f'{label} is inaccessible') from e
  return p,d
 def __call__(self,project_id=None,execution_id=None,initial_image=None,prompts=None,references=None,chunk_count=None,**_):
  prompts=list(prompts or []); refs=list(references or []); n=len(prompts) if chunk_count is None else chunk_count
  if type(n) is not int or n not in (2,3): raise PreparationError('chunk count must be two or three')
  if len(prompts)!=n or any(not isinstance(x,str) or not x.strip() for x in prompts): raise PreparationError('one nonblank prompt is required per chunk')
  if len(refs)!=6: raise PreparationError('exactly six H3 references are required')
  src=[self._src(initial_image,'initial image')]+[self._src(x,f'reference slot {i}') for i,x in enumerate(refs)]
  rel=[]
  for p,d in src:
   base=(Path('inputs')/p.name).as_posix(); t=self.root/base
   try: conflict = t.exists() and (not t.is_file() or t.read_bytes()!=d)
   except OSError as e: raise PreparationError(f'collision check failed for {base}') from e
   if conflict: base=(Path('inputs')/(sha256(d).hexdigest()+'_'+p.name)).as_posix()
   rel.append(base)
  for r,(_,d) in zip(rel,src):
   t=self.root/r
   try: conflict = t.exists() and (not t.is_file() or t.read_bytes()!=d)
   except OSError as e: raise PreparationError(f'destination check failed for {r}') from e
   if conflict: raise PreparationError(f'import collision for {r}')
  pid=ProjectId(project_id.strip()) if isinstance(project_id,str) and project_id.strip() else ProjectId(str(uuid4())); eid=ExecutionId(execution_id.strip()) if isinstance(execution_id,str) and execution_id.strip() else ExecutionId(str(uuid4()))
  try:p,es=self.repository.load(pid)
  except PersistenceError as e:
   # Only the repository's explicit not-found contract permits creation.
   # Corruption, schema, I/O and all other persistence failures fail closed.
   if str(e).strip().lower() != 'project not found':
    raise PreparationError(f'project load failed: {e}') from e
   p,es=Project(pid),[]
  ms=[e for e in es if str(e.id)==str(eid)]
  if len(ms)>1: raise PreparationError('execution selection is ambiguous')
  defaults={'initial_image':rel[0],'prompts':prompts,'references':rel[1:]}
  if ms:
   e=ms[0]
   if e.project_id!=p.id or e.workflow_profile_ref is None or e.workflow_profile_ref.value!=H3_PROFILE.name or dict(e.defaults)!=defaults or len(e.chunks)!=n: raise PreparationError('existing execution conflicts with preparation')
  else:
   e=Execution(p.id,eid,defaults=defaults,workflow_profile_ref=WorkflowProfileRef(H3_PROFILE.name))
   for i in range(n): e.add_chunk(Chunk(order=i))
  made=[]; made_dirs=[]
  try:
   for r,(_,d) in zip(rel,src):
    t=self.root/r
    if not t.exists():
     missing=[]; parent=t.parent
     while parent != self.root and not parent.exists(): missing.append(parent); parent=parent.parent
     t.parent.mkdir(parents=True,exist_ok=True); made_dirs.extend(missing); t.write_bytes(d); made.append(t)
   if not ms:self.repository.save(p,[*es,e])
  except Exception as exc:
   for t in made:
    try:t.unlink()
    except OSError: pass
   for parent in sorted(set(made_dirs), key=lambda p: len(p.parts), reverse=True):
    try:
     if parent != self.root and parent.exists() and not any(parent.iterdir()): parent.rmdir()
    except OSError: pass
   if isinstance(exc, PersistenceError): raise PreparationError(f'persistence save failed: {exc}') from exc
   raise PreparationError(f'import failed: {exc}') from exc
  return self.snapshot(str(p.id),str(e.id))
