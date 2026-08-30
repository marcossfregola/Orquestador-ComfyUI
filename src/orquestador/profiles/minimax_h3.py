"""Canonical MiniMax H3 UI workflow compatibility contract."""
from dataclasses import dataclass
from types import MappingProxyType
import hashlib,json
from pathlib import Path
from orquestador.domain.workflow_profile import WorkflowProfile
class WorkflowProfileError(ValueError):
 def __init__(self,message,code='workflow.invalid',context=None): super().__init__(message); self.code=code; self.context=MappingProxyType(dict(context or {}))
class MalformedWorkflowError(WorkflowProfileError): pass
class IncompatibleWorkflowError(MalformedWorkflowError): pass
class WorkflowHashMismatchError(IncompatibleWorkflowError): pass
H3_CANONICAL_SHA256='3070EB659A0BDBEB3D8392B0D203F6B4B86409709A20143280473A12C44BA4A7'
H3_API_TEMPLATE_SHA256='CDD5C56963BC3CA626ADA678AA9FE6F73046B238BF9D9C8BBE80E3D9173496B9'
H3_PROFILE=WorkflowProfile('minimax-h3-ui','1.0.0')
_T={92:'SaveVideo',114:'LoadImage',119:'ImageScaleToTotalPixels',120:'GetImageSize',127:'ImageCropV2',129:'MiniMaxH3HybridRefAndKeyframe',136:'CLIPLoader',137:'VAELoader',138:'VAELoader',139:'UNETLoader',142:'BasicGuider',143:'SamplerCustomAdvanced',144:'RandomNoise',145:'KSamplerSelect',146:'BasicScheduler',147:'VAEDecode',148:'CreateVideo',**{i:'LoadImage' for i in(130,131,132,150,151,152)},**{i:'ImageCropV2' for i in(133,134,135,153,154,155)},**{i:'ImageScaleToMaxDimension' for i in range(156,162)}}
H3_NODE_TYPES=MappingProxyType(_T); REQUIRED_REFS=tuple(f'ref_images.ref_image_{i}' for i in range(7))
H3_BINDINGS=MappingProxyType({'prompt':(129,'prompt'),'first_frame':(129,'first_frame'),'width':(129,'width'),'height':(129,'height'),'length':(129,'length'),'ref_image_size':(129,'ref_image_size'),'also_ref_first_frame':(129,'also_ref_first_frame'),'fps':(148,'fps'),'output':(92,'video'),'ref_images':tuple((129,f'ref_images.ref_image_{i}') for i in range(6))})
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

def _validate_api_template(d):
 if not isinstance(d,dict) or set(d)!= {'129','148','92'}: raise IncompatibleWorkflowError('API template node set mismatch','template.shape')
 expected={ '129':'MiniMaxH3HybridRefAndKeyframe','148':'CreateVideo','92':'SaveVideo' }
 for k,cls in expected.items():
  n=d.get(k)
  if not isinstance(n,dict) or n.get('class_type')!=cls or not isinstance(n.get('inputs'),dict): raise IncompatibleWorkflowError('API template class/input mismatch','template.class')
 ins=d['129']['inputs']; req={'prompt','first_frame','width','height','length','ref_image_size','also_ref_first_frame','clip','vae','audio_vae',*(f'ref_images.ref_image_{i}' for i in range(6))}
 if set(ins)!=req: raise IncompatibleWorkflowError('API template input set mismatch','template.inputs')
 if d['148']['inputs'].get('images')!=['147',0] or d['148']['inputs'].get('fps') is None or d['148']['inputs'].get('bit_depth') is None: raise IncompatibleWorkflowError('CreateVideo structure mismatch','template.create_video')
 save=d['92']['inputs']
 if save.get('video')!=['148',0] or not all(k in save for k in ('filename_prefix','format','codec')): raise IncompatibleWorkflowError('SaveVideo structure mismatch','template.save_video')
 if not all(isinstance(ins[x],(str,int,bool,list)) for x in req): raise IncompatibleWorkflowError('API template input shape mismatch','template.input_shape')
 return d

def bind_inputs(api_prompt, *, prompt=None, first_frame=None, references=None, **values):
 """Return a copy of the API prompt with only declared H3 inputs overridden."""
 _validate_api_template(api_prompt)
 out=json.loads(json.dumps(api_prompt)); ins=out['129']['inputs']
 allowed={'prompt','first_frame','width','height','length','ref_image_size','also_ref_first_frame','fps'}
 if prompt is not None: values['prompt']=prompt
 if first_frame is not None: values['first_frame']=first_frame
 for k,v in values.items():
  if k not in allowed: raise WorkflowProfileError(f'unsupported H3 binding: {k}','binding.unsupported')
  if k=='fps': out['148']['inputs']['fps']=v
  else: ins[k]=v
 if references is not None:
  if not isinstance(references,(list,tuple)) or len(references)!=6: raise WorkflowProfileError('exactly six reference images required','binding.references')
  for i,v in enumerate(references): ins[f'ref_images.ref_image_{i}']=v
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
