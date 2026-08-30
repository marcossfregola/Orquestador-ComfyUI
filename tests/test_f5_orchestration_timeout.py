import copy
import unittest

from orquestador.domain.core import (
    Chunk, DomainError, Execution, ExecutionId, Project, ProjectId,
    resolve_orchestration_timeout_seconds,
)


class OrchestrationTimeoutResolutionTests(unittest.TestCase):
    def make_entities(self, project_defaults=None, execution_defaults=None, chunk_defaults=None):
        project = Project(ProjectId('p'), project_defaults or {})
        execution = Execution(project.id, ExecutionId('e'), execution_defaults or {})
        chunk = Chunk(defaults=chunk_defaults or {})
        execution.add_chunk(chunk)
        return project, execution, chunk

    def test_absent_defaults_to_1800(self):
        self.assertEqual(resolve_orchestration_timeout_seconds(*self.make_entities()), 1800)

    def test_precedence_project_execution_chunk(self):
        self.assertEqual(resolve_orchestration_timeout_seconds(*self.make_entities({'orchestration_timeout_seconds': 10})), 10)
        self.assertEqual(resolve_orchestration_timeout_seconds(*self.make_entities({'orchestration_timeout_seconds': 10}, {'orchestration_timeout_seconds': 20})), 20)
        self.assertEqual(resolve_orchestration_timeout_seconds(*self.make_entities({'orchestration_timeout_seconds': 10}, {'orchestration_timeout_seconds': 20}, {'orchestration_timeout_seconds': 30})), 30)

    def test_exact_positive_int_accepted(self):
        self.assertEqual(resolve_orchestration_timeout_seconds(*self.make_entities({'orchestration_timeout_seconds': 1})), 1)

    def test_invalid_values_fail_closed(self):
        for value in (True, False, '10', 1.0, 0, -1, None, {}, []):
            with self.subTest(value=value):
                with self.assertRaisesRegex(DomainError, 'orchestration_timeout_seconds'):
                    resolve_orchestration_timeout_seconds(*self.make_entities({'orchestration_timeout_seconds': value}))

    def test_unrelated_defaults_ignored_and_mappings_unchanged(self):
        project, execution, chunk = self.make_entities(
            {'orchestration_timeout_seconds': 10, 'other': 'p'},
            {'orchestration_timeout_seconds': 20, 'other': 'e'},
            {'orchestration_timeout_seconds': 30, 'other': 'c'})
        before = (dict(project.defaults), dict(execution.defaults), dict(chunk.defaults))
        self.assertEqual(resolve_orchestration_timeout_seconds(project, execution, chunk), 30)
        self.assertEqual(before, (dict(project.defaults), dict(execution.defaults), dict(chunk.defaults)))

    def test_resolution_leaves_real_attempt_unmodified(self):
        project, execution, chunk = self.make_entities({'orchestration_timeout_seconds': 10})
        attempt = chunk.new_attempt()
        before = copy.deepcopy(attempt)
        self.assertEqual(resolve_orchestration_timeout_seconds(project, execution, chunk), 10)
        self.assertEqual(attempt, before)


if __name__ == '__main__':
    unittest.main()
