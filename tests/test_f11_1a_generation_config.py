import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from orquestador.application.prepare_gui import PrepareGuiUseCase
from orquestador.application.start_gui_chain import StartGuiChainUseCase, StartPreparationError
from orquestador.domain.config import GenerationConfig, GenerationConfigError
from orquestador.domain.core import Project, ProjectId
from orquestador.persistence.sqlite import SQLiteProjectRepository
from orquestador.profiles.minimax_h3 import (
    H3_PROFILE,
    WorkflowProfileError,
    bind_inputs,
    load_api_template,
)


def valid_values(**updates):
    values = {
        "profile_ref": H3_PROFILE.name,
        "initial_image": "inputs/initial.png",
        "references": [f"inputs/ref-{index}.png" for index in range(6)],
        "chunk_count": 2,
        "prompts": ["first prompt", "second prompt"],
    }
    values.update(updates)
    return values


class GenerationConfigTests(unittest.TestCase):
    def test_defaults_and_round_trip(self):
        config = GenerationConfig.from_mapping(valid_values())
        self.assertEqual(config.megapixels, 0.6)
        self.assertEqual(config.length, 294)
        self.assertEqual(config.steps, 20)
        self.assertEqual(config.fps, 24)
        self.assertEqual(config.ref_image_size, "match")
        self.assertFalse(config.also_ref_first_frame)
        self.assertEqual(config.orchestration_timeout_seconds, 1800)
        self.assertEqual(config, GenerationConfig.from_json(config.to_json()))
        self.assertEqual(json.loads(config.to_json())["references"], list(config.references))

    def test_two_and_three_chunks(self):
        two = GenerationConfig.from_mapping(valid_values())
        three = GenerationConfig.from_mapping(
            valid_values(chunk_count=3, prompts=["one", "two", "three"])
        )
        self.assertEqual((two.chunk_count, len(two.prompts)), (2, 2))
        self.assertEqual((three.chunk_count, len(three.prompts)), (3, 3))

    def test_invalid_shape_and_prompts(self):
        for count, prompts in ((1, ["one"]), (4, ["a", "b", "c", "d"])):
            with self.subTest(count=count):
                with self.assertRaises(GenerationConfigError):
                    GenerationConfig.from_mapping(valid_values(chunk_count=count, prompts=prompts))
        for references in ([], ["only"] * 5, ["too-many"] * 7):
            with self.subTest(references=len(references)):
                with self.assertRaises(GenerationConfigError):
                    GenerationConfig.from_mapping(valid_values(references=references))
        for prompts in (["", "valid"], ["valid", "   "], ["only"]):
            with self.subTest(prompts=prompts):
                with self.assertRaises(GenerationConfigError):
                    GenerationConfig.from_mapping(valid_values(prompts=prompts))

    def test_numeric_validation_is_fail_closed(self):
        for value in (0, -1, math.nan, math.inf, -math.inf):
            with self.subTest(megapixels=value):
                with self.assertRaises(GenerationConfigError):
                    GenerationConfig.from_mapping(valid_values(megapixels=value))
        for name in ("length", "steps", "fps", "orchestration_timeout_seconds"):
            for value in (0, -1, 1.5, True, False):
                with self.subTest(name=name, value=value):
                    with self.assertRaises(GenerationConfigError):
                        GenerationConfig.from_mapping(valid_values(**{name: value}))
        with self.assertRaises(GenerationConfigError):
            GenerationConfig.from_mapping(valid_values(ref_image_size="512"))
        with self.assertRaises(GenerationConfigError):
            GenerationConfig.from_mapping(valid_values(also_ref_first_frame=1))

    def test_unsupported_keys_and_profile_fail_explicitly(self):
        for key in ("seed", "sampler", "scheduler", "width", "height", "unknown"):
            with self.subTest(key=key):
                with self.assertRaises(GenerationConfigError):
                    GenerationConfig.from_mapping(valid_values(**{key: 1}))
        with self.assertRaises(GenerationConfigError):
            GenerationConfig.from_mapping(valid_values(profile_ref="other-profile"))

    def test_scope_precedence_is_project_execution_chunk(self):
        project = valid_values(length=10, megapixels=0.2)
        execution = {"length": 20, "megapixels": 0.3}
        chunk = {"length": 30, "megapixels": 0.4}
        execution_config = GenerationConfig.from_scopes(project, execution)
        effective = GenerationConfig.from_mapping(
            {**execution_config.to_mapping(), **chunk}, strict=True
        )
        self.assertEqual((execution_config.length, execution_config.megapixels), (20, 0.3))
        self.assertEqual((effective.length, effective.megapixels), (30, 0.4))


