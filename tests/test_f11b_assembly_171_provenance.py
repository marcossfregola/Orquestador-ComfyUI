import tempfile
import unittest
from pathlib import Path
from orquestador.application.assembly import (AssembleExecutionUseCase, AssemblySource,
    AssemblySourceRoot)

class _A:
    def __init__(self): self.calls=[]
    def assemble(self, s, d, **k): self.calls.append((s,d)); return d

class AssemblyProvenance171Tests(unittest.TestCase):
    def test_duplicate_roots_are_disambiguated_by_descriptor(self):
        with tempfile.TemporaryDirectory() as td:
            b=Path(td); p=b/'project'; c=b/'comfy'; (p/'video').mkdir(parents=True); (c/'video').mkdir(parents=True)
            for r, data in ((p,b'project'),(c,b'comfy')):
                (r/'video'/'MiniMax_H3_00261_.mp4').write_bytes(data)
                (r/'video'/'MiniMax_H3_00262_.mp4').write_bytes(data)
            a=_A(); u=AssembleExecutionUseCase(a,p,(p,c)); d=b/'final.mp4'
            self.assertTrue(u.execute([AssemblySource('video/MiniMax_H3_00261_.mp4',AssemblySourceRoot.PROJECT_DURABLE),AssemblySource('video/MiniMax_H3_00262_.mp4',AssemblySourceRoot.PROJECT_DURABLE)],d).success)
            self.assertTrue(all(str(x).startswith(str(p)) for x in a.calls[0][0]))
            self.assertTrue(u.execute([AssemblySource('video/MiniMax_H3_00261_.mp4',AssemblySourceRoot.COMFY_OUTPUT),AssemblySource('video/MiniMax_H3_00262_.mp4',AssemblySourceRoot.COMFY_OUTPUT)],b/'c.mp4').success)
            self.assertTrue(all(str(x).startswith(str(c)) for x in a.calls[1][0]))
            self.assertFalse(u.execute(['video/MiniMax_H3_00261_.mp4','video/MiniMax_H3_00262_.mp4'],b/'legacy.mp4').success)
    def test_declared_root_rejects_wrong_absolute_and_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            b=Path(td); p=b/'p'; c=b/'c'; p.mkdir(); c.mkdir(); (p/'x.mp4').write_bytes(b'x'); (c/'x.mp4').write_bytes(b'c'); a=_A(); u=AssembleExecutionUseCase(a,p,(p,c))
            self.assertFalse(u.execute([AssemblySource(c/'x.mp4',AssemblySourceRoot.PROJECT_DURABLE)]*2,b/'o.mp4').success)
            self.assertFalse(u.execute([AssemblySource('../x.mp4',AssemblySourceRoot.PROJECT_DURABLE)]*2,b/'o2.mp4').success)

if __name__ == '__main__': unittest.main()
