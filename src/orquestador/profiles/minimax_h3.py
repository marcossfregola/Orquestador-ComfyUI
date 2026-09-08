"""Canonical MiniMax H3 UI workflow compatibility contract."""
from dataclasses import dataclass
from types import MappingProxyType
import hashlib,json
from pathlib import Path
from orquestador.domain.workflow_profile import WorkflowProfile
from orquestador.domain.config import validate_parameter, GenerationConfigError
class WorkflowProfileError(ValueError):
 def __init__(self,message,code='workflow.invalid',context=None): super().__init__(message); self.code=code; self.context=MappingProxyType(dict(context or {}))
class MalformedWorkflowError(WorkflowProfileError): pass
class IncompatibleWorkflowError(MalformedWorkflowError): pass
class WorkflowHashMismatchError(IncompatibleWorkflowError): pass
H3_CANONICAL_SHA256='3070EB659A0BDBEB3D8392B0D203F6B4B86409709A20143280473A12C44BA4A7'
H3_API_TEMPLATE_SHA256='4DCFB2783391FBA0C5090B8A78765E46AA26B9A2215B948664F0D20341EC8F25'
H3_PROFILE=WorkflowProfile('minimax-h3-ui','1.0.0')
H3_MAX_RESOLUTION=16384
NO_CROP_BOUNDING_BOX=MappingProxyType({'x':0,'y':0,'width':H3_MAX_RESOLUTION,'height':H3_MAX_RESOLUTION})
# Explicitly opt-in development/test profile.  It is applied to a copied API
# prompt at start time and is never persisted as an execution/user default.
FAST_E2E_CONFIG=MappingProxyType({'length':56,'megapixels':0.09,'steps':4})
_T={92:'SaveVideo',114:'LoadImage',119:'ImageScaleToTotalPixels',120:'GetImageSize',127:'ImageCropV2',129:'MiniMaxH3HybridRefAndKeyframe',136:'CLIPLoader',137:'VAELoader',138:'VAELoader',139:'UNETLoader',142:'BasicGuider',143:'SamplerCustomAdvanced',144:'RandomNoise',145:'KSamplerSelect',146:'BasicScheduler',147:'VAEDecode',148:'CreateVideo',**{i:'LoadImage' for i in(130,131,132,150,151,152)},**{i:'ImageCropV2' for i in(133,134,135,153,154,155)},**{i:'ImageScaleToMaxDimension' for i in range(156,162)}}
H3_NODE_TYPES=MappingProxyType(_T); REQUIRED_REFS=tuple(f'ref_images.ref_image_{i}' for i in range(7))
_API_LINKS=MappingProxyType({'92.video':['148',0],'119.image':['127',0],'120.image':['119',0],'127.image':['114',0],'129.width':['120',0],'129.height':['120',1],'129.clip':['136',0],'129.vae':['137',0],'129.audio_vae':['138',0],'129.first_frame':['119',0],**{f'129.ref_images.ref_image_{i}':[str(x),0] for i,x in enumerate((156,157,158,159,161,160))},'133.image':['130',0],'134.image':['131',0],'135.image':['132',0],'142.model':['139',0],'142.conditioning':['129',0],'143.noise':['144',0],'143.guider':['142',0],'143.sampler':['145',0],'143.sigmas':['146',0],'143.latent_image':['129',1],'146.model':['139',0],'147.samples':['143',0],'147.vae':['137',0],'148.images':['147',0],'153.image':['150',0],'154.image':['151',0],'155.image':['152',0],'156.image':['133',0],'157.image':['134',0],'158.image':['135',0],'159.image':['153',0],'160.image':['155',0],'161.image':['154',0]})
H3_BINDINGS=MappingProxyType({'prompt':(129,'prompt'),'first_frame':(114,'image'),'megapixels':(119,'megapixels'),'steps':(146,'steps'),'width':(129,'width'),'height':(129,'height'),'length':(129,'length'),'ref_image_size':(129,'ref_image_size'),'also_ref_first_frame':(129,'also_ref_first_frame'),'fps':(148,'fps'),'output':(92,'video'),'ref_images':tuple((n,'image') for n in (130,131,132,150,151,152))})
_L=((314,114,0,127,0,'IMAGE'),(315,127,0,119,0,'IMAGE'),(251,119,0,120,0,'IMAGE'),(259,119,0,129,3,'IMAGE'),(263,120,0,129,15,'INT'),(264,120,1,129,16,'INT'),(301,133,0,156,0,'IMAGE'),(302,156,0,129,5,'IMAGE'),(303,134,0,157,0,'IMAGE'),(304,157,0,129,6,'IMAGE'),(305,135,0,158,0,'IMAGE'),(306,158,0,129,7,'IMAGE'),(307,153,0,159,0,'IMAGE'),(310,159,0,129,8,'IMAGE'),(308,154,0,161,0,'IMAGE'),(311,161,0,129,9,'IMAGE'),(309,155,0,160,0,'IMAGE'),(312,160,0,129,10,'IMAGE'),(271,136,0,129,0,'CLIP'),(275,137,0,129,1,'VAE'),(274,138,0,129,2,'VAE'),(281,139,0,142,0,'MODEL'),(282,129,0,142,1,'CONDITIONING'),(283,142,0,143,1,'GUIDER'),(284,144,0,143,0,'NOISE'),(285,145,0,143,2,'SAMPLER'),(286,139,0,146,0,'MODEL'),(287,146,0,143,3,'SIGMAS'),(288,129,1,143,4,'LATENT'),(289,143,0,147,0,'LATENT'),(291,137,0,147,1,'VAE'),(292,147,0,148,0,'IMAGE'),(293,148,0,92,0,'VIDEO'))
@dataclass(frozen=True,slots=True)
class CompatibilityReport: profile:WorkflowProfile; sha256:str; node_ids:tuple; link_ids:tuple
def validate_ui_workflow_structure(mapping, *, verified_sha256=H3_CANONICAL_SHA256):
 """Validate parsed UI workflow structure; ``verified_sha256`` is provenance only.

 This function does not establish canonical raw-byte identity. Use
 :func:`validate_static_compatibility` for production trust-boundary checks.
 """
 d=mapping
 if not isinstance(d,dict): raise MalformedWorkflowError('workflow mapping required','workflow.top_level')
 if not isinstance(d.get('nodes'),list) or not isinstance(d.get('links'),list): raise MalformedWorkflowError('nodes/links must be lists','workflow.collections')
 digest=str(verified_sha256).upper()
 ns={}
 for n in d['nodes']:
  if not isinstance(n,dict) or type(n.get('id')) is not int or n['id'] in ns: raise MalformedWorkflowError('malformed node','workflow.node')
  if n['id'] in _T and (not isinstance(n.get('type'),str) or not isinstance(n.get('inputs'),list) or not isinstance(n.get('outputs'),list)): raise MalformedWorkflowError('malformed required node','workflow.node')
  ns[n['id']]=n
 for i,t in _T.items():
  if ns.get(i,{}).get('type')!=t: raise IncompatibleWorkflowError('required node/type missing','workflow.node_type')
 ls={}
 for x in d['links']:
  if not isinstance(x,list) or len(x)!=6 or type(x[0]) is not int or x[0] in ls: raise MalformedWorkflowError('malformed link','workflow.link')
  ls[x[0]]=x
 for lid,o,os,t,ts,typ in ls.values():
  if o not in ns or t not in ns: raise MalformedWorkflowError('unknown endpoint','workflow.endpoint')
  if type(os) is not int or type(ts) is not int or os<0 or ts<0: raise MalformedWorkflowError('invalid slot','workflow.slot_index')
  if os>=len(ns[o].get('outputs',[])) or ts>=len(ns[t].get('inputs',[])): raise MalformedWorkflowError('slot out of range','workflow.slot_range')
  if not all(isinstance(e,dict) and isinstance(e.get('name'),str) for e in ns[o]['outputs']+ns[t]['inputs']): raise MalformedWorkflowError('malformed slot','workflow.slot')
  if ns[o]['outputs'][os].get('type')!=typ or ns[t]['inputs'][ts].get('type')!=typ: raise IncompatibleWorkflowError('link type mismatch','workflow.type_mismatch')
 for r in _L:
  if ls.get(r[0])!=list(r): raise IncompatibleWorkflowError('required topology mismatch','workflow.topology')
 ins={e['name']:e for e in ns[129]['inputs']}; names=('clip','vae','audio_vae','first_frame','last_frame',*REQUIRED_REFS,'prompt','width','height','length','ref_image_size','also_ref_first_frame')
 if any(x not in ins for x in names): raise IncompatibleWorkflowError('missing H3 input','workflow.input_missing')
 for i in range(6):
  lid=ins[REQUIRED_REFS[i]].get('link')
  if lid not in ls or ls[lid][3:5]!=[129,5+i]: raise IncompatibleWorkflowError('reference mismatch','workflow.reference_topology')
 if ins[REQUIRED_REFS[6]].get('link') is not None: raise IncompatibleWorkflowError('ref6 connected','workflow.ref6_connected')
 for lid,(_,o,os,t,ts,_) in ls.items():
  if ns[t]['inputs'][ts].get('link')!=lid or lid not in (ns[o]['outputs'][os].get('links') or []): raise IncompatibleWorkflowError('link consistency mismatch','workflow.link_consistency')
 return CompatibilityReport(H3_PROFILE,digest,tuple(sorted(ns)),tuple(sorted(ls)))