class H3BindingTests(unittest.TestCase):
    def test_public_bindings_target_expected_nodes_without_mutating_template(self):
        template = load_api_template()
        original = copy.deepcopy(template)
        refs = [f"orquestador/static/ref-{index}.png" for index in range(6)]
        bound = bind_inputs(
            template,
            prompt="bound prompt",
            first_frame="orquestador/static/initial.png",
            references=refs,
            megapixels=0.4,
            length=123,
            steps=7,
            fps=15,
            ref_image_size="match",
            also_ref_first_frame=False,
        )
        self.assertEqual(template, original)
        self.assertEqual(bound["114"]["inputs"]["image"], "orquestador/static/initial.png")
        self.assertEqual(bound["129"]["inputs"]["first_frame"], ["119", 0])
        self.assertEqual(bound["119"]["inputs"]["megapixels"], 0.4)
        self.assertEqual(bound["146"]["inputs"]["steps"], 7)
        self.assertEqual(bound["129"]["inputs"]["length"], 123)
        self.assertEqual(bound["148"]["inputs"]["fps"], 15)
        self.assertEqual(
            [bound[str(node)]["inputs"]["image"] for node in (130, 131, 132, 150, 151, 152)],
            refs,
        )

    def test_seed_sampler_scheduler_are_not_public_bindings(self):
        template = load_api_template()
        for key in ("seed", "sampler", "scheduler"):
            with self.subTest(key=key):
                with self.assertRaises(WorkflowProfileError):
                    bind_inputs(template, prompt="prompt", **{key: 1})


class PersistenceAndPrecedenceTests(unittest.TestCase):
    def _assets(self, root):
        initial = root / "start.png"
        initial.write_bytes(b"start")
        refs = []
        for index in range(6):
            path = root / f"ref-{index}.png"
            path.write_bytes(f"ref-{index}".encode())
            refs.append(str(path))
        return initial, refs

    def test_save_close_reopen_and_project_edit_preserve_execution_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initial, refs = self._assets(root)
            repository = SQLiteProjectRepository(root)
            repository.save(
                Project(ProjectId("p"), {"length": 77, "megapixels": 0.42, "steps": 9, "fps": 17}),
                [],
            )
            prepare = PrepareGuiUseCase(repository, root, lambda project_id, execution_id: (project_id, execution_id))
            result = prepare(
                project_id="p",
                execution_id="e",
                initial_image=str(initial),
                prompts=["one", "two"],
                references=refs,
            )
            self.assertEqual(result, ("p", "e"))
            repository.close()

            reopened = SQLiteProjectRepository(root)
            project, executions = reopened.load("p")
            execution = executions[0]
            self.assertEqual(execution.defaults["length"], 77)
            self.assertEqual(GenerationConfig.from_scopes(project.defaults, execution.defaults).length, 77)
            project.defaults = {"length": 999}
            reopened.save(project, [execution])
            project2, executions2 = reopened.load("p")
            self.assertEqual(GenerationConfig.from_scopes(project2.defaults, executions2[0].defaults).length, 77)
            reopened.close()

    def test_start_resolves_authorized_chunk_override_only(self):
        class Chain:
            def __init__(self):
                self.prompts = None

            def run(self, project, execution, prompts, **kwargs):
                self.prompts = prompts
                return {"state": "submitted"}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initial, refs = self._assets(root)
            repository = SQLiteProjectRepository(root)
            repository.save(
                Project(
                    ProjectId("p"),
                    {"length": 77, "megapixels": 0.42, "steps": 9, "fps": 17},
                ),
                [],
            )
            prepare = PrepareGuiUseCase(repository, root, lambda project_id, execution_id: (project_id, execution_id))
            prepare(
                project_id="p",
                execution_id="e",
                initial_image=str(initial),
                prompts=["one", "two"],
                references=refs,
            )
            project, executions = repository.load("p")
            executions[0].chunks[1].defaults = {"length": 333}
            project.defaults = {"length": 999}
            repository.save(project, executions)
            chain = Chain()
            start = StartGuiChainUseCase(
                repository,
                root,
                chain,
                materializer=lambda paths: ["initial-upload", *[f"ref-upload-{i}" for i in range(6)]],
            )
            result = start("p", "e")
            self.assertEqual(result["state"], "submitted")
            self.assertEqual(chain.prompts[0]["129"]["inputs"]["prompt"], "one")
            self.assertEqual(chain.prompts[1]["129"]["inputs"]["prompt"], "two")
            self.assertEqual(chain.prompts[0]["119"]["inputs"]["megapixels"], 0.42)
            self.assertEqual(chain.prompts[1]["119"]["inputs"]["megapixels"], 0.42)
            self.assertEqual(chain.prompts[0]["129"]["inputs"]["length"], 77)
            self.assertEqual(chain.prompts[1]["129"]["inputs"]["length"], 333)
            self.assertEqual(chain.prompts[0]["146"]["inputs"]["steps"], 9)
            self.assertEqual(chain.prompts[1]["146"]["inputs"]["steps"], 9)
            self.assertEqual(chain.prompts[0]["148"]["inputs"]["fps"], 17)
            self.assertEqual(chain.prompts[1]["148"]["inputs"]["fps"], 17)
            durable_before = dict(repository.load("p")[1][0].defaults)
            with self.assertRaises(StartPreparationError):
                start("p", "e", prompts=["transient A", "transient B"])
            with self.assertRaises(StartPreparationError):
                start("p", "e", length=123)
            with self.assertRaises(StartPreparationError):
                start("p", "e", initial_image="inputs/other.png")
            with self.assertRaises(StartPreparationError):
                start("p", "e", references=["inputs/other.png"] * 6)
            self.assertEqual(dict(repository.load("p")[1][0].defaults), durable_before)
            self.assertEqual(chain.prompts[0]["129"]["inputs"]["prompt"], "one")
            repository.close()


if __name__ == "__main__":
    unittest.main()
