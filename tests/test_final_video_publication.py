import tempfile
import unittest
from pathlib import Path

from orquestador.application.final_output import (
    FINAL_OUTPUT_FOLDER_KEY,
    FINAL_OUTPUT_FILENAME_KEY,
    FINAL_OUTPUT_NAME_MODE_KEY,
    FinalOutputConfigError,
    final_output_filename,
)
from orquestador.application.prepare_gui import (
    PrepareGuiUseCase,
    PreflightGuiUseCase,
    PreparationError,
)
from orquestador.domain.core import Project, ProjectId
from orquestador.persistence.sqlite import SQLiteProjectRepository


class FinalVideoPublicationPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root=Path(self.temp.name)
        self.input=self.root/"source.png"
        self.input.write_bytes(b"image")
        self.output=self.root/"finals"
        self.output.mkdir()
        self.repo=SQLiteProjectRepository(self.root)
        self.project=Project(ProjectId("project"),name="Mi Proyecto")
        self.repo.save(self.project,[])

    def tearDown(self):
        self.repo.close()
        self.temp.cleanup()

    def candidate(self, **updates):
        values=dict(
            project_id=str(self.project.id),
            execution_id=None,
            initial_image=str(self.input),
            references=[],
            prompts=["uno","dos"],
            chunk_count=2,
            final_output_folder=str(self.output),
            final_output_name="",
        )
        values.update(updates)
        return values

    def test_default_filename_uses_project_name_and_custom_name_is_normalized(self):
        self.assertEqual(final_output_filename("Mi Proyecto"),"Mi Proyecto.mp4")
        self.assertEqual(final_output_filename("Mi Proyecto","Entrega final"),"Entrega final.mp4")
        self.assertEqual(final_output_filename("Mi Proyecto","Entrega final.MP4"),"Entrega final.mp4")
        self.assertEqual(final_output_filename("Proyecto: prueba"),"Proyecto_ prueba.mp4")
        with self.assertRaises(FinalOutputConfigError):
            final_output_filename("Mi Proyecto","malo?.mp4")
        with self.assertRaises(FinalOutputConfigError):
            final_output_filename("Mi Proyecto","CON")

    def test_preflight_validates_final_destination_without_persisting(self):
        before=tuple(self.repo.load(self.project.id)[1])
        result=PreflightGuiUseCase(self.repo,self.root)(**self.candidate())
        self.assertTrue(result["valid"])
        after=tuple(self.repo.load(self.project.id)[1])
        self.assertEqual(after,before)
        with self.assertRaisesRegex(PreparationError,"invalid Windows"):
            PreflightGuiUseCase(self.repo,self.root)(
                **self.candidate(final_output_name="malo?.mp4")
            )
        with self.assertRaisesRegex(PreparationError,"does not exist"):
            PreflightGuiUseCase(self.repo,self.root)(
                **self.candidate(final_output_folder=str(self.root/"missing"))
            )

    def test_prepare_freezes_folder_and_resolved_filename_in_execution_defaults(self):
        use=PrepareGuiUseCase(self.repo,self.root,lambda *_: {"ok":True})
        use(**self.candidate())
        _,executions=self.repo.load(self.project.id)
        execution=executions[0]
        self.assertEqual(
            execution.defaults[FINAL_OUTPUT_FOLDER_KEY],
            str(self.output.resolve()),
        )
        self.assertEqual(
            execution.defaults[FINAL_OUTPUT_FILENAME_KEY],
            "Mi Proyecto.mp4",
        )
        self.assertEqual(
            execution.defaults[FINAL_OUTPUT_NAME_MODE_KEY],
            "project",
        )

        self.repo.rename_project(self.project.id, "Proyecto Renombrado")
        use(**self.candidate())
        _,executions=self.repo.load(self.project.id)
        execution=executions[0]
        self.assertEqual(
            execution.defaults[FINAL_OUTPUT_FILENAME_KEY],
            "Proyecto Renombrado.mp4",
        )
        self.assertEqual(
            execution.defaults[FINAL_OUTPUT_NAME_MODE_KEY],
            "project",
        )

        use(**self.candidate(final_output_name="Entrega final"))
        _,executions=self.repo.load(self.project.id)
        execution=executions[0]
        self.assertEqual(
            execution.defaults[FINAL_OUTPUT_FILENAME_KEY],
            "Entrega final.mp4",
        )
        self.assertEqual(
            execution.defaults[FINAL_OUTPUT_NAME_MODE_KEY],
            "custom",
        )

        self.repo.rename_project(self.project.id, "Otro nombre de proyecto")
        use(
            project_id=str(self.project.id),
            execution_id=None,
            initial_image=str(self.input),
            references=[],
            prompts=["uno","dos"],
            chunk_count=2,
            final_output_folder=str(self.output),
        )
        _,executions=self.repo.load(self.project.id)
        self.assertEqual(
            executions[0].defaults[FINAL_OUTPUT_FILENAME_KEY],
            "Entrega final.mp4",
        )
        self.assertEqual(
            executions[0].defaults[FINAL_OUTPUT_NAME_MODE_KEY],
            "custom",
        )

    def test_invalid_reprepare_does_not_replace_prior_publication_snapshot(self):
        use=PrepareGuiUseCase(self.repo,self.root,lambda *_: {"ok":True})
        use(**self.candidate(final_output_name="Valido"))
        before=dict(self.repo.load(self.project.id)[1][0].defaults)
        with self.assertRaises(PreparationError):
            use(**self.candidate(final_output_name="invalido*"))
        after=dict(self.repo.load(self.project.id)[1][0].defaults)
        self.assertEqual(after,before)


if __name__=="__main__":
    unittest.main()