def validate_static_compatibility(raw, expected_sha256=H3_CANONICAL_SHA256):
 if not isinstance(raw,(bytes,bytearray)): raise MalformedWorkflowError('raw workflow bytes required','workflow.raw_type')
 digest=hashlib.sha256(bytes(raw)).hexdigest().upper()
 if digest!=str(expected_sha256).upper(): raise WorkflowHashMismatchError('workflow SHA-256 mismatch','workflow.hash_mismatch')
 try: d=json.loads(bytes(raw))
 except Exception as e: raise MalformedWorkflowError('invalid workflow JSON','workflow.invalid_json') from e
 return validate_ui_workflow_structure(d, verified_sha256=digest)

_BOUND_MUTABLE_KEYS=frozenset({'114.image','119.megapixels','146.steps',*(f'{n}.image' for n in (130,131,132,150,151,152)),'129.prompt','129.width','129.height','129.length','129.ref_image_size','129.also_ref_first_frame','148.fps'})

def _validate_api_template(d, *, bound=False):
 if not isinstance(d,dict) or set(d)!=set(map(str,H3_NODE_TYPES)): raise IncompatibleWorkflowError('API template node set mismatch','template.shape')
 for k,cls in H3_NODE_TYPES.items():
  n=d.get(str(k))
  if not isinstance(n,dict) or n.get('class_type')!=cls or not isinstance(n.get('inputs'),dict): raise IncompatibleWorkflowError('API template class/input mismatch','template.class')
 ins=d['129']['inputs']; req={'prompt','first_frame','width','height','length','ref_image_size','also_ref_first_frame','clip','vae','audio_vae',*(f'ref_images.ref_image_{i}' for i in range(6))}
 if not req.issubset(ins): raise IncompatibleWorkflowError('API template input set mismatch','template.inputs')
 if d['127']['inputs'].get('crop_region') != dict(NO_CROP_BOUNDING_BOX):
  raise IncompatibleWorkflowError('first-frame crop must preserve the full image','template.first_frame_crop')
 if d['148']['inputs'].get('images')!=['147',0] or d['92']['inputs'].get('video')!=['148',0]: raise IncompatibleWorkflowError('API chain mismatch','template.chain')
 # Every canonical link must resolve locally; only [node_id, slot] pairs are links.
 for consumer_id,node in d.items():
  for input_name,value in node['inputs'].items():
   if isinstance(value,list) and len(value)==2 and isinstance(value[0],str) and type(value[1]) is int and value[0] in d:
    source=value[0]; slot=value[1]
    if slot < 0: raise IncompatibleWorkflowError(f'invalid link: {consumer_id}.{input_name} -> {source}[{slot}]','template.link')
   elif isinstance(value,list) and len(value)==2 and isinstance(value[0],str) and type(value[1]) is int and value[0] not in d:
    raise IncompatibleWorkflowError(f'dangling link: {consumer_id}.{input_name} -> {value[0]}[{value[1]}]','template.dangling_link',{'consumer':consumer_id,'input':input_name,'source':value[0]})
   key=f'{consumer_id}.{input_name}'
   if key in _API_LINKS and value != _API_LINKS[key] and not (bound and key in _BOUND_MUTABLE_KEYS): raise IncompatibleWorkflowError(f'canonical link mismatch: {key}','template.topology')
 present={f'{i}.{k}' for i,n in d.items() for k,v in n['inputs'].items() if isinstance(v,list) and len(v)==2 and isinstance(v[0],str) and type(v[1]) is int}
 expected_links=set(_API_LINKS)
 if bound:
  expected_links={k for k in expected_links if not (k in _BOUND_MUTABLE_KEYS and d[k.split('.',1)[0]]['inputs'][k.split('.',1)[1]] != _API_LINKS[k])}
 if present != expected_links: raise IncompatibleWorkflowError('canonical link set mismatch','template.topology')
 # Recursive closure from SaveVideo, fail-closed on malformed link shape.
 seen=set(); stack=['92']
 if bound:
  for key in _BOUND_MUTABLE_KEYS:
   if key in _API_LINKS:
    node_id,input_name=key.split('.',1)
    if d[node_id]['inputs'].get(input_name)!=_API_LINKS[key]:
     stack.append(_API_LINKS[key][0])
 while stack:
  current=stack.pop()
  if current in seen: continue
  seen.add(current)
  for name,value in d[current]['inputs'].items():
   if isinstance(value,list) and len(value)==2 and isinstance(value[0],str) and type(value[1]) is int:
    if value[0] not in d: raise IncompatibleWorkflowError(f'dangling link: {current}.{name} -> {value[0]}[{value[1]}]','template.dangling_link')
    stack.append(value[0])
 if seen != set(d): raise IncompatibleWorkflowError('API graph is not closed from output 92','template.closure')
 if bound:
  def _placeholders(value, path=''):
   if isinstance(value,str) and '__ORQ_' in value: return [(path,value)]
   if isinstance(value,dict):
    out=[]
    for k,v in value.items(): out.extend(_placeholders(v,f'{path}.{k}' if path else str(k)))
    return out
   if isinstance(value,list):
    out=[]
    for i,v in enumerate(value): out.extend(_placeholders(v,f'{path}[{i}]'))
    return out
   return []
  leftovers=[x for x in _placeholders(d) if x[1] != '__ORQ_FIRST_FRAME__']
  if leftovers: raise WorkflowProfileError('unbound ORQ placeholders','binding.placeholders',{'placeholders':tuple(x[0] for x in leftovers)})
 return d

