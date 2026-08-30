import copy, hashlib, json, unittest
from pathlib import Path
from orquestador.profiles import minimax_h3 as h3
from orquestador.profiles.minimax_h3 import *
LINKS=[(314,114,0,127,0,'IMAGE'),(315,127,0,119,0,'IMAGE'),(251,119,0,120,0,'IMAGE'),(259,119,0,129,3,'IMAGE'),(263,120,0,129,15,'INT'),(264,120,1,129,16,'INT'),(301,133,0,156,0,'IMAGE'),(302,156,0,129,5,'IMAGE'),(303,134,0,157,0,'IMAGE'),(304,157,0,129,6,'IMAGE'),(305,135,0,158,0,'IMAGE'),(306,158,0,129,7,'IMAGE'),(307,153,0,159,0,'IMAGE'),(310,159,0,129,8,'IMAGE'),(308,154,0,161,0,'IMAGE'),(311,161,0,129,9,'IMAGE'),(309,155,0,160,0,'IMAGE'),(312,160,0,129,10,'IMAGE'),(271,136,0,129,0,'CLIP'),(275,137,0,129,1,'VAE'),(274,138,0,129,2,'VAE'),(281,139,0,142,0,'MODEL'),(282,129,0,142,1,'CONDITIONING'),(283,142,0,143,1,'GUIDER'),(284,144,0,143,0,'NOISE'),(285,145,0,143,2,'SAMPLER'),(286,139,0,146,0,'MODEL'),(287,146,0,143,3,'SIGMAS'),(288,129,1,143,4,'LATENT'),(289,143,0,147,0,'LATENT'),(291,137,0,147,1,'VAE'),(292,147,0,148,0,'IMAGE'),(293,148,0,92,0,'VIDEO')]

def fixture():
 mi={i:0 for i in H3_NODE_TYPES}; mo={i:0 for i in H3_NODE_TYPES}
 for _,o,os,t,ts,_ in LINKS: mo[o]=max(mo[o],os); mi[t]=max(mi[t],ts)
 names=['clip','vae','audio_vae','first_frame','last_frame',*(f'ref_images.ref_image_{i}' for i in range(7)),'ref_videos.ref_video_0','ref_video_audios.ref_video_audio_0','ref_audios.ref_audio_0','width','height','prompt','length','ref_image_size','also_ref_first_frame']
 ns=[]
 for i,t in H3_NODE_TYPES.items():
  ins=[{'name':names[j] if i==129 and j<len(names) else f'in{j}','type':'IMAGE'} for j in range(len(names) if i==129 else mi[i]+1)]; outs=[{'name':f'out{j}','type':'IMAGE','links':[]} for j in range(mo[i]+1)]; ns.append({'id':i,'type':t,'inputs':ins,'outputs':outs})
 by={n['id']:n for n in ns}
 for lid,o,os,t,ts,typ in LINKS: by[o]['outputs'][os].update(type=typ); by[o]['outputs'][os]['links'].append(lid); by[t]['inputs'][ts].update(type=typ,link=lid)
 return {'nodes':ns,'links':[list(x) for x in LINKS]}
