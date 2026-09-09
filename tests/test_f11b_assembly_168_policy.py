import tempfile
import unittest
from pathlib import Path

from orquestador.application.assembly import AssembleExecutionUseCase


class FakeAssembler:
    def __init__(self): self.calls = []
    def assemble(self, sources, destination, **kwargs):
        self.calls.append((sources, destination, kwargs)); return destination


class AssemblySourcePolicyTests(unittest.TestCase):
    def test_trusted_roots_and_destination_policy(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); project = base; comfy = base / 'comfy'; out = base / 'desktop'
            (project / 'project' / 'video').mkdir(parents=True); (comfy / 'video').mkdir(parents=True); out.mkdir()
            (project / 'project' / 'video' / 'a.mp4').write_bytes(b'a')
            (comfy / 'video' / 'b.mp4').write_bytes(b'b')
            fake = FakeAssembler(); use = AssembleExecutionUseCase(fake, project, (project, comfy))
            dest = out / 'final.mp4'
            result = use.execute(['project/video/a.mp4', 'video/b.mp4'], dest)
            self.assertTrue(result.success); self.assertEqual(fake.calls[0][1], dest.resolve())

    def test_absolute_roots_external_and_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); project = base/'p'; comfy = base/'c'; project.mkdir(); comfy.mkdir()
            a = project/'a.mp4'; b = comfy/'b.mp4'; ext = base/'x.mp4'
            a.write_bytes(b'a'); b.write_bytes(b'b'); ext.write_bytes(b'x')
            fake = FakeAssembler(); use = AssembleExecutionUseCase(fake, project, (project, comfy))
            self.assertTrue(use.execute([a, b], base/'ok.mp4').success)
            self.assertFalse(use.execute([ext, b], base/'bad.mp4').success)
            self.assertFalse(use.execute(['../x.mp4', b], base/'bad2.mp4').success)
            self.assertEqual(len(fake.calls), 1)

    def test_ambiguous_relative_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); p = base/'p'; c = base/'c'; p.mkdir(); c.mkdir()
            (p/'same.mp4').write_bytes(b'a'); (c/'same.mp4').write_bytes(b'b')
            fake = FakeAssembler(); result = AssembleExecutionUseCase(fake, p, (p, c)).execute(['same.mp4','same.mp4'], base/'x.mp4')
            self.assertFalse(result.success); self.assertFalse(fake.calls)

    def test_existing_destination_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td); a=p/'a'; b=p/'b'; a.write_bytes(b'a'); b.write_bytes(b'b'); d=p/'x.mp4'; d.write_bytes(b'x')
            fake=FakeAssembler(); result=AssembleExecutionUseCase(fake,p).execute([a,b],d)
            self.assertFalse(result.success); self.assertFalse(fake.calls)


if __name__ == '__main__': unittest.main()
