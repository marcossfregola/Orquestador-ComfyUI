import os, unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from orquestador.ui.main_window import MainWindow
from orquestador.application.gui_facade import GuiFacade

class F9UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def test_controls_and_factual_render(self):
        f=GuiFacade(snapshot=lambda *_:{'state':'RUNNING','chunks':[{'order':1,'state':'RUNNING','attempt_ref':'a','error':'x','output':'o','transition':'t'}],'reference_slots':['ref1'],'supported_parameters':['width'],'can_cancel':False})
        w=MainWindow(f); w.show(); self.app.processEvents()
        self.assertTrue(w.project and w.execution and w.initial and w.prompts); self.assertEqual(w.references.count(),1); self.assertIn('width',w.parameters.text()); self.assertFalse(w.cancel.isEnabled()); self.assertFalse(hasattr(w,'seed')); self.assertIn('error=x',w.chunks.item(0).text()); w.close()

if __name__=='__main__': unittest.main()
