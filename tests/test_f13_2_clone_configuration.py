import tempfile
import unittest
from pathlib import Path

from orquestador.application.clone_configuration import CloneConfigurationError, CloneConfigurationUseCase
from orquestador.domain import (
    Artifact, BackendJobRef, Chunk, Evidence, Execution, ExecutionId, Lifecycle,
    OutputRef, Phase, Project, ProjectId, WorkflowProfileRef,
)
from orquestador.domain.config import GenerationConfig
from orquestador.persistence import SQLiteProjectRepository


class F132CloneConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.directory.name)
        inputs = self.root / "inputs"
        inputs.mkdir()
        (inputs / "initial.png").write_bytes(b"initial")
        (inputs / "ref.png").write_bytes(b"reference")
        self.repository = SQLiteProjectRepository(self.root)
        self.clone = CloneConfigurationUseCase(self.repository)

    def tearDown(self):
        self.repository.close()
        self.directory.cleanup()

    def source(self, state=Lifecycle.PENDING):
        suffix = "" if state is Lifecycle.PENDING else "-" + state.value
        project = Project(ProjectId("source-project" + suffix), {"unrelated": "not copied"})
        config = GenerationConfig(
            initial_image="inputs/initial.png", references=("inputs/ref.png",),
            prompts=("first", "second"), chunk_count=2, megapixels=0.7,
            length=111, steps=22, fps=12, also_ref_first_frame=True,
        )
        execution = Execution(project.id, ExecutionId("source-execution" + suffix), config.to_mapping(), workflow_profile_ref=WorkflowProfileRef(config.profile_ref))
        execution.add_chunk(Chunk(order=0, defaults={"prompt": "override first", "steps": 23}))
        execution.add_chunk(Chunk(order=1, defaults={"fps": 13}))
        self.repository.save(project, [execution])
        if state is Lifecycle.FAILED:
            execution.transition(Lifecycle.RUNNING)
            execution.chunks[0].transition(Lifecycle.RUNNING)
            attempt = execution.chunks[0].new_attempt()
            attempt.assign_external_job_ref(BackendJobRef("prompt-id"))
            attempt.transition(Lifecycle.RUNNING)
            self.repository.save(project, [execution])
            attempt.transition(Lifecycle.FAILED)
            execution.chunks[0].transition(Lifecycle.FAILED)
            execution.transition(Lifecycle.FAILED)
        elif state is Lifecycle.SUCCEEDED:
            execution.transition(Lifecycle.RUNNING)
            for chunk in execution.chunks:
                chunk.transition(Lifecycle.RUNNING)
                attempt = chunk.new_attempt()
                attempt.assign_external_job_ref(BackendJobRef("prompt-" + str(chunk.order)))
                attempt.transition(Lifecycle.RUNNING)
            self.repository.save(project, [execution])
            for chunk in execution.chunks:
                attempt = chunk.attempts[0]
                attempt.transition(Lifecycle.SUCCEEDED, output=OutputRef("outputs/result-%s.mp4" % chunk.order), evidence=Evidence("verified"))
                chunk.transition(Lifecycle.SUCCEEDED)
            execution.transition(Lifecycle.SUCCEEDED)
        self.repository.save(project, [execution])
        if state is Lifecycle.SUCCEEDED:
            for chunk in execution.chunks:
                attempt = chunk.attempts[0]
                execution.artifacts.append(Artifact(project.id, execution.id, chunk.id, attempt.id, Phase.OUTPUT, attempt.output))
            self.repository.save(project, [execution], artifacts=execution.artifacts)
        return project, execution

    def test_copies_public_configuration_from_draft_succeeded_and_failed_without_runtime_evidence(self):
        for state in (Lifecycle.PENDING, Lifecycle.SUCCEEDED, Lifecycle.FAILED):
            with self.subTest(state=state):
                project, source = self.source(state)
                source_before = self.repository.load(project.id)
                result = self.clone(str(project.id), str(source.id))
                target_project, targets = self.repository.load(ProjectId(result.project_id))
                target = targets[0]
                self.assertEqual(result.execution_number, 1)
                self.assertEqual(target.workflow_profile_ref, source.workflow_profile_ref)
                self.assertEqual(dict(target_project.defaults), {})
                self.assertEqual(dict(target.defaults), GenerationConfig.from_scopes(project.defaults, source.defaults).to_mapping())
                self.assertEqual([dict(chunk.defaults) for chunk in target.chunks], [{"prompt": "override first", "steps": 23}, {"fps": 13}])
                self.assertEqual([chunk.order for chunk in target.chunks], [0, 1])
                self.assertNotEqual([chunk.id for chunk in target.chunks], [chunk.id for chunk in source.chunks])
                self.assertTrue(all(chunk.state is Lifecycle.PENDING and not chunk.attempts and chunk.first_frame is None for chunk in target.chunks))
                self.assertEqual(target.state, Lifecycle.PENDING)
                self.assertFalse(target.artifacts or target.errors)
                self.assertEqual(self.repository.load(project.id), source_before)

    def test_clone_and_source_are_independently_editable_or_historical(self):
        project, source = self.source()
        result = self.clone(str(project.id), str(source.id))
        _, targets = self.repository.load(ProjectId(result.project_id))
        targets[0].defaults = {**dict(targets[0].defaults), "steps": 99}
        targets[0].chunks[0].defaults = {"prompt": "changed"}
        self.repository.save(Project(ProjectId(result.project_id)), targets)
        _, originals = self.repository.load(project.id)
        self.assertEqual(originals[0].defaults["steps"], 22)
        self.assertEqual(originals[0].chunks[0].defaults["prompt"], "override first")

    def test_invalid_source_or_uncontained_input_fails_without_creating_target(self):
        project, source = self.source()
        source.defaults = {**dict(source.defaults), "initial_image": "../outside.png"}
        self.repository.save(project, [source])
        before = self.repository.list_project_ids()
        with self.assertRaises(CloneConfigurationError):
            self.clone(str(project.id), str(source.id))
        self.assertEqual(self.repository.list_project_ids(), before)

    def test_missing_contained_input_fails_closed_without_creating_target(self):
        project, source = self.source()
        source.defaults = {**dict(source.defaults), "initial_image": "inputs/missing.png"}
        self.repository.save(project, [source])
        before = self.repository.list_project_ids()
        with self.assertRaises(CloneConfigurationError):
            self.clone(str(project.id), str(source.id))
        self.assertEqual(self.repository.list_project_ids(), before)

    def test_contained_directory_fails_closed_without_creating_target(self):
        project, source = self.source()
        (self.root / "inputs" / "not-a-file").mkdir()
        source.defaults = {**dict(source.defaults), "initial_image": "inputs/not-a-file"}
        self.repository.save(project, [source])
        before = self.repository.list_project_ids()
        with self.assertRaises(CloneConfigurationError):
            self.clone(str(project.id), str(source.id))
        self.assertEqual(self.repository.list_project_ids(), before)

    def test_broken_or_escaping_symlink_fails_closed_when_supported(self):
        project, source = self.source()
        link = self.root / "inputs" / "linked.png"
        try:
            link.symlink_to(self.root.parent / "outside.png")
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        source.defaults = {**dict(source.defaults), "initial_image": "inputs/linked.png"}
        self.repository.save(project, [source])
        before = self.repository.list_project_ids()
        with self.assertRaises(CloneConfigurationError):
            self.clone(str(project.id), str(source.id))
        self.assertEqual(self.repository.list_project_ids(), before)

    def test_atomic_rollback_leaves_no_target_when_persistence_fails(self):
        project, source = self.source()
        self.repository.db.execute("CREATE TRIGGER abort_clone BEFORE INSERT ON chunks WHEN NEW.execution_id <> 'source-execution' BEGIN SELECT RAISE(ABORT, 'forced clone failure'); END")
        before = self.repository.list_project_ids()
        with self.assertRaises(CloneConfigurationError):
            self.clone(str(project.id), str(source.id))
        self.assertEqual(self.repository.list_project_ids(), before)


if __name__ == "__main__":
    unittest.main()
