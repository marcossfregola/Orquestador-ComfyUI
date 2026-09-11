import os, tempfile, unittest
from pathlib import Path
from orquestador.persistence.sqlite import SQLiteProjectRepository, PersistenceError
from orquestador.domain.core import Project, Execution, Chunk, Lifecycle, Attempt, ErrorRecord

class SQLiteF114AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='f114-sqlite-'))
        self.repo = SQLiteProjectRepository(self.root)
        self.p = Project(); self.e = Execution(self.p.id)
        for i in range(4): self.e.add_chunk(Chunk(order=i, defaults={'prompt': str(i)}))
        self.repo.save(self.p, [self.e])
    def tearDown(self): self.repo.close()
    def test_preparation_roundtrip_add_remove_duplicate_reorder(self):
        self.e.remove_chunk(str(self.e.chunks[0].id)); self.e.duplicate_chunk(str(self.e.chunks[1].id)); self.e.reorder_chunks([c.id for c in reversed(self.e.chunks)])
        self.repo.save_preparation_sequence(self.p, self.e)
        _, loaded = self.repo.load(self.p.id); got=loaded[0]
        self.assertEqual([c.order for c in got.chunks], list(range(4)))
        self.assertEqual([c.defaults['prompt'] for c in got.chunks], ['3','2','2','1'])
    def test_virgin_prunes_stale_rows_but_nonvirgin_refuses_atomically(self):
        stale=Chunk(order=4, defaults={'prompt':'stale'}); self.e.add_chunk(stale); self.repo.save(self.p,[self.e])
        self.e.chunks.pop(); self.e.reorder_chunks([c.id for c in self.e.chunks]); self.repo.save_preparation_sequence(self.p, self.e)
        self.assertEqual(self.repo.db.execute('select count(*) from chunks where execution_id=?',(str(self.e.id),)).fetchone()[0],4)
        self.e.state=Lifecycle.RUNNING; self.repo.save(self.p,[self.e])
        before=self.repo.db.execute('select id,ord,state from chunks where execution_id=? order by ord',(str(self.e.id),)).fetchall()
        with self.assertRaises(PersistenceError): self.repo.save_preparation_sequence(self.p,self.e)
        self.assertEqual(before,self.repo.db.execute('select id,ord,state from chunks where execution_id=? order by ord',(str(self.e.id),)).fetchall())
    def test_attempt_evidence_and_injected_failure_rollback(self):
        a=self.e.chunks[0].new_attempt(); a.error=ErrorRecord('X','boom')
        self.repo.save(self.p,[self.e])
        with self.assertRaises(PersistenceError): self.repo.save_preparation_sequence(self.p,self.e)
        self.assertEqual(self.repo.db.execute('select count(*) from errors').fetchone()[0],1)
        e2=Execution(self.p.id); e2.add_chunk(Chunk(order=0)); e2.add_chunk(Chunk(order=1)); self.repo.save(self.p,[e2])
        original=self.repo.save
        self.repo.save=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('injected'))
        with self.assertRaises(RuntimeError): self.repo.save_preparation_sequence(self.p,e2)
        self.assertEqual(self.repo.db.execute('select count(*) from chunks where execution_id=?',(str(e2.id),)).fetchone()[0],2)
        self.repo.save=original
    def test_generic_incomplete_aggregate_preserves_omitted_history(self):
        before=self.repo.db.execute('select id,ord,defaults from chunks where execution_id=? order by ord',(str(self.e.id),)).fetchall()
        partial=Execution(self.p.id,self.e.id,chunks=[self.e.chunks[0]])
        self.repo.save(self.p,[partial])
        self.assertEqual(before,self.repo.db.execute('select id,ord,defaults from chunks where execution_id=? order by ord',(str(self.e.id),)).fetchall())

if __name__ == '__main__': unittest.main()