def _validate_reduced_bound_graph(d):
 """Validate the compact graph produced when trailing reference branches are pruned."""
 if not isinstance(d,dict) or not d: raise IncompatibleWorkflowError('reduced graph required','template.reduced_shape')
 required={'92','114','119','120','127','129','136','137','138','139','142','143','144','145','146','147','148'}
 if not required.issubset(d): raise IncompatibleWorkflowError('reduced graph missing required node','template.reduced_node')
 for node_id,node in d.items():
  if not isinstance(node,dict) or node.get('class_type') != H3_NODE_TYPES.get(int(node_id)) or not isinstance(node.get('inputs'),dict):
   raise IncompatibleWorkflowError('reduced graph node mismatch','template.reduced_node')
 for consumer,node in d.items():
  for name,value in node['inputs'].items():
   if isinstance(value,list) and len(value)==2 and isinstance(value[0],str) and type(value[1]) is int:
    if value[0] not in d or value[1] < 0: raise IncompatibleWorkflowError('reduced graph dangling link','template.dangling_link')
 refs=sorted((k for k in d['129']['inputs'] if k.startswith('ref_images.ref_image_')), key=lambda k:int(k.rsplit('_',1)[1]))
 if refs != [f'ref_images.ref_image_{i}' for i in range(len(refs))] or len(refs)>6:
  raise IncompatibleWorkflowError('reduced graph reference keys are not dense','template.references')
 if any(not isinstance(d['129']['inputs'][k],list) or d['129']['inputs'][k][0] not in d for k in refs):
  raise IncompatibleWorkflowError('reduced graph reference link missing','template.references')
 return d

