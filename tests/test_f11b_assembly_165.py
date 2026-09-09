import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from orquestador.ui.main_window import MainWindow


class _Facade:
    def refresh(self):
        from orquestador.application.gui_facade import ExecutionSnapshot
        return ExecutionSnapshot()


class AssemblyBindingRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_save_destination_is_bound_after_durable_ids(self):
        facade = _Facade()
        calls = []
        facade.assemble = lambda *args: calls.append(args)
        window = MainWindow(facade)
        window.project.setText("f11b-e2e-160")
        window.execution.setText("f11b-e2e-160-001")
        window._run = lambda operation, kind="other": operation()
        with patch("orquestador.ui.main_window.QFileDialog.getSaveFileName", return_value=(r"C:\target\joined.mp4", "MP4")):
            window._assemble()
        self.assertEqual(calls, [("f11b-e2e-160", "f11b-e2e-160-001", r"C:\target\joined.mp4")])
        window.close()


if __name__ == "__main__":
    unittest.main()
