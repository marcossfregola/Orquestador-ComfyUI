import ast, io, re, tokenize, unittest
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
        def forbidden(source):
            bad={'eta','percent','percentage'}
            for tok in tokenize.generate_tokens(io.StringIO(source).readline):
                if tok.type == tokenize.STRING:
                    value=ast.literal_eval(tok.string)
                    if isinstance(value,str) and any(re.search(r'\b'+re.escape(w)+r'\b', value, re.I) for w in bad): return True
                elif tok.type == tokenize.NAME and tok.string.lower() in bad: return True
            return False
        self.assertFalse(forbidden('x = getattr(obj, "metadata")'))
        self.assertTrue(forbidden('label = "ETA: 3 seconds"'))
        text=''.join(p.read_text() for p in (Path(__file__).parents[1]/'src'/'orquestador'/'ui').glob('*.py'))
        self.assertFalse(forbidden(text))
if __name__=='__main__': unittest.main()