def configure_fast_e2e(api_prompt):
 """Return a non-persistent, explicitly opt-in fast development prompt."""
 _validate_api_template(api_prompt)
 out=json.loads(json.dumps(api_prompt))
 out['119']['inputs']['megapixels']=FAST_E2E_CONFIG['megapixels']
 out['129']['inputs']['length']=FAST_E2E_CONFIG['length']
 out['146']['inputs']['steps']=FAST_E2E_CONFIG['steps']
 _validate_api_template(out)
 return out

def bind_inputs(api_prompt, *, prompt=None, first_frame=None, references=None, **values):
 """Return a copy of the API prompt with only declared H3 inputs overridden."""
 _validate_api_template(api_prompt)
 out=json.loads(json.dumps(api_prompt)); ins=out['129']['inputs']
 allowed={'prompt','first_frame','megapixels','steps','width','height','length','ref_image_size','also_ref_first_frame','fps'}
 if prompt is not None: values['prompt']=prompt
 if first_frame is not None: values['first_frame']=first_frame
 for k,v in values.items():
  if k not in allowed: raise WorkflowProfileError(f'unsupported H3 binding: {k}','binding.unsupported')
  try:
   if k in {'megapixels','steps','length','fps','ref_image_size','also_ref_first_frame'}:
    v=validate_parameter(k,v)
  except GenerationConfigError as exc:
   raise WorkflowProfileError(str(exc),'binding.invalid_value') from exc
  if k=='fps': out['148']['inputs']['fps']=v
  elif k=='megapixels': out['119']['inputs']['megapixels']=v
  elif k=='steps': out['146']['inputs']['steps']=v
  elif k=='first_frame':
   if not isinstance(v,str) or not v.strip(): raise WorkflowProfileError('first_frame must be a nonblank path','binding.first_frame')
   out['114']['inputs']['image']=v
  elif k=='prompt':
   if not isinstance(v,str) or not v.strip(): raise WorkflowProfileError('prompt must be nonblank','binding.prompt')
   ins[k]=v
  else: ins[k]=v
 if references is not None:
  if not isinstance(references,(list,tuple)) or len(references)>6: raise WorkflowProfileError('references must contain 0 to 6 images','binding.references')
  refs=list(references)
  if any(not isinstance(v,str) or not v.strip() for v in refs): raise WorkflowProfileError('reference image paths must be nonblank','binding.references')
  for i,v in enumerate(refs):
   if not isinstance(v,str) or not v.strip(): raise WorkflowProfileError('reference image paths must be nonblank','binding.references')
   out[str((130,131,132,150,151,152)[i])]['inputs']['image']=v
  # Compact the product binding: omit absent reference slots and their branch.
  if len(refs) < 6:
   branch_nodes=((130,133,156),(131,134,157),(132,135,158),(150,153,159),(151,154,161),(152,155,160))
   for nodes in branch_nodes[len(refs):]:
    for nid in nodes: out.pop(str(nid),None)
   for key in list(ins):
    if key.startswith('ref_images.ref_image_') and int(key.rsplit('_',1)[1]) >= len(refs): ins.pop(key)
 if references is None or len(references)==6:
  _validate_api_template(out, bound=True)
 else:
  _validate_reduced_bound_graph(out)
 return out

