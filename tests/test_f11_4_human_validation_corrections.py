import os, unittest, tempfile
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from PySide6.QtCore import Qt, QPoint, QThread
from PySide6.QtTest import QTest
from PySide6.QtGui import QImage
from orquestador.ui.main_window import MainWindow, _CropDialog
from orquestador.application.gui_facade import ExecutionSnapshot, OperationResult, ChunkSnapshot
from orquestador.application.prepare_gui import PrepareGuiUseCase, PreparationError
from orquestador.persistence.sqlite import SQLiteProjectRepository

class F114HumanValidationCorrections(unittest.TestCase):
 @classmethod
 def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
 def wait_idle(self,w,timeout=3000):
  import time
  end=time.monotonic()+timeout/1000
  while time.monotonic()<end and (w._busy or (w._thread is not None and w._thread.isRunning())): self.app.processEvents(); QTest.qWait(10)
  for _ in range(20): self.app.processEvents(); QTest.qWait(5)
  self.assertFalse(w._busy, f'busy={w._busy} thread={w._thread} running={w._thread.isRunning() if w._thread else None} calls pending={w._pending_action} cont={w._continuation}')
  self.assertIsNone(w._thread)
 def make(self):
  class F:
   def refresh(self): return ExecutionSnapshot('p','e','pending',chunks=())
  w=MainWindow(F()); self.addCleanup(w.close); return w
 def test_general_controls_have_explicit_labels(self):
  labels=' '.join(x.text() for x in self.make().findChildren(QLabel))
  for s in ('Megapixels','Length / Frames','Steps','FPS','Reference image size','Also reference first frame'): self.assertIn(s,labels)
 def test_direct_chunk_overrides_edit_draft_and_restore_inheritance(self):
  w=self.make(); w._ensure_prompt_count(); p=w.chunk_tabs.widget(0); untouched=dict(w._drafts[1].overrides)
  shown=lambda e: e.value() if hasattr(e,'value') else e.currentText() if hasattr(e,'currentText') else e.isChecked()
  for k in ('megapixels','length','steps','fps','ref_image_size','also_ref_first_frame'):
   t=getattr(p,f'chunk_{k}_override'); e=getattr(p,f'chunk_{k}_editor'); inherited=w._effective_value(0,k); self.assertEqual(shown(e),inherited); t.click(); self.assertEqual(w._effective_value(0,k),inherited); self.assertEqual(shown(e),inherited)
   if hasattr(e,'setValue'): e.setValue(inherited+1 if isinstance(inherited,int) else inherited+.1)
   elif hasattr(e,'setChecked'): e.setChecked(not inherited)
   self.assertIn(k,w._drafts[0].overrides); self.assertEqual(w._drafts[1].overrides,untouched); t.click(); self.assertNotIn(k,w._drafts[0].overrides); self.assertEqual(shown(e),inherited)
  w._drafts[0].overrides={'steps':18}; w._sync_draft_controls(); w.override_key.setCurrentText('prompt')
  p.findChild(QPushButton,'chunk_steps_restore').click()
  self.assertNotIn('steps',w._drafts[0].overrides); self.assertEqual(shown(p.chunk_steps_editor),w._general_value('steps'))
 def test_direct_durable_override_calls_sequence_once(self):
  w=self.make(); w._ensure_prompt_count(); w._sequence_ids=['c1','c2']; calls=[]; w._sequence_op=lambda *a,**k:calls.append((a,k)); p=w.chunk_tabs.widget(0)
  for k in ('megapixels','length','steps','fps','ref_image_size','also_ref_first_frame'):
   t=getattr(p,f'chunk_{k}_override'); t.click(); t.click()
  self.assertEqual(len(calls),12); self.assertTrue(all(c[0][1]=='c1' for c in calls)); self.assertEqual(sum(c[0][0]=='set_override' for c in calls),6)
 def test_local_sequence_buttons_clicks_preserve_prompt_and_overrides(self):
  w=self.make(); w.prompts[0].setPlainText('one'); w._drafts[0].overrides={'steps':18}; w._sync_draft_controls(); w.chunk_tabs.setCurrentIndex(0); source_id=w._drafts[0].draft_id; w.duplicate_button.click(); duplicate_id=w._drafts[1].draft_id; self.assertNotEqual(duplicate_id,source_id); self.assertEqual(w._drafts[1].prompt,'one'); self.assertEqual(w.prompts[1].toPlainText(),'one'); self.assertEqual(w._drafts[1].overrides,{'steps':18}); self.assertTrue(w.remove_chunk_button.isEnabled()); w.chunk_tabs.setCurrentIndex(1); self.assertTrue(w.move_up_button.isEnabled()); w.move_up_button.click(); self.assertEqual(w.chunk_tabs.currentIndex(),0); self.assertEqual(w._drafts[0].draft_id,duplicate_id); self.assertEqual(w.prompts[0].toPlainText(),'one'); self.assertEqual(w._drafts[0].overrides,{'steps':18}); w.remove_chunk_button.click(); self.assertEqual(len(w._drafts),2); self.assertFalse(w.remove_chunk_button.isEnabled())
 def test_prompt_preprepare_is_local_only(self):
  w=self.make(); w.prompts[0].setPlainText('local'); self.assertEqual(w._drafts[0].prompt,'local'); self.assertIsNone(w._prompt_dirty)
 def test_prompt_debounce_coalesces_to_one_durable_update(self):
  w=self.make(); w._sequence_ids=['c1','c2']; w.prompts[0]._chunk_id='c1'; w.prompts[0].setPlainText('a'); w.prompts[0].setPlainText('ab'); self.assertEqual(w._prompt_dirty,('c1','ab'))
 def _dirty_structural_case(self, button_name, expected, index, *, fail=False):
  calls=[]
  snap=lambda: ExecutionSnapshot('p','e','pending',chunks=tuple(ChunkSnapshot(i,'pending',chunk_id=f'c{i+1}') for i in range(3)))
  class F:
   def refresh(self,*a): return snap()
   def edit_sequence(self,*a,**kw):
    if kw['operation'] != 'read_provenance': calls.append((kw['operation'],kw.get('chunk_id'),kw.get('delta')))
    return OperationResult(not (fail and kw['operation']=='update_prompt'), snap(), 'injected failure' if fail else 'ok')
  w=MainWindow(F()); w.project.setText('p'); w.execution.setText('e'); w.render(snap())
  w.chunk_tabs.blockSignals(True); w.chunk_tabs.setCurrentIndex(index); w.render(snap()); w.chunk_tabs.blockSignals(False); w.prompts[index].setPlainText('dirty'); w._prompt_dirty=(f'c{index+1}','dirty')
  button={'add':w.add_chunk_button,'remove':w.remove_chunk_button,'up':w.move_up_button,'down':w.move_down_button,'dup':w.duplicate_button}[button_name]
  self.assertTrue(button.isEnabled())
  button.click(); self.wait_idle(w, timeout=3000)
  self.app.processEvents(); QTest.qWait(50)
  self.assertIsNone(w._thread); self.assertFalse(w._busy)
  if fail:
   self.assertEqual([x[0] for x in calls], ['update_prompt']); self.assertIsNone(w._pending_action); self.assertIsNone(w._continuation); self.assertIsNone(w._prompt_dirty)
  else:
   self.assertEqual(calls[0], ('update_prompt',f'c{index+1}',None)); self.assertEqual(calls[1][0], expected); self.assertEqual(len(calls),2)
  w.close(); self.app.processEvents(); QTest.qWait(20)

 def test_dirty_prompt_add_flushes_then_continues(self): self._dirty_structural_case('add','add',0)
 def test_dirty_prompt_remove_flushes_then_continues(self): self._dirty_structural_case('remove','remove',1)
 def test_dirty_prompt_move_up_flushes_then_continues(self): self._dirty_structural_case('up','move',1)
 def test_dirty_prompt_move_down_flushes_then_continues(self): self._dirty_structural_case('down','move',0)
 def test_dirty_prompt_duplicate_flushes_then_continues(self): self._dirty_structural_case('dup','duplicate',0)
 def test_dirty_prompt_flush_failure_clears_without_deferred_action(self): self._dirty_structural_case('add','add',0,fail=True)
 def test_prepare_overrides_survive_sqlite_reopen_with_provenance(self):
  with tempfile.TemporaryDirectory(dir=os.environ.get('ORQ_TEST_TMP')) as d:
   root=Path(d); img=root/'s.png'; QImage(8,8,QImage.Format_RGB32).save(str(img)); r=SQLiteProjectRepository(root); use=PrepareGuiUseCase(r,root,lambda p,e: ExecutionSnapshot(p,e,'pending')); use(project_id='p',execution_id='e',initial_image=str(img),prompts=['one','two'],chunk_count=2,chunk_overrides=[{'megapixels':.6,'steps':18},{'megapixels':.9,'steps':27}]); _,es=r.load('p'); ids=[str(c.id) for c in es[0].chunks]; r.close(); r=SQLiteProjectRepository(root); _,es=r.load('p'); self.assertEqual(ids,[str(c.id) for c in es[0].chunks]); self.assertEqual([c.defaults['prompt'] for c in es[0].chunks],['one','two']); self.assertEqual(es[0].chunks[1].defaults['steps'],27); r.close()
 def test_duplicate_draft_prepare_gets_distinct_durable_ids_and_same_values(self):
  w=self.make(); w._drafts[0].overrides={'steps':18,'megapixels':.6}; w.prompts[0].setPlainText('copy'); w.duplicate_button.click(); self.assertNotEqual(w._drafts[0].draft_id,w._drafts[1].draft_id); self.assertEqual(w._drafts[0].overrides,w._drafts[1].overrides)
 def test_invalid_chunk_override_is_fail_closed_without_partial_persistence(self):
  with tempfile.TemporaryDirectory(dir=os.environ.get('ORQ_TEST_TMP')) as d:
   root=Path(d); img=root/'s.png'; QImage(8,8,QImage.Format_RGB32).save(str(img)); r=SQLiteProjectRepository(root); u=PrepareGuiUseCase(r,root,lambda p,e: ExecutionSnapshot(p,e,'pending')); u(project_id='p',execution_id='e',initial_image=str(img),prompts=['one','two'],chunk_count=2); n=r.db.execute('select count(*) from chunks').fetchone()[0]; r.close()
   for bad in ({'bogus':1},{'steps':'x'}):
    r=SQLiteProjectRepository(root); u=PrepareGuiUseCase(r,root,lambda p,e: ExecutionSnapshot(p,e,'pending'))
    with self.assertRaises(PreparationError): u(project_id='bad',execution_id='bad',initial_image=str(img),prompts=['one','two'],chunk_count=2,chunk_overrides=[bad,{}])
    r.close(); r=SQLiteProjectRepository(root); self.assertEqual(r.db.execute('select count(*) from chunks').fetchone()[0],n); r.close()
 def _dlg(self):
  d=tempfile.mkdtemp(dir=os.environ.get('ORQ_TEST_TMP')); p=Path(d)/'i.png'; QImage(320,180,QImage.Format_RGB32).save(str(p)); x=_CropDialog(str(p)); x.show(); self.app.processEvents(); self.addCleanup(x.close); return x
 def test_crop_interactive_real_handles_and_ratios(self):
  d=self._dlg(); c=d.label.rect().center(); QTest.mousePress(d.label,Qt.LeftButton,pos=c-QPoint(50,30)); QTest.mouseMove(d.label,c+QPoint(50,30),20); QTest.mouseRelease(d.label,Qt.LeftButton,pos=c+QPoint(50,30)); self.assertIsNotNone(d.rectangle());
  for ratio in ('Manual','1:1','16:9'): d.ratio.setCurrentText(ratio); self.app.processEvents(); self.assertGreater(d.rubber.width(),0)
 def test_crop_whole_rect_move_and_mapping(self):
  d=self._dlg(); c=d.label.rect().center(); QTest.mousePress(d.label,Qt.LeftButton,pos=c-QPoint(40,20)); QTest.mouseMove(d.label,c+QPoint(40,20),20); QTest.mouseRelease(d.label,Qt.LeftButton,pos=c+QPoint(40,20)); old=d.rectangle(); s=d.rubber.geometry().center(); QTest.mousePress(d.label,Qt.LeftButton,pos=s); QTest.mouseMove(d.label,s+QPoint(30,10),20); QTest.mouseRelease(d.label,Qt.LeftButton,pos=s+QPoint(30,10)); new=d.rectangle(); self.assertGreaterEqual(new.x,old.x); self.assertLessEqual(new.x+new.width,320)
 def test_override_global_and_prompt_changes_invalidate_start_and_reprepare_restores_it(self):
  state={'n':0}; starts=[]
  class F:
   def refresh(self,*a): return ExecutionSnapshot(project_id='p',execution_id='e',state='ready',can_start=True)
   def prepare(self,**kw): state['n']+=1; return OperationResult(True,ExecutionSnapshot(project_id='p',execution_id='e',state='ready',can_start=True), 'prepared')
   def edit_sequence(self,*a,**kw): return OperationResult(True,ExecutionSnapshot(project_id='p',execution_id='e',state='ready',can_start=True),'flushed')
   def start_chain(self,*a): starts.append(1); return OperationResult(True,ExecutionSnapshot(project_id='p',execution_id='e',state='running'),'started')
  w=MainWindow(F()); self.addCleanup(w.close); w.project.setText('p'); w.execution.setText('e'); w._prepared_key=w._form_key(); w._auth_can_start=True; w._update_start(); self.assertTrue(w.start.isEnabled())
  w.megapixels.setValue(w.megapixels.value()+.1); self.assertFalse(w.start.isEnabled()); w.prepare.click()
  for _ in range(40): self.app.processEvents(); QTest.qWait(5)
  self.assertTrue(w.start.isEnabled()); page=w.chunk_tabs.widget(0); page.chunk_steps_override.click(); page.chunk_steps_editor.setValue(19); self.assertFalse(w.start.isEnabled()); w.prepare.click()
  for _ in range(40): self.app.processEvents(); QTest.qWait(5)
  w._prepared_key=w._form_key(); w._auth_can_start=True; w._update_start(); self.assertTrue(w.start.isEnabled()); self.assertEqual(w._drafts[0].overrides['steps'],19); w.prompts[0].setPlainText('dirty'); self.assertFalse(w.start.isEnabled()); w.prepare.click()
  for _ in range(80): self.app.processEvents(); QTest.qWait(5)
  self.assertTrue(w.start.isEnabled()); w.start.click();
  for _ in range(40): self.app.processEvents(); QTest.qWait(5)
  self.assertEqual(len(starts),1)
 def test_prepare_deferred_restore_does_not_bless_edit_and_reprepare_restores_start(self):
  calls=[]; deferred=[]
  prepared=ExecutionSnapshot(project_id='p',execution_id='e',state='ready',can_start=True)
  class F:
   def refresh(self,*a): return prepared
   def prepare(self,**kw): calls.append(dict(kw)); return OperationResult(True,prepared,'prepared')
  w=MainWindow(F()); self.addCleanup(w.close); w.project.setText('p'); w.execution.setText('e')
  with patch('orquestador.ui.main_window.QTimer.singleShot', side_effect=lambda _delay, callback: deferred.append(callback)):
   w._prepare(); self.wait_idle(w)
  self.assertEqual(len(calls),1); self.assertEqual(len(deferred),1); self.assertTrue(w.start.isEnabled())
  original_steps=w.steps.value(); self.assertEqual(calls[0]['steps'],original_steps)
  edited_steps=original_steps+1; w.steps.setValue(edited_steps)
  for _ in range(4): self.app.processEvents(); QTest.qWait(2)
  self.assertFalse(w.start.isEnabled())
  deferred.pop(0)(); self.app.processEvents()
  self.assertFalse(w.start.isEnabled()); self.assertIsNone(w._prepared_key)
  w.prepare.click(); self.wait_idle(w)
  for _ in range(4): self.app.processEvents(); QTest.qWait(2)
  self.assertEqual(len(calls),2); self.assertEqual(calls[1]['steps'],edited_steps); self.assertTrue(w.start.isEnabled())
 def test_refs_and_tabs_regression(self):
  w=self.make(); self.assertEqual([w.tabs.tabText(i) for i in range(3)],['Principal','Referencias','Chunks']); self.assertIs(w.ref_image_size.parentWidget(),w.tabs.widget(2)); self.assertIs(w.also_ref_first_frame.parentWidget(),w.tabs.widget(2))
 def test_f11_5_smoke_capability_gating_and_worker_boundary(self):
  gui=QThread.currentThread(); seen=[]; mode={'ok':True}
  chunks=tuple(ChunkSnapshot(i,'pending',chunk_id=f'c{i+1}') for i in range(3))
  class F:
   def refresh(self,*a): return ExecutionSnapshot(project_id='p',execution_id='e',state='ready',chunks=chunks,can_resume=True,can_retry=True,can_cancel=True,can_assemble=True)
   def resume_execution(self,*a): seen.append(('resume',QThread.currentThread())); return OperationResult(mode['ok'],ExecutionSnapshot(project_id='p',execution_id='e',state='done',chunks=chunks), 'resume fail' if not mode['ok'] else 'resume ok')
   retry_execution=resume_execution; cancel_pending=resume_execution; assemble=resume_execution
  for attr in ('resume','retry','cancel'):
   w=MainWindow(F()); self.addCleanup(w.close); w.project.setText('p'); w.execution.setText('e'); w.render(F().refresh()); b=getattr(w,attr); self.assertTrue(b.isEnabled()); b.click(); self.wait_idle(w); self.assertTrue(b.isEnabled() if attr == 'resume' else not b.isEnabled())
  self.assertEqual(len(seen),3); self.assertTrue(all(t is not gui for _,t in seen))
