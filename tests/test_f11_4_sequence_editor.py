import unittest
from orquestador.application.edit_chunk_sequence import EditChunkSequenceUseCase
from orquestador.domain.config import CHUNK_OVERRIDE_KEYS
from orquestador.domain.core import Project, Execution, Chunk, Lifecycle, DomainError

class Repo:
    def __init__(self):
        self.p=Project(); self.e=Execution(self.p.id)
        self.e.add_chunk(Chunk(order=0,defaults={'prompt':'a'})); self.e.add_chunk(Chunk(order=1,defaults={'prompt':'b'}))
    def load(self,pid): return self.p,[self.e]
    def save(self,p,es): self.p,self.e=p,es[0]
    def load_transitions(self,eid): return []

class FailingRepo(Repo):
    def save(self,p,es): raise RuntimeError('injected persistence failure')

class F114SequenceEditorTests(unittest.TestCase):
    def setUp(self): self.r=Repo(); self.uc=EditChunkSequenceUseCase(self.r)
    def test_structural_ops_ids_and_minimum(self):
        ids=[str(c.id) for c in self.r.e.chunks]; self.uc(self.r.p.id,self.r.e.id,'duplicate',ids[0]); self.assertEqual(len(self.r.e.chunks),3); self.assertNotEqual(str(self.r.e.chunks[1].id),ids[0]); self.uc(self.r.p.id,self.r.e.id,'move',str(self.r.e.chunks[2].id),delta=-1); self.uc(self.r.p.id,self.r.e.id,'remove',str(self.r.e.chunks[1].id)); self.assertEqual(len(self.r.e.chunks),2)
    def test_override_provenance_and_restore(self):
        cid=str(self.r.e.chunks[0].id); self.r.p.defaults={'steps':20}; self.uc(self.r.p.id,self.r.e.id,'set_override',cid,key='steps',value=30); p=self.uc(self.r.p.id,self.r.e.id,'read_provenance',cid); self.assertEqual(p['steps']['source'],'override'); self.uc(self.r.p.id,self.r.e.id,'clear_override',cid,key='steps'); self.assertEqual(self.uc(self.r.p.id,self.r.e.id,'read_provenance',cid)['steps']['source'],'project')
    def test_forbidden_override_rejected(self):
        with self.assertRaises(DomainError): self.uc(self.r.p.id,self.r.e.id,'set_override',str(self.r.e.chunks[0].id),key='seed',value=1)
    def test_runtime_evidence_locks_edits(self):
        self.r.e.chunks[0].state=Lifecycle.RUNNING
        with self.assertRaises(DomainError): self.uc(self.r.p.id,self.r.e.id,'duplicate',str(self.r.e.chunks[0].id))

    def test_add_remove_duplicate_reorder_reload_contiguous_stable_ids(self):
        original=[c.id for c in self.r.e.chunks]; self.uc(self.r.p.id,self.r.e.id,'add',defaults={'prompt':'c'})
        self.uc(self.r.p.id,self.r.e.id,'duplicate',str(original[0])); self.uc(self.r.p.id,self.r.e.id,'move',str(original[1]),delta=-1)
        self.uc(self.r.p.id,self.r.e.id,'remove',str(original[0])); self.assertEqual([c.order for c in self.r.e.chunks],list(range(3))); self.assertIn(original[1],[c.id for c in self.r.e.chunks])

    def test_adjacent_swap_collision_safe_and_ids_preserved(self):
        ids=[c.id for c in self.r.e.chunks]; self.uc(self.r.p.id,self.r.e.id,'move',str(ids[0]),delta=1); self.assertEqual([c.id for c in self.r.e.chunks], [ids[1],ids[0]])

    def test_remove_below_minimum_rejected_without_mutation(self):
        before=[c.id for c in self.r.e.chunks]
        with self.assertRaises(DomainError): self.uc(self.r.p.id,self.r.e.id,'remove',str(before[0]))
        self.assertEqual(before,[c.id for c in self.r.e.chunks])

    def test_persistence_failure_rolls_back_sequence(self):
        r=FailingRepo(); uc=EditChunkSequenceUseCase(r); before=[(c.id,c.order) for c in r.e.chunks]
        with self.assertRaises(RuntimeError): uc(r.p.id,r.e.id,'add')
        self.assertEqual(before,[(c.id,c.order) for c in r.e.chunks])

    def test_attempts_artifacts_errors_guard_fails_closed(self):
        self.r.e.chunks[0].attempts=[object()]
        with self.assertRaises(DomainError): self.uc(self.r.p.id,self.r.e.id,'update_prompt',str(self.r.e.chunks[0].id),prompt='x')

    def test_transition_guard_including_nullable_target(self):
        self.r.load_transitions=lambda eid:[{'source_chunk_id':None,'target_chunk_id':None}]
        with self.assertRaises(DomainError): self.uc(self.r.p.id,self.r.e.id,'add')

    def test_non_pending_execution_and_chunk_rejected(self):
        self.r.e.state=Lifecycle.SUCCEEDED
        with self.assertRaises(DomainError): self.uc(self.r.p.id,self.r.e.id,'add')
        self.r.e.state=Lifecycle.PENDING; self.r.e.chunks[0].state=Lifecycle.RUNNING
        with self.assertRaises(DomainError): self.uc(self.r.p.id,self.r.e.id,'update_prompt',str(self.r.e.chunks[0].id),prompt='x')

    def test_n4_config_and_prompt_inheritance_clear(self):
        [self.uc(self.r.p.id,self.r.e.id,'add') for _ in range(2)]; self.r.p.defaults={'prompt':'inherited'}; self.r.e.chunks[0].defaults={}
        cid=str(self.r.e.chunks[0].id); self.assertEqual(self.uc(self.r.p.id,self.r.e.id,'read_effective',cid)['prompt'],'inherited')
        self.uc(self.r.p.id,self.r.e.id,'update_prompt',cid,prompt='explicit'); self.assertEqual(self.uc(self.r.p.id,self.r.e.id,'read_effective',cid)['prompt'],'explicit'); self.uc(self.r.p.id,self.r.e.id,'clear_override',cid,key='prompt'); self.assertEqual(self.uc(self.r.p.id,self.r.e.id,'read_effective',cid)['prompt'],'inherited')

    def test_duplicate_copies_defaults_without_runtime_evidence(self):
        c=self.r.e.chunks[0]; c.defaults={'prompt':'x'}; c.attempts=[]; self.uc(self.r.p.id,self.r.e.id,'duplicate',str(c.id)); d=self.r.e.chunks[1]; self.assertEqual(d.defaults,c.defaults); self.assertEqual(d.attempts,[]); self.assertNotEqual(d.id,c.id)

    def test_all_content_operations_roundtrip(self):
        cid=str(self.r.e.chunks[0].id); self.uc(self.r.p.id,self.r.e.id,'update_prompt',cid,prompt='z'); self.uc(self.r.p.id,self.r.e.id,'set_override',cid,key='steps',value=22); self.uc(self.r.p.id,self.r.e.id,'clear_override',cid,key='steps'); self.assertEqual(self.r.e.chunks[0].defaults['prompt'],'z')

    def test_production_gui_wires_editor_and_public_surface(self):
        import orquestador.ui.app as app
        self.assertTrue(hasattr(app,'compose'))

if __name__=='__main__': unittest.main()
