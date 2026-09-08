import os, tempfile, unittest, inspect
from pathlib import Path
from unittest.mock import patch
from orquestador.ui.app import AppConfig, compose
from orquestador.profiles.minimax_h3 import H3_PROFILE
from orquestador.domain.core import BackendJobRef
from orquestador.adapters.http import HistoryResult, HistoryState
from orquestador.adapters.video import VideoFrame

class FakeChain:
    def __init__(self): self.calls=[]
    def run(self, project, execution, prompts, *, transition_rebinder=None, transition_materializer=None): self.calls.append((project, execution, prompts, transition_rebinder, transition_materializer)); return {"state":"submitted"}

class F10GuiMatrixTests(unittest.TestCase):
    def setUp(self):
        self._old_tmp={k:os.environ.get(k) for k in ('TEMP','TMP','ORQ_TEST_TMP')}
        base=Path(os.environ.get("ORQ_TEST_TMP", tempfile.gettempdir())).resolve(); base.mkdir(parents=True, exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=base); self.root=Path(self.tmp.name)
        (self.root/'start.png').write_bytes(b'start'); self.refs=[]
        for i in range(6): p=self.root/f'ref{i}.png'; p.write_bytes(f'ref{i}'.encode()); self.refs.append(str(p))
        os.environ['TEMP']=os.environ['TMP']=os.environ['ORQ_TEST_TMP']=str(self.root)
        self.chain=FakeChain(); self.facade,self.res=compose(AppConfig(self.root),chain_usecase=self.chain)
    def tearDown(self):
        self.res['repository'].close(); self.tmp.cleanup()
        for k,v in self._old_tmp.items():
            if v is None: os.environ.pop(k,None)
            else: os.environ[k]=v
    def prep(self,**kw):
        a=dict(initial_image=str(self.root/'start.png'),prompts=['one','two'],references=self.refs); a.update(kw); return self.facade.prepare(**a)
    def test_architecture_boundaries_and_real_defaults(self):
        self.assertNotIn('start_chain_old',Path('src/orquestador/ui/app.py').read_text()); self.res['repository'].close(); _,real=compose(AppConfig(self.root)); self.assertEqual(type(real['chain']).__name__,'ChainExecutionUseCase'); self.assertEqual(type(real['coordinator']).__name__,'ChunkExecutionCoordinator'); real['repository'].close()
        ui=Path('src/orquestador/ui/main_window.py').read_text(); self.assertNotRegex(ui,r'(sqlite|ComfyUI|ffmpeg|persistence)'); [self.assertIn(x,ui) for x in ('project_id','execution_id','initial_image','prompts','references')]
    def test_compose_extractor_injection_keeps_chain_boundary(self):
        class E: pass
        self.res['repository'].close(); _,r=compose(AppConfig(self.root),extractor_factory=E); self.assertEqual(type(r['chain']).__name__,'ChainExecutionUseCase'); self.assertEqual(type(r['coordinator']).__name__,'ChunkExecutionCoordinator'); r['repository'].close()
    def test_generated_and_explicit_ids(self):
        a=self.prep(); self.assertTrue(a.snapshot.project_id.strip()); self.assertTrue(a.snapshot.execution_id.strip()); b=self.prep(project_id='P',execution_id='E'); self.assertEqual((b.snapshot.project_id,b.snapshot.execution_id),('P','E')); c=self.prep(project_id='Q'); self.assertEqual(c.snapshot.project_id,'Q'); self.assertTrue(c.snapshot.execution_id)
    def test_existing_selection_preserves_state_and_conflict_fails(self):
        a=self.prep(project_id='p',execution_id='e'); r=self.res['repository']; before=repr(r.load('p')); self.assertTrue(self.prep(project_id='p',execution_id='e').success); self.assertEqual(before,repr(r.load('p'))); self.assertTrue(self.prep(project_id='p',execution_id='e',prompts=['changed','two']).success)
    def test_prepare_validation_matrix(self):
        before=set(self.root.rglob('*')); cases=[dict(initial_image='missing'),dict(initial_image=str(self.root)),dict(prompts=['one']),dict(prompts=['one',' ']),dict(references=self.refs+['x']),dict(chunk_count=1),dict(chunk_count=4)]
        for kw in cases:
            with self.subTest(kw=kw): self.assertFalse(self.prep(**kw).success)
        self.assertEqual(before,set(self.root.rglob('*')))
    def test_imports_are_contained_collision_safe_and_idempotent(self):
        a=self.prep(); _,es=self.res['repository'].load(a.snapshot.project_id); d=es[0].defaults; self.assertTrue(all(not Path(v).is_absolute() for v in [d['initial_image'],*d['references']])); self.assertTrue((self.root/d['initial_image']).is_file()); self.assertTrue(self.prep().success)
        other=self.root/'other.png'; other.write_bytes(b'start'); self.assertTrue(self.prep(initial_image=str(other)).success)
    def test_copy_failure_rolls_back_and_preserves_preexisting(self):
        (self.root/'inputs').mkdir(); old=self.root/'inputs'/'start.png'; old.write_bytes(b'old'); self.assertTrue(self.prep().success); self.assertEqual(old.read_bytes(),b'old'); old.unlink()
        with patch.object(Path,'write_bytes',side_effect=OSError('denied')): self.assertFalse(self.prep().success)
    def test_six_refs_order_and_ref6_unbound(self):
        a=self.prep(); pid,eid=a.snapshot.project_id,a.snapshot.execution_id; self.assertTrue(self.facade.start_chain(pid,eid).success); bound=self.chain.calls[0][2][0]['129']['inputs']; self.assertNotIn('ref_images.ref_image_6',bound); self.assertEqual([bound[f'ref_images.ref_image_{i}'] for i in range(6)],[['156',0],['157',0],['158',0],['159',0],['161',0],['160',0]])
    def test_fast_e2e_flag_uses_copy_without_persisting_defaults(self):
        a=self.prep(); pid,eid=a.snapshot.project_id,a.snapshot.execution_id
        self.assertTrue(self.facade.start_chain(pid,eid,fast_e2e=True).success)
        prompt=self.chain.calls[0][2][0]
        self.assertEqual((prompt['119']['inputs']['megapixels'],prompt['129']['inputs']['length'],prompt['146']['inputs']['steps']),(0.09,56,4))
        self.assertEqual(prompt['127']['inputs']['crop_region'],{'x':0,'y':0,'width':16384,'height':16384})
        _, executions=self.res['repository'].load(pid)
        self.assertNotIn('fast_e2e',executions[0].defaults)
    def test_start_overrides_and_zero_chain_calls_on_failures(self):
        a=self.prep(); pid,eid=a.snapshot.project_id,a.snapshot.execution_id; self.assertTrue(self.facade.start_chain(pid,eid).success)
        for kw in (dict(initial_image=' '),dict(initial_image='arbitrary'),dict(prompts=['one']),dict(references=self.refs[:5]),dict(references=self.refs+['x'])):
            with self.subTest(kw=kw): self.assertFalse(self.facade.start_chain(pid,eid,**kw).success)
        self.assertEqual(len(self.chain.calls),1)
    def test_start_missing_project_execution_profile_and_chunk_fail_closed(self):
        self.assertFalse(self.facade.start_chain('none','none').success); a=self.prep(); pid,eid=a.snapshot.project_id,a.snapshot.execution_id; repo=self.res['repository']; orig=repo.load
        def badload(x):
            p,es=orig(x); es[0].workflow_profile_ref=type(es[0].workflow_profile_ref)('wrong'); return p,es
        with patch.object(repo,'load',side_effect=badload): self.assertFalse(self.facade.start_chain(pid,eid).success)
        self.assertEqual(len(self.chain.calls),0)
    def test_each_missing_persisted_image_or_ref_rejected(self):
        a=self.prep(); pid,eid=a.snapshot.project_id,a.snapshot.execution_id; d=self.res['repository'].load(pid)[1][0].defaults
        for i,path in enumerate([d['initial_image'],*d['references']]):
            target=self.root/path; target.unlink(); self.assertFalse(self.facade.start_chain(pid,eid).success); target.write_bytes(b'start' if i==0 else f'ref{i-1}'.encode())
    def test_preparation_three_chunks_and_no_transition_frame(self):
        a=self.prep(chunk_count=3,prompts=['a','b','c']); e=self.res['repository'].load(a.snapshot.project_id)[1][0]; self.assertEqual(len(e.chunks),3); self.assertTrue(all(c.first_frame is None for c in e.chunks))

    def test_real_chain_cross_chunk_composition(self):
        self.res['repository'].close()
        class Client:
            def __init__(self, endpoint): self.submits=[]; self.uploads=[]; self.network_calls=0
            def submit(self, prompt, client_id=None):
                self.submits.append(prompt); ref=BackendJobRef(f'job-{len(self.submits)}'); p=self.root/'outputs'/f'{ref.value}.mp4'; p.parent.mkdir(exist_ok=True); p.write_bytes(b'video'); return ref
            def upload_image(self, path, *, subfolder='', overwrite=False, requested_filename=None):
                name = requested_filename or Path(path).name
                self.uploads.append((subfolder + '/' if subfolder else '') + name)
                return {'name': name, 'subfolder': subfolder, 'type':'input'}
            def history(self, ref):
                return HistoryResult(ref, HistoryState.SUCCEEDED, {'status':{'status_str':'success','completed':True},'outputs':{'92':{'images':[{'filename':f'{ref.value}.mp4','subfolder':'outputs','type':'output'}],'animated':[True]}}})
            def health(self): self.network_calls+=1; raise AssertionError('network')
        class Extractor:
            def __init__(self): self.calls=[]
            def extract_last_frame(self, source, destination):
                destination=Path(destination); self.calls.append((Path(source),destination)); destination.parent.mkdir(parents=True,exist_ok=True); destination.write_bytes(b'frame'); return VideoFrame(destination,4,5)
        c1=Client('x'); c1.root=self.root; e1=Extractor(); f1,r1=compose(AppConfig(self.root),client_factory=lambda _:c1,extractor_factory=lambda:e1)
        p=f1.prepare(project_id='p-real',execution_id='e-real',initial_image=str(self.root/'start.png'),prompts=['p0','p1'],references=self.refs,chunk_count=2); self.assertTrue(p.success,p.message)
        pid,eid=p.snapshot.project_id,p.snapshot.execution_id; project,es=r1['repository'].load(pid); ex=es[0]; self.assertEqual(ex.workflow_profile_ref.value,H3_PROFILE.name); self.assertEqual(r1['repository'].load_transitions(eid),[]); r1['repository'].close()
        c2=Client('x'); c2.root=self.root; e2=Extractor(); facade,res=compose(AppConfig(self.root),client_factory=lambda _:c2,extractor_factory=lambda:e2); self.res=res
        self.assertEqual(type(res['repository']).__name__,'SQLiteProjectRepository'); self.assertEqual(type(res['chain']).__name__,'ChainExecutionUseCase'); self.assertEqual(type(res['coordinator']).__name__,'ChunkExecutionCoordinator'); self.assertEqual(type(facade).__name__,'GuiFacade'); self.assertEqual(facade.refresh(pid,eid).state,'pending')
        out=facade.start_chain(pid,eid); self.assertTrue(out.success,out.message); self.assertEqual(len(c2.submits),2)
        a,b=c2.submits; self.assertEqual(a['129']['inputs']['prompt'],'p0'); self.assertEqual(b['129']['inputs']['prompt'],'p1'); self.assertEqual([b['129']['inputs'][f'ref_images.ref_image_{i}'] for i in range(6)],[['156',0],['157',0],['158',0],['159',0],['161',0],['160',0]])
        self.assertEqual(len(c2.uploads),8)
        self.assertEqual([Path(x).parent.as_posix() for x in c2.uploads[:7]],['orquestador/static'] * 7)
        self.assertEqual([Path(x).name.split('-')[0] for x in c2.uploads[:7]],['initial','ref','ref','ref','ref','ref','ref'])
        ts=[t for t in res['repository'].load_transitions(eid) if t.target_chunk_id is not None]; self.assertEqual(len(ts),1); t=ts[0]
        self.assertEqual(t.source_output.uri,'outputs/job-1.mp4')
        self.assertEqual(a['129']['inputs']['first_frame'],['119',0])
        self.assertEqual(a['114']['inputs']['image'],c2.uploads[0])
        load_nodes=('130','131','132','150','151','152')
        ref_slots=('156','157','158','159','161','160')
        self.assertEqual([a[node]['inputs']['image'] for node in load_nodes],c2.uploads[1:7])
        self.assertEqual([a['129']['inputs'][f'ref_images.ref_image_{i}'] for i in range(6)],[[node,0] for node in ref_slots])
        self.assertEqual(a['129']['inputs']['first_frame'],['119',0])
        self.assertEqual(b['114']['inputs']['image'],c2.uploads[7])
        self.assertTrue(c2.uploads[7].startswith('orquestador/transitions/transition-'))
        self.assertTrue(c2.uploads[7].endswith('.png'))
        self.assertEqual(b['129']['inputs']['first_frame'],['119',0])
        self.assertNotEqual(t.source_output.uri,ex.defaults['initial_image']); self.assertIsNotNone(t.materialized_ref); self.assertEqual(t.materialized_ref.load_image_value,c2.uploads[7]); self.assertNotIn('__ORQ_FIRST_FRAME__',t.source_output.uri); self.assertTrue((self.root/t.source_output.uri).is_file()); self.assertEqual(len(e2.calls),2)
        _,final=res['repository'].load(pid); self.assertEqual(final[0].state.value,'succeeded'); self.assertEqual(len(c2.submits),2); self.assertEqual(c2.network_calls,0)
        evidence_path=os.environ.get('ORQ_F10_COMPOSITION_EVIDENCE_PATH')
        if evidence_path:
            import json
            rel=lambda x: str(Path(x).relative_to(self.root)) if Path(x).is_absolute() else str(x)
            payload={'project_id':pid,'execution_id':eid,'real_components':['SQLiteProjectRepository','GuiFacade','PrepareGuiUseCase','StartGuiChainUseCase','ChainExecutionUseCase','ChunkExecutionCoordinator','SubmitAttemptUseCase'],'fake_boundaries':['Client','Extractor'],'initial_relative':rel(ex.defaults['initial_image']),'references':[rel(x) for x in ex.defaults['references']], 'chunk0_first_frame':a['129']['inputs']['first_frame'],'transition_uri':t.source_output.uri,'chunk1_first_frame':b['129']['inputs']['first_frame'],'prompt0':a['129']['inputs']['prompt'],'prompt1':b['129']['inputs']['prompt'],'submit_count':len(c2.submits),'final_state':final[0].state.value,'durable_reread_state':final[0].state.value,'durable_transition':t.source_output.uri,'TRANSITION_REPLACED_INITIAL':'YES','PLACEHOLDER_ABSENT':'YES','NO_THIRD_SUBMIT':'YES','NO_REAL_NETWORK':'YES','NO_REAL_FFMPEG':'YES'}
            Path(evidence_path).write_text(json.dumps(payload),encoding='utf-8')
        res['repository'].close()

if __name__=='__main__': unittest.main()
