import os, unittest, uuid, shutil
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from orquestador.application.gui_facade import GuiFacade, ExecutionSnapshot, ChunkSnapshot, OperationResult

class MainWindowF114AcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def _external_image_path(self, name):
        root = Path(os.environ.get('ORQ_TEST_TMP', r'C:\Codex\Orquestador-Test-Temp\f11-preview-evidence'))
        folder = root / f'{self.__class__.__name__}-{uuid.uuid4().hex}'
        folder.mkdir(parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        return folder / name
    def test_real_action_surface_routes_stable_ids_and_labels(self):
        from orquestador.ui.main_window import MainWindow
        calls=[]; chunks=tuple(ChunkSnapshot(i,'pending',chunk_id=f'id-{i}') for i in range(4))
        snap=ExecutionSnapshot('p','e','pending',chunks=chunks,can_start=True,supported_parameters=('prompt','megapixels','length','steps','fps','ref_image_size','also_ref_first_frame'))
        f=GuiFacade(snapshot=lambda *_:snap, sequence_edit=lambda *a,**k: calls.append((a,k)) or OperationResult(True,snap))
        w=MainWindow(f); self.addCleanup(w.close); w.project.setText('p'); w.execution.setText('e'); w.render(snap); w._run=lambda op,*_a,**_k: op()
        self.assertEqual([w.chunks.item(i).text().split()[1] for i in range(4)],['1','2','3','4'])
        w.chunks.setCurrentRow(1); w._add_sequence(); w._remove_sequence(); w._move_sequence(-1); w._move_sequence(1); w._duplicate_sequence(); w.override_key.setCurrentText('steps'); w.override_value.setText('22'); w._set_override(); w._clear_override(); w._sequence_op('update_prompt','id-1',prompt='edited')
        ops=[k['operation'] for _,k in calls if k['operation']!='read_provenance']
        self.assertEqual(ops,['add','remove','move','move','duplicate','set_override','clear_override','update_prompt'])
        self.assertTrue(all(k.get('chunk_id') in (None,'id-1') for _,k in calls if k['operation']!='read_provenance'))
        w._show_provenance(); self.assertTrue(hasattr(w,'provenance'))

    def test_add_button_dispatches_exactly_once_for_prepared_sequence(self):
        from orquestador.ui.main_window import MainWindow
        chunks = tuple(ChunkSnapshot(i, 'pending', chunk_id=f'id-{i}') for i in range(3))
        snap = ExecutionSnapshot('p', 'e', 'pending', chunks=chunks)
        calls = []; current = {'snap': snap}
        def edit(*a, **k):
            calls.append(k); n = len(current['snap'].chunks) + 1
            current['snap'] = ExecutionSnapshot('p', 'e', 'pending', chunks=tuple(ChunkSnapshot(i, 'pending', chunk_id=f'id-{i}') for i in range(n)))
            return OperationResult(True, current['snap'])
        f = GuiFacade(snapshot=lambda *_: current['snap'], sequence_edit=edit)
        w = MainWindow(f); self.addCleanup(w.close)
        w.project.setText('p'); w.execution.setText('e'); w.render(snap)
        w._prepared_selection = ('p', 'e'); w._run = lambda op, *_a, **_k: (op(), w.render(current['snap']))
        w.add_chunk_button.click()
        self.assertEqual([c['operation'] for c in calls], ['add'])
        self.assertEqual(w.chunk_count.value(), 4)

    def test_remove_button_dispatches_once_and_respects_floor(self):
        from orquestador.ui.main_window import MainWindow
        calls = []
        def run_case(n):
            chunks = tuple(ChunkSnapshot(i, 'pending', chunk_id=f'id-{i}') for i in range(n))
            current = {'snap': ExecutionSnapshot('p', 'e', 'pending', chunks=chunks)}
            def edit(*a, **k):
                calls.append(k)
                if n > 2:
                    current['snap'] = ExecutionSnapshot('p', 'e', 'pending', chunks=tuple(ChunkSnapshot(i, 'pending', chunk_id=f'id-{i+1}') for i in range(n-1)))
                return OperationResult(True, current['snap'])
            f = GuiFacade(snapshot=lambda *_: current['snap'],
                          sequence_edit=edit)
            w = MainWindow(f); self.addCleanup(w.close)
            w.project.setText('p'); w.execution.setText('e'); w.render(current['snap']); w._prepared_selection=('p','e'); w._run=lambda op,*_a,**_k: (op(), w.render(current['snap']))
            w.chunk_tabs.setCurrentIndex(0); w.remove_chunk_button.click()
            return w
        w4 = run_case(4)
        self.assertEqual([c['operation'] for c in calls], ['remove'])
        self.assertEqual(w4.chunk_count.value(), 3)
        calls.clear(); w2 = run_case(2)
        self.assertEqual(calls, [])
        self.assertGreaterEqual(w2.chunk_count.value(), 2)

    def test_five_chunks_are_navigable_in_dynamic_chunk_tabs(self):
        from orquestador.ui.main_window import MainWindow
        chunks=tuple(ChunkSnapshot(i,'pending',chunk_id=f'id-{i}') for i in range(5))
        snap=ExecutionSnapshot('p','e','pending',chunks=chunks,can_start=True)
        f=GuiFacade(snapshot=lambda *_:snap)
        w=MainWindow(f); self.addCleanup(w.close)
        w.chunk_count.setValue(5)
        self.assertEqual(len(w.prompts), 5)
        self.assertEqual([e.objectName() for e in w.prompts], [f'chunkPrompt{i}' for i in range(1,6)])
        self.assertEqual(w.chunk_tabs.count(), 5)
        self.assertTrue(all(e.minimumHeight() >= 260 for e in w.prompts))
        w.prompts[3].setText('chunk four'); w.prompts[4].setText('chunk five')
        self.assertEqual(w.prompts[3].toPlainText(), 'chunk four')
        self.assertEqual(w.prompts[4].toPlainText(), 'chunk five')
        w.render(snap)
        self.assertEqual(w._sequence_ids, [f'id-{i}' for i in range(5)])
        self.assertEqual([w.chunks.item(i).text().split()[1] for i in range(5)], ['1','2','3','4','5'])

    def test_references_have_dedicated_tab_grid_and_controls_below(self):
        from orquestador.ui.main_window import MainWindow
        from PySide6.QtWidgets import QTabWidget
        from PySide6.QtCore import Qt
        snap=ExecutionSnapshot('p','e','pending',reference_slots=tuple(f'r{i}.png' for i in range(6)))
        w=MainWindow(GuiFacade(snapshot=lambda *_:snap)); self.addCleanup(w.close)
        self.assertIsInstance(w.tabs, QTabWidget)
        self.assertEqual([w.tabs.tabText(i) for i in range(w.tabs.count())], ['Principal','Referencias','Chunks'])
        self.assertIs(w.initial_confirmation.parentWidget(), w.tabs.widget(0))
        self.assertIs(w.reference_scroll_area.parentWidget(), w.tabs.widget(1))
        self.assertEqual(w.reference_grid.columnCount(), 2)
        self.assertEqual(w.reference_grid.count(), 6)
        for i in range(6):
            card=w.reference_grid.itemAt(i).widget(); self.assertIsNotNone(card)
            self.assertIs(card.parentWidget(), w.reference_scroll_area.widget())
            self.assertGreaterEqual(card.layout().indexOf(w.reference_labels[i]), 0)
            button_row = card.layout().itemAt(1).layout()
            self.assertIsNotNone(button_row)
            self.assertGreaterEqual(button_row.indexOf(w.reference_buttons[i]), 0)
            self.assertEqual(card.sizePolicy().verticalPolicy().name, 'Maximum')
            self.assertEqual(w.reference_labels[i].sizePolicy().verticalPolicy().name, 'Fixed')
            self.assertEqual((w.reference_labels[i].minimumWidth(), w.reference_labels[i].minimumHeight()), (220, 150))
            self.assertEqual((w.reference_labels[i].maximumWidth(), w.reference_labels[i].maximumHeight()), (220, 150))
        self.assertTrue(w.reference_grid.alignment() & Qt.AlignTop)
        self.assertEqual(w.reference_scroll_area.verticalScrollBarPolicy().name, 'ScrollBarAsNeeded')
        self.assertFalse(w.references.isVisible())

    def test_reference_preview_uses_compact_box_and_preserves_aspect_ratio(self):
        from orquestador.ui.main_window import MainWindow
        from PySide6.QtGui import QImage, QColor
        image_path = self._external_image_path('wide.png')
        image = QImage(400, 200, QImage.Format_RGB32); image.fill(QColor('blue'))
        self.assertTrue(image.save(str(image_path), 'PNG')); self.assertTrue(image_path.is_file())
        snap = ExecutionSnapshot('p', 'e', 'pending', reference_slots=(str(image_path),))
        w = MainWindow(GuiFacade(snapshot=lambda *_: snap)); self.addCleanup(w.close)
        pm = w.reference_labels[0].pixmap()
        self.assertIsNotNone(pm)
        self.assertEqual((pm.width(), pm.height()), (220, 110))
        self.assertAlmostEqual(pm.width() / pm.height(), 2.0, delta=0.02)
        self.assertGreater(pm.width(), 120); self.assertGreater(pm.height(), 72)

    def test_reference_edits_keep_existing_invalidation_contract(self):
        from orquestador.ui.main_window import MainWindow
        snap=ExecutionSnapshot('p','e','pending',can_start=True)
        w=MainWindow(GuiFacade(snapshot=lambda *_:snap)); self.addCleanup(w.close)
        w._prepared_key=w._form_key(); w._auth_can_start=True; w._update_start(); self.assertTrue(w.start.isEnabled())
        self.assertTrue(w.add_reference('r0.png')); self.assertFalse(w.start.isEnabled())
        self.assertTrue(w.replace_reference(0,'r1.png')); self.assertTrue(w.remove_reference(0)); self.assertFalse(w.start.isEnabled())

    def test_render_empty_references_clears_previous_state_without_touching_initial(self):
        from orquestador.ui.main_window import MainWindow
        from PySide6.QtGui import QImage, QColor
        image_path = self._external_image_path('initial.png')
        image = QImage(8, 8, QImage.Format_RGB32); image.fill(QColor('red'))
        self.assertTrue(image.save(str(image_path), 'PNG')); self.assertTrue(image_path.is_file())
        snap_a = ExecutionSnapshot('p', 'a', 'pending', reference_slots=('ref-a.png',))
        snap_b = ExecutionSnapshot('p', 'b', 'pending', reference_slots=())
        w = MainWindow(GuiFacade(snapshot=lambda *_: snap_a)); self.addCleanup(w.close)
        w.initial.setText(str(image_path))
        w.render(snap_a)
        self.assertEqual([w.references.item(i).text() for i in range(w.references.count())], ['ref-a.png'])
        self.assertEqual(w.reference_labels[0].toolTip(), 'ref-a.png')
        w.render(snap_b)
        self.assertEqual(w.references.count(), 0)
        self.assertEqual(w.initial.text(), str(image_path))
        self.assertEqual(w.reference_labels[0].text(), 'Reference 1: empty — choose a file')
        self.assertEqual(w.reference_labels[0].toolTip(), '')
        self.assertTrue(w.reference_labels[0].pixmap() is None or w.reference_labels[0].pixmap().isNull())

    def test_facade_preserves_missing_vs_explicit_empty_reference_authority(self):
        from orquestador.ui.main_window import MainWindow

        class NoReferenceAuthority:
            state = 'pending'; errors = (); chunks = (); supported_parameters = (); artifacts = ()
            can_start = can_cancel = can_retry = can_resume = can_recover = can_assemble = busy = False

        cases = (
            ({'state': 'pending'}, None),
            ({'state': 'pending', 'reference_slots': []}, ()),
            (NoReferenceAuthority(), None),
        )
        for source, expected in cases:
            facade = GuiFacade(snapshot=lambda *_args, source=source: source)
            self.assertEqual(facade.refresh('p', 'e').reference_slots, expected)

        class EmptyReferences(NoReferenceAuthority):
            reference_slots = ()
        facade = GuiFacade(snapshot=lambda *_: EmptyReferences())
        self.assertEqual(facade.refresh('p', 'e').reference_slots, ())

        w = MainWindow(GuiFacade(snapshot=lambda *_: {'state': 'pending', 'reference_slots': ['ref-a.png']})); self.addCleanup(w.close)
        w.render(w.facade.refresh('p', 'e'))
        w.facade._snapshot = lambda *_: {'state': 'pending'}
        w.render(w.facade.refresh('p', 'e'))
        self.assertEqual([w.references.item(i).text() for i in range(w.references.count())], ['ref-a.png'])
        w.facade._snapshot = lambda *_: {'state': 'pending', 'reference_slots': []}
        w.render(w.facade.refresh('p', 'e'))
        self.assertEqual(w.references.count(), 0)

    def test_render_snapshot_without_reference_authority_preserves_existing_state(self):
        from orquestador.ui.main_window import MainWindow
        snap_a = ExecutionSnapshot('p', 'a', 'pending', reference_slots=('ref-a.png',))
        class NoReferenceAuthority:
            can_start = False; busy = False; state = 'pending'; errors = (); chunks = ()
            supported_parameters = (); artifacts = (); can_cancel = can_retry = can_resume = can_recover = can_assemble = False
        w = MainWindow(GuiFacade(snapshot=lambda *_: snap_a)); self.addCleanup(w.close)
        w.render(snap_a); w.render(NoReferenceAuthority())
        self.assertEqual(w.references.count(), 1)
        self.assertEqual(w.references.item(0).text(), 'ref-a.png')

    def test_prompt_identity_survives_reorder_duplicate_remove_and_reopen(self):
        from orquestador.ui.main_window import MainWindow
        ids = ['A-id', 'B-id', 'C-id']
        def snap(order, prompts, overrides=None):
            return ExecutionSnapshot('p','e','pending', chunks=tuple(
                ChunkSnapshot(i, 'pending', chunk_id=cid, prompt=prompts[cid], overrides=tuple((str(k),v) for k,v in (overrides or {}).get(cid,{}).items()))
                for i, cid in enumerate(order)), can_start=True)
        prompts = {'A-id':'A', 'B-id':'B', 'C-id':'C'}
        overrides = {'A-id': {'steps':18}, 'B-id': {'fps':30}}
        current = snap(ids, prompts, overrides); calls=[]
        f = GuiFacade(snapshot=lambda *_: current,
                      sequence_edit=lambda *a, **k: calls.append(k) or OperationResult(True, current))
        w = MainWindow(f); self.addCleanup(w.close); w.project.setText('p'); w.execution.setText('e'); w.render(current)
        w._run = lambda op, *_a, **_k: op()
        w.chunk_tabs.setCurrentIndex(1); calls.clear()
        reordered = snap(['C-id','A-id','B-id'], prompts, overrides); w.render(reordered)
        self.assertEqual(w._sequence_ids, ['C-id','A-id','B-id'])
        self.assertEqual(w.chunk_tabs.currentIndex(), 2)
        self.assertEqual(w._selected_chunk_id(), 'B-id')
        self.assertEqual([e.toPlainText() for e in w.prompts], ['C','A','B'])
        self.assertEqual(w._drafts[1].overrides, {'steps':18})
        self.assertEqual([w.chunk_tabs.tabText(i) for i in range(3)], ['Chunk 1','Chunk 2','Chunk 3'])
        w.prompts[1]._chunk_id = 'A-id'; w.prompts[1].setPlainText('A-edited')
        # Prompt edits are intentionally debounced; no durable write occurs
        # per keystroke.  The final value is flushed by the timer/action path.
        self.assertEqual(calls, [])
        duplicated = snap(['C-id','A-id','D-id','B-id'], {**prompts,'D-id':'A'}, {**overrides,'D-id':{'steps':18}}); w.render(duplicated)
        self.assertEqual(w.prompts[2].toPlainText(), 'A')
        self.assertEqual(w.chunk_tabs.currentIndex(), 3)
        self.assertEqual(w._selected_chunk_id(), 'B-id')
        self.assertEqual(w._drafts[3].overrides, {'fps':30})
        removed = snap(['C-id','D-id','B-id'], {**prompts,'D-id':'A'}, {**overrides,'D-id':{'steps':18}}); w.render(removed)
        self.assertEqual(w.chunk_tabs.currentIndex(), 2)
        self.assertEqual(w._selected_chunk_id(), 'B-id')
        self.assertEqual([(cid,e.toPlainText()) for cid,e in zip(w._sequence_ids,w.prompts)], [('C-id','C'),('D-id','A'),('B-id','B')])

if __name__=='__main__': unittest.main()
