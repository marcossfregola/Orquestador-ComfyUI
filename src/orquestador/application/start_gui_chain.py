from pathlib import Path
import hashlib
from ..profiles.minimax_h3 import H3_PROFILE,load_api_template,bind_inputs,rebind_first_frame,configure_fast_e2e
class StartPreparationError(ValueError): pass

def _effective_upload_ref(value):
 if not isinstance(value,dict) or value.get('type')!='input' or not isinstance(value.get('name'),str) or not value['name'].strip() or not isinstance(value.get('subfolder',''),str): raise StartPreparationError('static upload response is malformed')
 sub=value.get('subfolder','').strip().strip('/')
 name=value['name'].strip()
 if not name or any(x in name for x in ('/','\\')) or '..' in name.split('/') or ':' in name or any(x in sub for x in ('\\',':')) or '..' in sub.split('/'):
  raise StartPreparationError('static upload response is unsafe')
 return (sub+'/' if sub else '')+name

class StaticInputMaterializer:
 def __init__(self, client, root): self.client,self.root=client,Path(root).resolve()
 def __call__(self, paths):
  out=[]
  for i,raw in enumerate(paths):
   if not isinstance(raw,str) or Path(raw).is_absolute(): raise StartPreparationError('prepared static path is invalid')
   p=(self.root/raw).resolve()
   if not p.is_relative_to(self.root) or not p.is_file(): raise StartPreparationError('prepared static file is missing')
   digest=hashlib.sha256(p.read_bytes()).hexdigest()[:16]
   # Preserve the source image suffix so ComfyUI receives a truthful MIME
   # type/filename (the initial asset is PNG while references are JPEG).
   suffix=p.suffix.lower() if p.suffix else '.png'
   requested=f"{'initial' if i==0 else f'ref-{i}'}-{digest}{suffix}"
   try: value=self.client.upload_image(p,subfolder='orquestador/static',overwrite=False,requested_filename=requested)
   except Exception as exc: raise StartPreparationError(f'static upload failed: {exc}') from exc
   out.append(_effective_upload_ref(value))
  return out
class StartGuiChainUseCase:
 def __init__(self,repository,root,chain,template=None,materializer=None,transition_materializer=None): self.repository,self.root,self.chain,self.template,self.materializer,self.transition_materializer=repository,Path(root).resolve(),chain,template,materializer,transition_materializer
 def __call__(self,project_id,execution_id,prompts=None,initial_image=None,references=None,fast_e2e=False,**_):
  if type(fast_e2e) is not bool: raise StartPreparationError('fast_e2e must be a boolean')
  try:p,es=self.repository.load(project_id)
  except Exception as e: raise StartPreparationError(f'project load failed: {e}') from e
  ms=[e for e in es if str(e.id)==str(execution_id)]
  if len(ms)!=1: raise StartPreparationError('execution selection is missing or ambiguous')
  e=ms[0]; d=dict(e.defaults)
  if e.workflow_profile_ref is None or e.workflow_profile_ref.value!=H3_PROFILE.name: raise StartPreparationError('execution is not prepared for minimax-h3-ui')
  ps=list(prompts if prompts is not None else d.get('prompts',[])); refs=list(references if references is not None else d.get('references',[])); image=d.get('initial_image') if initial_image is None else initial_image
  if len(e.chunks) not in (2,3) or len(ps)!=len(e.chunks) or any(not isinstance(x,str) or not x.strip() for x in ps): raise StartPreparationError('prompt count/order invalid')
  if initial_image is not None and (not isinstance(initial_image,str) or not initial_image.strip()): raise StartPreparationError('initial image override must be nonblank')
  if len(refs)!=6: raise StartPreparationError('exactly six H3 references are required')
  if initial_image is not None and image != d.get('initial_image'): raise StartPreparationError('initial image override is not a prepared durable path')
  if references is not None and refs != list(d.get('references',[])): raise StartPreparationError('references must match prepared durable paths')
  paths=[image,*refs]
  if any(not isinstance(x,str) or Path(x).is_absolute() or not (self.root/x).resolve().is_relative_to(self.root) or not (self.root/x).is_file() for x in paths): raise StartPreparationError('prepared image/reference file is missing or invalid')
  if self.materializer is not None:
   try: materialized=list(self.materializer(paths))
   except StartPreparationError: raise
   except Exception as exc: raise StartPreparationError(f'static upload failed: {exc}') from exc
   if len(materialized)!=7 or any(not isinstance(x,str) or not x for x in materialized): raise StartPreparationError('static materialization is incomplete')
   image,refs=materialized[0],materialized[1:]
  t=load_api_template(self.template)
  if fast_e2e: t=configure_fast_e2e(t)
  bound=[bind_inputs(t,prompt=q,first_frame=image if i==0 else None,references=refs) for i,q in enumerate(ps)]
  return self.chain.run(p,e,bound,transition_rebinder=rebind_first_frame,transition_materializer=self.transition_materializer)