def rebind_first_frame(bound_prompt, first_frame):
 """Copy an H3 API prompt and replace its authoritative first-frame input."""
 _validate_api_template(bound_prompt, bound=True)
 if not isinstance(first_frame, str) or not first_frame.strip():
  raise WorkflowProfileError('first_frame must be a nonblank path','binding.first_frame')
 out=json.loads(json.dumps(bound_prompt))
 node_id, input_name = H3_BINDINGS['first_frame']
 node=out.get(str(node_id))
 if not isinstance(node,dict) or not isinstance(node.get('inputs'),dict) or input_name not in node['inputs']:
  raise IncompatibleWorkflowError('authoritative first_frame binding missing','binding.first_frame')
 node['inputs'][input_name]=first_frame
 _validate_api_template(out, bound=True)
 return out

def load_api_template(path=None):
 p=Path(path) if path else Path(__file__).with_name('artifacts')/'minimax_h3_api_template.v1.json'
 try:
  raw=p.read_bytes()
  if hashlib.sha256(raw).hexdigest().upper()!=H3_API_TEMPLATE_SHA256: raise WorkflowHashMismatchError('API template integrity mismatch','template.hash')
  manifest=json.loads((p.with_name('minimax_h3_profile.v1.json')).read_text(encoding='utf-8'))
  if manifest.get('profile')!=H3_PROFILE.name or manifest.get('version')!=H3_PROFILE.version or manifest.get('canonical_ui_sha256')!=H3_CANONICAL_SHA256: raise IncompatibleWorkflowError('API manifest mismatch','template.manifest')
  if manifest.get('api_template_sha256')!=H3_API_TEMPLATE_SHA256: raise WorkflowHashMismatchError('API manifest hash mismatch','template.manifest_hash')
  return _validate_api_template(json.loads(raw.decode('utf-8')))
 except (OSError, json.JSONDecodeError) as e: raise WorkflowProfileError('invalid API template','template.invalid') from e
