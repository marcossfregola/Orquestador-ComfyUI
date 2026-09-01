import ast, unittest
from pathlib import Path
class BoundaryTests(unittest.TestCase):
    def test_ui_has_no_infrastructure_imports_and_core_no_qt(self):
        root=Path(__file__).parents[1]/'src'/'orquestador'; forbidden={'sqlite3','subprocess','requests','httpx','urllib','websocket','websockets'}
        for p in (root/'ui').glob('*.py'):
            t=ast.parse(p.read_text()); names={n.name.split('.')[0] for n in ast.walk(t) if isinstance(n,ast.Import) for n in n.names}
            names|={n.module.split('.')[0] for n in ast.walk(t) if isinstance(n,ast.ImportFrom) and n.level==0 and n.module}
            self.assertFalse(names & forbidden, (p,names&forbidden))
        for p in (root/'application').glob('*.py'):
            self.assertNotIn('PySide6',p.read_text())
    def test_no_fake_progress(self):
        text=''.join(p.read_text().lower() for p in (Path(__file__).parents[1]/'src'/'orquestador'/'ui').glob('*.py'))
        self.assertNotIn('eta',text); self.assertNotIn('percent',text)
if __name__=='__main__': unittest.main()
