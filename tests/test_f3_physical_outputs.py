import os
import shutil
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from orquestador.adapters import (
    BackendJobRef, OutputDescriptor, PhysicalOutputStatus, validate_physical_output,
)


class PhysicalOutputTests(unittest.TestCase):
    def setUp(self):
        configured = os.environ.get("ORQ_TEST_TMP", "").strip()
        if not configured:
            self.fail("ORQ_TEST_TMP must be set to an existing directory")
        root = Path(configured)
        if not root.is_dir():
            self.fail(f"ORQ_TEST_TMP must be an existing directory: {root}")
        self.base = root / f"physical_{self._testMethodName}"
        shutil.rmtree(self.base, ignore_errors=True)
        self.base.mkdir(parents=True)
        self.job = BackendJobRef("physical-job")

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def d(self, filename="clip.mp4", subfolder="nested", output_type="video"):
        return OutputDescriptor(self.job, "9", filename, subfolder, output_type)

    def test_exists_nested_and_empty_subfolder(self):
        (self.base / "nested").mkdir()
        (self.base / "nested" / "clip.mp4").write_bytes(b"x")
        ev = validate_physical_output(self.d(), self.base)
        self.assertEqual(ev.status, PhysicalOutputStatus.EXISTS)
        self.assertTrue(ev.resolved_path.is_relative_to(self.base.resolve()))
        empty = self.d(subfolder="")
        (self.base / "clip.mp4").write_bytes(b"")
        self.assertEqual(validate_physical_output(empty, self.base).status, PhysicalOutputStatus.EXISTS)

    def test_missing_not_file_unreadable_and_invalid_root(self):
        self.assertEqual(validate_physical_output(self.d(), self.base).status, PhysicalOutputStatus.MISSING)
        (self.base / "nested").mkdir()
        self.assertEqual(validate_physical_output(self.d(filename="nested", subfolder=""), self.base).status, PhysicalOutputStatus.NOT_FILE)
        (self.base / "nested" / "clip.mp4").write_bytes(b"x")
        with patch.object(Path, "open", side_effect=OSError("denied")):
            self.assertEqual(validate_physical_output(self.d(), self.base).status, PhysicalOutputStatus.UNREADABLE)
        self.assertEqual(validate_physical_output(self.d(), self.base / "missing").status, PhysicalOutputStatus.INVALID_ROOT)
        root_file = self.base / "root.txt"; root_file.write_text("x")
        self.assertEqual(validate_physical_output(self.d(), root_file).status, PhysicalOutputStatus.INVALID_ROOT)

    def test_containment_edges_and_opaque_type(self):
        (self.base / "safe").mkdir(); (self.base / "safe" / "a unicode name.mp4").write_bytes(b"x")
        desc = self.d(filename="a unicode name.mp4", subfolder="safe", output_type="opaque")
        ev = validate_physical_output(desc, self.base)
        self.assertEqual(ev.status, PhysicalOutputStatus.EXISTS); self.assertIs(ev.descriptor, desc)
        self.assertEqual(ev.descriptor.output_type, "opaque")
        for bad in ("..\\escape", "C:\\absolute.mp4", "/absolute.mp4"):
            edge = OutputDescriptor(self.job, "9", bad, "safe", "video")
            self.assertNotEqual(validate_physical_output(edge, self.base).status, PhysicalOutputStatus.EXISTS)
        outside = self.base.parent / "outside_containment"; shutil.rmtree(outside, ignore_errors=True); outside.mkdir(); (outside / "x").write_text("x")
        link = self.base / "link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            # Windows commonly denies symlink creation.  A directory junction
            # is equivalent for containment and normally needs no elevation.
            import subprocess
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                           check=False, capture_output=True, text=True)
        if link.is_dir():
            self.assertEqual(validate_physical_output(self.d(filename="x", subfolder="link"), self.base).status, PhysicalOutputStatus.OUTSIDE_ROOT)
        else:
            # Deterministic test-only fallback: resolve the external target
            # before patching and return it only for the exact candidate.
            resolved_outside = (outside / "x").resolve()
            original_resolve = Path.resolve
            candidate = link / "x"
            def resolve_edge(path, *args, **kwargs):
                if path == candidate:
                    return resolved_outside
                return original_resolve(path, *args, **kwargs)
            with patch.object(Path, "resolve", resolve_edge):
                self.assertEqual(validate_physical_output(self.d(filename="x", subfolder="link"), self.base).status, PhysicalOutputStatus.OUTSIDE_ROOT)

    def test_evidence_is_frozen(self):
        ev = validate_physical_output(self.d(), self.base)
        with self.assertRaises(FrozenInstanceError):
            ev.status = PhysicalOutputStatus.EXISTS


if __name__ == "__main__":
    unittest.main()
