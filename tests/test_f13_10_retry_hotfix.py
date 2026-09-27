import json
from unittest import TestCase
from unittest.mock import Mock

from orquestador.adapters.http import ComfyUIRejectedError
from orquestador.application.recover_execution import RetryExecutionUseCase
from orquestador.application.bridge import SubmitOutcome
from orquestador.application.submit_boundary import SubmitBoundary
from orquestador.domain import (
    Artifact,
    BackendJobRef,
    Chunk,
    Evidence,
    ErrorRecord,
    Execution,
    Lifecycle,
    MaterializedInputRef,
    OutputRef,
    Phase,
    Project,
    TransitionFrame,
)
from orquestador.profiles.minimax_h3 import H3_PROFILE


class RetryHotfixTests(TestCase):
    def _state(self):
        project = Project()
        execution = Execution(project.id)
        references = [f"inputs/ref{i}.png" for i in range(4)]
        defaults = {
            "profile_ref": H3_PROFILE.name,
            "initial_image": "inputs/initial.png",
            "references": references,
            "prompts": ["chunk 1", "chunk 2"],
            "chunk_count": 2,
        }
        project.defaults = execution.defaults = defaults
        previous = Chunk(order=0)
        target = Chunk(order=1)
        execution.add_chunk(previous)
        execution.add_chunk(target)
        execution.transition(Lifecycle.RUNNING)
        previous.transition(Lifecycle.RUNNING)
        previous_attempt = previous.new_attempt()
        previous_attempt.assign_external_job_ref(BackendJobRef("chunk-1"))
        previous_output = OutputRef("outputs/chunk-1.mp4")
        previous_attempt.transition(Lifecycle.RUNNING)
        previous_attempt.transition(Lifecycle.SUCCEEDED, output=previous_output, evidence=Evidence("verified"))
        previous.transition(Lifecycle.SUCCEEDED)
        target.transition(Lifecycle.RUNNING)
        current = target.new_attempt()
        current.assign_external_job_ref(BackendJobRef("stale"))
        current.transition(Lifecycle.RUNNING)
        current.transition(Lifecycle.FAILED, error=ErrorRecord("stale_external_job_not_found", "history was absent"))
        target.transition(Lifecycle.FAILED)
        staged = target.new_attempt()
        execution.transition(Lifecycle.FAILED)
        artifact = Artifact(project.id, execution.id, previous.id, previous_attempt.id, Phase.OUTPUT, previous_output)
        transition = TransitionFrame(
            project.id,
            execution.id,
            previous.id,
            previous_attempt.id,
            previous_output,
            9,
            10,
            target.id,
            MaterializedInputRef("input", "orquestador/transitions", "transition.png", "0" * 64),
        )
        repo = Mock()
        repo.load.return_value = (project, [execution])
        repo.load_transitions.return_value = (transition,)
        return project, execution, target, staged, repo

    def test_retry_reuses_start_materialization_for_all_references(self):
        project, execution, target, _, repo = self._state()

        class RecordingMaterializer:
            def __init__(self):
                self.paths = None

            def __call__(self, paths):
                self.paths = list(paths)
                return [
                    "orquestador/static/initial.png",
                    "orquestador/static/ref-1.png",
                    "orquestador/static/ref-2.png",
                    "orquestador/static/ref-3.png",
                    "orquestador/static/ref-4.png",
                ]

        materializer = RecordingMaterializer()
        usecase = RetryExecutionUseCase(repo, None, materializer)
        prompt = usecase._reconstruct_prompt(project, execution, target)

        self.assertEqual(materializer.paths, ["inputs/initial.png", "inputs/ref0.png", "inputs/ref1.png", "inputs/ref2.png", "inputs/ref3.png"])
        self.assertEqual(prompt["114"]["inputs"]["image"], "orquestador/transitions/transition.png")
        self.assertEqual(prompt["130"]["inputs"]["image"], "orquestador/static/ref-1.png")
        self.assertEqual(prompt["131"]["inputs"]["image"], "orquestador/static/ref-2.png")
        self.assertEqual(prompt["132"]["inputs"]["image"], "orquestador/static/ref-3.png")
        self.assertEqual(prompt["150"]["inputs"]["image"], "orquestador/static/ref-4.png")

    def test_retry_rejection_keeps_http_status_and_compact_node_detail(self):
        project = Project()
        execution = Execution(project.id)
        chunk = Chunk(order=0)
        execution.add_chunk(chunk)
        attempt = chunk.new_attempt()
        body = json.dumps(
            {
                "error": {
                    "type": "prompt_outputs_failed_validation",
                    "message": "Prompt outputs failed validation",
                    "details": "large fallback detail",
                },
                "node_errors": {
                    "131": {
                        "class_type": "LoadImage",
                        "errors": [{"message": "Custom validation failed for node", "details": "Invalid image file: inputs/ref.png"}],
                    }
                },
            }
        )
        transport = Mock()
        transport.submit.side_effect = ComfyUIRejectedError("rejected", 400, body)
        result = SubmitBoundary(transport, repository=Mock()).submit_existing_pending_attempt(
            project, execution, chunk.id, attempt.id, {"prompt": "graph"}
        )

        self.assertEqual(result.outcome, SubmitOutcome.REJECTED)
        self.assertIn("status=400", result.error)
        self.assertIn("LoadImage 131: Invalid image file: inputs/ref.png", result.error)
        self.assertLess(len(result.error), 400)
        self.assertIsNone(attempt.external_job_ref)
        self.assertEqual(attempt.state, Lifecycle.PENDING)
        self.assertEqual(transport.submit.call_count, 1)


if __name__ == "__main__":
    import unittest

    unittest.main()