class TestH3(unittest.TestCase):
 def setUp(self): self.w=fixture()
 def bad(self,fn,exc=WorkflowProfileError):
  w=copy.deepcopy(self.w); fn(w)
  with self.assertRaises(exc): validate_ui_workflow_structure(w,verified_sha256='fixture')
 def test_success_report_frozen(self):
  r=validate_ui_workflow_structure(self.w,verified_sha256='fixture'); self.assertEqual(r.sha256,'FIXTURE'); self.assertIsInstance(r.node_ids,tuple)
  root=Path(__file__).resolve().parents[1]
  provenance=json.loads((root/'src'/'orquestador'/'profiles'/'artifacts'/'minimax_h3_provenance.v1.json').read_text(encoding='utf-8'))
  source=root/'tests'/'fixtures'/'minimax_h3'/'prompt.sanitized.v2.json'
  self.assertEqual((root/provenance['source']).resolve(),source.resolve())
  raw=source.read_bytes()
  self.assertEqual(hashlib.sha256(raw).hexdigest().upper(),provenance['source_sha256'].upper())
  expected={link[0]:tuple(link) for link in json.loads(raw)['workflow']['links'] if link[0] in (263,264)}
  self.assertEqual(expected[263][1:5],(120,0,129,15))
  self.assertEqual(expected[264][1:5],(120,1,129,16))
  actual={link[0]:link for link in h3._L if link[0] in expected}
  self.assertEqual(actual,expected)
 def test_deep_immutability(self): self.assertRaises(AttributeError,lambda: validate_ui_workflow_structure(self.w).node_ids.__setitem__(0,1))
 def test_nonmapping(self): self.bad(lambda w:w.clear(),MalformedWorkflowError)
 def test_nodes_not_list(self): self.bad(lambda w:w.update(nodes={}),MalformedWorkflowError)
 def test_links_not_list(self): self.bad(lambda w:w.update(links={}),MalformedWorkflowError)
 def test_duplicate_node(self): self.bad(lambda w:w['nodes'].append(copy.deepcopy(w['nodes'][0])),MalformedWorkflowError)
 def test_wrong_type(self): self.bad(lambda w:w['nodes'][0].update(type='X'),IncompatibleWorkflowError)
 def test_missing_node(self): self.bad(lambda w:w['nodes'].pop(),IncompatibleWorkflowError)
 def test_duplicate_link(self): self.bad(lambda w:w['links'].append(w['links'][0]),MalformedWorkflowError)
 def test_malformed_link(self): self.bad(lambda w:w['links'].__setitem__(0,[1]),MalformedWorkflowError)
 def test_unknown_origin(self): self.bad(lambda w:w['links'].__setitem__(0,[314,999,0,127,0,'IMAGE']),MalformedWorkflowError)
 def test_unknown_target(self): self.bad(lambda w:w['links'].__setitem__(0,[314,114,0,999,0,'IMAGE']),MalformedWorkflowError)
 def test_negative_slot(self): self.bad(lambda w:w['links'].__setitem__(0,[314,114,-1,127,0,'IMAGE']),MalformedWorkflowError)
 def test_origin_slot_range(self): self.bad(lambda w:w['links'].__setitem__(0,[314,114,9,127,0,'IMAGE']),MalformedWorkflowError)
 def test_target_slot_range(self): self.bad(lambda w:w['links'].__setitem__(0,[314,114,0,127,9,'IMAGE']),MalformedWorkflowError)
 def test_type_mismatch(self): self.bad(lambda w:w['links'].__setitem__(0,[314,114,0,127,0,'LATENT']),IncompatibleWorkflowError)
 def test_input_global_mismatch(self): self.bad(lambda w:w['nodes'][-1]['inputs'].__setitem__(0,{'name':'x','type':'VIDEO'}),IncompatibleWorkflowError)
 def test_output_global_mismatch(self): self.bad(lambda w: next(n for n in w['nodes'] if n['id']==114)['outputs'][0]['links'].clear(),IncompatibleWorkflowError)
 def test_missing_first_frame(self): self.bad(lambda w:w['nodes'][5]['inputs'].__setitem__(3,{'name':'x','type':'IMAGE'}),IncompatibleWorkflowError)
 def test_rewired_width(self): self.bad(lambda w:next(n for n in w['nodes'] if n['id']==129)['inputs'][15].update(link=999),IncompatibleWorkflowError)
 def test_rewired_height(self): self.bad(lambda w:next(n for n in w['nodes'] if n['id']==129)['inputs'][16].update(link=999),IncompatibleWorkflowError)
 def test_reference_missing(self): self.bad(lambda w:w['nodes'][5]['inputs'].__setitem__(6,{'name':'ref_images.ref_image_1','type':'IMAGE'}),IncompatibleWorkflowError)
 def test_ref6_connected(self): self.bad(lambda w:w['nodes'][5]['inputs'].__setitem__(11,{'name':'ref_images.ref_image_6','type':'IMAGE','link':302}),IncompatibleWorkflowError)
 def test_output_link_missing(self): self.bad(lambda w:w['links'].remove(next(x for x in w['links'] if x[0]==293)),IncompatibleWorkflowError)
 def test_raw_nonbytes(self):
  with self.assertRaises(MalformedWorkflowError): validate_static_compatibility({},'00')
 def test_raw_wrong_hash(self):
  with self.assertRaises(WorkflowHashMismatchError): validate_static_compatibility(b'{}','00')
 def test_raw_invalid_json(self):
  raw=b'{';
  with self.assertRaises(MalformedWorkflowError): validate_static_compatibility(raw,hashlib.sha256(raw).hexdigest())
 def test_template_and_bindings_are_centralized(self):
  t=load_api_template(); b=bind_inputs(t,prompt='x',references=['a']*6,length=20)
  self.assertEqual(b['129']['inputs']['prompt'],'x'); self.assertEqual(b['129']['inputs']['length'],20)
  self.assertEqual(b['129']['inputs']['ref_images.ref_image_5'],'a')
 def test_binding_rejects_unknown_and_wrong_reference_count(self):
  t=load_api_template()
  with self.assertRaises(WorkflowProfileError): bind_inputs(t,wat=False)
  with self.assertRaises(WorkflowProfileError): bind_inputs(t,references=['a'])
if __name__=='__main__': unittest.main()
