import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

from orquestador.application.f11_1b import derive_capabilities
from orquestador.domain.core import Lifecycle


class F111BCapabilityTests(unittest.TestCase):
    def execution(self, state, attempts=1):
        chunk = SimpleNamespace(state=state, attempts=[SimpleNamespace(state=Lifecycle.FAILED)
                                                        for _ in range(attempts)])
        return SimpleNamespace(state=state, chunks=[chunk])

    def test_retry_matrix_is_bounded_and_terminal_only(self):
        eligible = derive_capabilities(self.execution(Lifecycle.FAILED), retryable=True)
        self.assertTrue(eligible.can_retry)
        self.assertFalse(derive_capabilities(self.execution(Lifecycle.FAILED), retryable=False).can_retry)
        for state in (Lifecycle.CANCELLED, Lifecycle.RUNNING, Lifecycle.PENDING,
                      Lifecycle.SUCCEEDED, Lifecycle.UNKNOWN):
            self.assertFalse(derive_capabilities(self.execution(state), retryable=True).can_retry)

    def test_other_capabilities_remain_derived(self):
        caps = derive_capabilities(self.execution(Lifecycle.FAILED),
                                   retryable=True, can_cancel_candidate=True)
        self.assertTrue(caps.can_retry)
        self.assertTrue(caps.can_cancel)
        self.assertTrue(caps.can_resume)
        self.assertTrue(caps.can_recover)

    def test_productive_snapshot_computes_retryable_before_canonical_derivation(self):
        tree = ast.parse(Path('src/orquestador/ui/app.py').read_text(encoding='utf-8'))
        snapshot = next(n for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef) and n.name == '_snapshot_for_repo')
        assigns = [n for n in snapshot.body if isinstance(n, ast.Assign)]
        retry_index = next(i for i, n in enumerate(assigns)
                           if any(isinstance(t, ast.Name) and t.id == 'retryable' for t in n.targets))
        derive_index = next(i for i, n in enumerate(assigns)
                            if any(isinstance(x, ast.Name) and x.id == 'caps'
                                   for x in n.targets))
        self.assertLess(retry_index, derive_index)
        derive = assigns[derive_index].value
        retry_kw = next(k for k in derive.keywords if k.arg == 'retryable')
        self.assertIsInstance(retry_kw.value, ast.Name)
        self.assertEqual(retry_kw.value.id, 'retryable')
        self.assertFalse(any(isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Attribute) and t.attr == 'can_retry' for t in n.targets)
            for n in snapshot.body))


if __name__ == '__main__':
    unittest.main()
