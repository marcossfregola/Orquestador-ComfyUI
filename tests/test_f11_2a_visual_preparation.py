import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from orquestador.application.create_reference_derivative import (
    CreateReferenceDerivativeUseCase, CropRectangle,
)


class F112AVisualPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        base = Path(os.environ.get("ORQ_TEST_TMP", r"C:\Codex\Orquestador-Test-Temp"))
        base.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="f112a-", dir=str(base)))
        self.source = self.root / "source.png"
        image = QImage(8, 6, QImage.Format_RGB32); image.fill(0x112233); self.assertTrue(image.save(str(self.source)))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_crop_dimensions_original_unchanged_and_destination_under_project(self):
        before = self.source.read_bytes(); digest = hashlib.sha256(before).hexdigest()
        result = CreateReferenceDerivativeUseCase(self.root)(self.source, CropRectangle(1, 2, 3, 4), 0)
        self.assertEqual(QImage(str(result.path)).size().width(), 3)
        self.assertEqual(QImage(str(result.path)).size().height(), 4)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), digest)
        self.assertTrue(result.path.resolve().is_relative_to((self.root / "derived" / "references").resolve()))

    def test_empty_and_reference_cardinality_and_order_operations(self):
        from orquestador.ui.main_window import MainWindow
        facade = Mock(); facade.refresh.return_value = Mock(state="Ready", can_start=False, busy=False, errors=[], chunks=[], reference_slots=[] , supported_parameters=[])
        w = MainWindow(facade); self.addCleanup(w.close)
        self.assertEqual(w._inputs()["references"], [])
        for n in range(6): self.assertTrue(w.add_reference(f"r{n}"))
        self.assertFalse(w.add_reference("r6"))
        self.assertTrue(w.replace_reference(2, "x")); self.assertTrue(w.remove_reference(1))
        self.assertEqual(w._inputs()["references"], ["r0", "x", "r3", "r4", "r5"])
        w._prepared_key = w._form_key(); w._auth_can_start = True; w._update_start(); self.assertTrue(w.start.isEnabled())
        w.remove_reference(0); self.assertFalse(w.start.isEnabled())

    def test_initial_preview_identifiable_and_parameters_passed_unchanged(self):
        from orquestador.ui.main_window import MainWindow
        facade = Mock(); facade.refresh.return_value = Mock(state="Ready", can_start=False, busy=False, errors=[], chunks=[], reference_slots=[], supported_parameters=[])
        w = MainWindow(facade); self.addCleanup(w.close)
        w.initial.setText(str(self.source)); self.app.processEvents()
        self.assertTrue(self.source.name in w.initial_confirmation.text() or not w.initial_confirmation.pixmap().isNull())
        self.assertEqual(w.initial_confirmation.toolTip(), str(self.source))
        w.references.addItems(["a", "b"]); w.prompts[0].setText("prompt"); w.prompts[1].setText("prompt2")
        inputs = w._inputs(); self.assertEqual(inputs["references"], ["a", "b"]); self.assertEqual(inputs["prompts"], ["prompt", "prompt2"])

    def test_invalid_crop_collision_and_root_escape_rejected(self):
        use = CreateReferenceDerivativeUseCase(self.root)
        for rect in (CropRectangle(-1, 0, 2, 2), CropRectangle(0, 0, 9, 2), CropRectangle(0, 0, 0, 1)):
            with self.assertRaises(ValueError): use(self.source, rect, 0)
        first = use(self.source, CropRectangle(0, 0, 2, 2), 0)
        first.path.write_bytes(b"collision")
        with self.assertRaises(ValueError): use(self.source, CropRectangle(0, 0, 2, 2), 0)
        outside = self.root.parent / (self.root.name + "-outside"); outside.mkdir(exist_ok=True)
        try:
            link = self.root / "derived" / "references"; link.parent.mkdir(); link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable on this Windows environment; lexical root validation remains covered")
        with self.assertRaises(ValueError): CreateReferenceDerivativeUseCase(self.root)

    def test_crop_destination_uses_configured_root_when_cwd_changes(self):
        from orquestador.ui.main_window import MainWindow
        import os
        facade = Mock(); facade.refresh.return_value = Mock(state="Ready", can_start=False, busy=False, errors=[], chunks=[], reference_slots=[] , supported_parameters=[])
        configured = self.root / "runtime"; configured.mkdir()
        w = MainWindow(facade, configured); self.addCleanup(w.close)
        w.references.addItem(str(self.source))
        class Dialog:
            def exec(self): return 1
            def rectangle(self): return CropRectangle(0, 0, 3, 2)
        old = Path.cwd()
        checkout_derived = old / "derived" / "references"
        before = {p.name for p in checkout_derived.glob("*")} if checkout_derived.exists() else set()
        try:
            os.chdir(str(self.root.parent))
            with patch("orquestador.ui.main_window._CropDialog", return_value=Dialog()):
                self.assertTrue(w.crop_reference(0))
        finally:
            os.chdir(str(old))
        result = Path(w.references.item(0).text())
        self.assertTrue(result.resolve().is_relative_to((configured / "derived" / "references").resolve()))
        self.assertTrue(result.exists())
        after = {p.name for p in checkout_derived.glob("*")} if checkout_derived.exists() else set()
        self.assertEqual(after, before)


if __name__ == "__main__": unittest.main()
