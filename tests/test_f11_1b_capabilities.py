import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from orquestador.application.f11_1b import derive_capabilities
from orquestador.application.recover_execution import RetryExecutionUseCase
from orquestador.domain.core import (
    Artifact,
    BackendJobRef,
    Chunk,
    ErrorRecord,
    Evidence,
    Execution,
    Lifecycle,
    OutputRef,
    Phase,
    Project,
    TransitionFrame,
)


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

    def test_retry_only_hides_resume_and_recover(self):
        caps = derive_capabilities(
            self.execution(Lifecycle.FAILED), retryable=True, retry_only=True
        )
        self.assertTrue(caps.can_retry)
        self.assertFalse(caps.can_resume)
        self.assertFalse(caps.can_recover)

    def test_staged_stale_retry_is_the_only_retry_capability_for_exact_shape(self):
        project = Project()
        execution = Execution(project.id)
        predecessor = Chunk(order=0)
        target = Chunk(order=1)
        execution.add_chunk(predecessor)
        execution.add_chunk(target)
        execution.transition(Lifecycle.RUNNING)
        predecessor.transition(Lifecycle.RUNNING)
        previous = predecessor.new_attempt()
        previous.transition(
            Lifecycle.RUNNING,
        )
        output = OutputRef("video/chunk1.mp4")
        previous.transition(Lifecycle.SUCCEEDED, output=output, evidence=Evidence("verified"))
        predecessor.transition(Lifecycle.SUCCEEDED)
        target.transition(Lifecycle.RUNNING)
        first = target.new_attempt()
        first.assign_external_job_ref(BackendJobRef("stale-ref"))
        first.transition(Lifecycle.RUNNING)
        first.transition(
            Lifecycle.FAILED,
            error=ErrorRecord("stale_external_job_not_found", "history was absent"),
        )
        target.transition(Lifecycle.FAILED)
        target.new_attempt()
        execution.transition(Lifecycle.FAILED)
        execution.artifacts = [
            Artifact(project.id, execution.id, predecessor.id, previous.id, Phase.OUTPUT, output)
        ]
        repo = Mock()
        repo.load_transitions.return_value = (
            TransitionFrame(
                project.id, execution.id, predecessor.id, previous.id,
                output, 9, 10, target.id,
            ),
        )
        usecase = RetryExecutionUseCase(repo, None)

        self.assertTrue(usecase.can_retry(execution, repository=repo))
        self.assertTrue(usecase.requires_explicit_retry(execution, repository=repo))

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
