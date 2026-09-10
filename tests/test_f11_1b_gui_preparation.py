import unittest
from pathlib import Path
import tempfile
import shutil
import os
import time
from unittest.mock import Mock, patch

from orquestador.domain.config import (
    DEFAULT_FPS, DEFAULT_LENGTH, DEFAULT_MEGAPIXELS, DEFAULT_STEPS,
    DEFAULT_REF_IMAGE_SIZE, DEFAULT_ALSO_REF_FIRST_FRAME, GenerationConfig,
)
from orquestador.application.prepare_gui import PreflightGuiUseCase, PreparationError, effective_generation_config
from orquestador.profiles.minimax_h3 import H3_PROFILE
from orquestador.persistence.sqlite import PersistenceError
from orquestador.persistence.sqlite import SQLiteProjectRepository
from orquestador.domain.core import Project, ProjectId, Execution, ExecutionId, WorkflowProfileRef, Lifecycle, OutputRef, Evidence, Artifact, Phase, BackendJobRef
from orquestador.application.gui_facade import ExecutionSnapshot, OperationResult

class Repo:
    def load(self, project_id):
        raise PersistenceError("project not found")


class F111BGuiPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
    def test_authoritative_defaults_are_constructible_scalars(self):
        self.assertGreater(DEFAULT_MEGAPIXELS, 0)
        self.assertEqual(DEFAULT_LENGTH, 294)
        self.assertEqual(DEFAULT_STEPS, 20)
        self.assertEqual(DEFAULT_FPS, 24)
        with self.assertRaises(Exception):
            GenerationConfig()

    def setUp(self):
        base = Path(os.environ.get("ORQ_TEST_TMP", tempfile.gettempdir())).resolve()
        base.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="f111b-", dir=str(base)))
        self.files = []
        for i in range(8):
            p = self.root / f"{i}.png"; p.write_bytes(b"x"); self.files.append(str(p))
    def tearDown(self): shutil.rmtree(self.root, ignore_errors=True)
    def candidate(self, refs=None, prompts=None, count=2, initial_image=None):
        return dict(project_id="p", execution_id="e", initial_image=initial_image or self.files[0], references=refs or self.files[1:7], prompts=prompts or ["a"]*count, chunk_count=count, profile_ref=H3_PROFILE.name)
    def test_preflight_is_non_mutating_and_validates_files(self):
        repo=Mock(); repo.load.side_effect=PersistenceError("project not found"); repo.save=Mock()
        before=set(self.root.iterdir()); result=PreflightGuiUseCase(repo, self.root)(**self.candidate())
        self.assertTrue(result["valid"]); self.assertEqual(before,set(self.root.iterdir()))
        repo.save.assert_not_called(); repo.load.assert_called_once()

    def test_preflight_never_materializes_or_creates_entities(self):
        repo=Mock(); repo.load.side_effect=PersistenceError("project not found")
        with patch("orquestador.application.prepare_gui.Project") as project, patch("orquestador.application.prepare_gui.Execution") as execution:
            result=PreflightGuiUseCase(repo, self.root)(**self.candidate())
        self.assertTrue(result["valid"]); project.assert_not_called(); execution.assert_not_called()
    def test_reference_cardinality_rejected(self):
        use=PreflightGuiUseCase(Repo(), self.root)
        for n in (7,):
            with self.assertRaises(PreparationError): use(**self.candidate(refs=self.files[1:1+n]))
        for n in (0,1,6):
            self.assertTrue(use(**self.candidate(refs=self.files[1:1+n]))["valid"])
    def test_chunk_and_prompt_validation(self):
        use=PreflightGuiUseCase(Repo(), self.root)
        for count in (1,4):
            with self.assertRaises(PreparationError): use(**self.candidate(count=count, prompts=["a"]*count))
        with self.assertRaises(PreparationError): use(**self.candidate(prompts=["a", ""]))
    def test_missing_or_directory_inputs_rejected(self):
        use=PreflightGuiUseCase(Repo(), self.root)
        with self.assertRaises(PreparationError): use(**self.candidate(initial_image=str(self.root / "missing")))
        with self.assertRaises(PreparationError): use(**self.candidate(refs=[str(self.root)]*6))
    def test_precedence_merges_scopes(self):
        scopes=(
            {"initial_image":"project.png","references":["p0","p1","p2","p3","p4","p5"],"prompts":["pp1","pp2"],"chunk_count":2,"megapixels":1.0,"length":100,"steps":10,"fps":12},
            {"initial_image":"exec.png","references":["e0","e1","e2","e3","e4","e5"],"prompts":["ep1","ep2"],"chunk_count":3,"megapixels":2.0,"length":200,"steps":20,"fps":18},
            {"initial_image":"gui.png","references":["g0","g1","g2","g3","g4","g5"],"prompts":["gp1","gp2","gp3"],"chunk_count":3,"megapixels":3.0,"length":300,"steps":30,"fps":24},
        )
        value=effective_generation_config(*scopes)
        for name, expected in {"initial_image":"gui.png","references":tuple(scopes[2]["references"]),"prompts":tuple(scopes[2]["prompts"]),"chunk_count":3,"megapixels":3.0,"length":300,"steps":30,"fps":24}.items(): self.assertEqual(getattr(value,name),expected)

    def test_invalid_numeric_values_delegate_to_authoritative_config(self):
        use=PreflightGuiUseCase(Repo(), self.root)
        for kw in ({"length": True}, {"steps": 0}, {"fps": -1}, {"megapixels": float("nan")}, {"megapixels": float("inf")}):
            with self.subTest(kw=kw), self.assertRaises(PreparationError): use(**self.candidate(), **kw)

    def test_health_is_called_only_after_local_validation(self):
        from orquestador.ui.app import compose, AppConfig
        class Client:
            def __init__(self,*a): self.calls=0
            def health(self): self.calls += 1; return {"healthy": True}
        client=Client()
        class CF:
            def __new__(cls,*a): return client
        root=self.root / "health-local"; root.mkdir()
        facade,_=compose(AppConfig(root), client_factory=CF)
        result=facade.preflight(**self.candidate(refs=self.files[1:6]))
        self.assertTrue(result.success)
        self.assertEqual(client.calls, 1)

    def _window(self, snapshot=None):
        from orquestador.ui.main_window import MainWindow
        from orquestador.application.gui_facade import GuiFacade
        snap=snapshot or ExecutionSnapshot(state="pending")
        calls=[]
        facade=GuiFacade(snapshot=lambda *_: snap)
        facade.calls=calls
        facade.prepare=lambda **kw: calls.append(("prepare",kw)) or OperationResult(True, ExecutionSnapshot(state="pending",can_start=True), detail=kw)
        facade.preflight=lambda **kw: calls.append(("preflight",kw)) or OperationResult(True, ExecutionSnapshot(state="pending",can_start=True), detail=kw)
        facade.start_chain=lambda *a, **kw: calls.append(("start",a if a else kw)) or OperationResult(True, ExecutionSnapshot(state="running",can_start=False), detail=(a or kw))
        w=MainWindow(facade); w._test_calls=calls; w.show(); self.app.processEvents()
        return w

    def test_gui_J_six_reference_slots_replace_and_invalidate(self):
        w=self._window(); self.addCleanup(w.close)
        self.assertEqual(len(w.reference_buttons),6)
        values=[f"r{i}" for i in range(6)]; w.references.addItems(values)
        with patch("orquestador.ui.main_window.QFileDialog.getOpenFileName", return_value=("replacement", "")):
            w._choose_reference(3)
        self.assertEqual([w.references.item(i).text() for i in range(6)], values[:3]+["replacement"]+values[4:])
        w._prepared_key=w._form_key(); w._auth_can_start=True; w._update_start(); self.assertTrue(w.start.isEnabled())
        with patch("orquestador.ui.main_window.QFileDialog.getOpenFileName", return_value=("new", "")): w._choose_reference(0)
        self.assertIsNone(w._prepared_key); self.assertFalse(w.start.isEnabled())

    def test_gui_K_prompt_visibility_and_inputs(self):
        w=self._window(); self.addCleanup(w.close)
        w.chunk_count.setCurrentText("2"); self.app.processEvents(); self.assertFalse(w.prompts[2].isVisible()); self.assertFalse(w.prompts[2].isEnabled()); self.assertEqual(len(w._inputs()["prompts"]),2)
        w.chunk_count.setCurrentText("3"); self.app.processEvents(); w.prompts[2].setText("third"); self.assertTrue(w.prompts[2].isVisible()); self.assertTrue(w.prompts[2].isEnabled()); self.assertEqual(w._inputs()["prompts"], ["","","third"])
        w.chunk_count.setCurrentText("2"); self.app.processEvents(); self.assertFalse(w.prompts[2].isVisible()); self.assertFalse(w.prompts[2].isEnabled()); self.assertEqual(len(w._inputs()["prompts"]),2)

    def test_gui_M_out_of_scope_controls_absent(self):
        w=self._window(); self.addCleanup(w.close)
        for name in ("seed","sampler","scheduler","lens","manual_width","manual_height"):
            self.assertFalse(hasattr(w,name)); self.assertEqual(w.findChildren(type(w.start), name), [])
        for name in ("width", "height"):
            self.assertEqual(w.findChildren(type(w.start), name), [])

    def test_gui_f113_controls_defaults_inputs_and_capabilities(self):
        w=self._window(); self.addCleanup(w.close)
        self.assertTrue(hasattr(w, "ref_image_size")); self.assertTrue(hasattr(w, "also_ref_first_frame"))
        self.assertEqual(w.ref_image_size.currentText(), DEFAULT_REF_IMAGE_SIZE)
        self.assertEqual(DEFAULT_REF_IMAGE_SIZE, "match")
        self.assertFalse(w.also_ref_first_frame.isChecked())
        self.assertFalse(DEFAULT_ALSO_REF_FIRST_FRAME)
        self.assertEqual(w._inputs()["ref_image_size"], "match")
        self.assertEqual(w._inputs()["also_ref_first_frame"], False)
        w.also_ref_first_frame.setChecked(True)
        self.assertEqual(w._inputs()["also_ref_first_frame"], True)
        w.also_ref_first_frame.setChecked(False)
        self.assertEqual(w._inputs()["also_ref_first_frame"], False)

        from orquestador.application.f11_1b import derive_capabilities
        execution = type("Execution", (), {"state": "pending"})()
        capabilities = derive_capabilities(execution)
        self.assertEqual(capabilities.supported_parameters,
                         ("megapixels", "length", "steps", "fps", "ref_image_size", "also_ref_first_frame"))
        self.assertEqual(capabilities.reference_slots, ())

    def test_gui_f113_edits_invalidate_prepared_state_and_disable_start(self):
        w=self._window(); self.addCleanup(w.close)
        for edit in (
            lambda: w.ref_image_size.currentTextChanged.emit("match"),
            lambda: w.also_ref_first_frame.setChecked(not w.also_ref_first_frame.isChecked()),
        ):
            w._prepared_key=w._form_key(); w._auth_can_start=True; w._update_start(); self.assertTrue(w.start.isEnabled())
            edit(); self.assertIsNone(w._prepared_key); self.assertFalse(w.start.isEnabled())

    def test_gui_N_start_gating_and_no_implicit_prepare(self):
        w=self._window(); self.addCleanup(w.close); self.assertFalse(w.start.isEnabled())
        class _Noop:
            def deleteLater(self): pass
        def scheduled(op, kind="other"):
            w._operation_kind, w._busy = kind, True
            w._set_enabled(False)
            w._done(op())
            w._worker, w._thread = _Noop(), _Noop()
            w._cleanup()
        w._run = scheduled
        # A successful preflight result is not a preparation and cannot enable Start.
        w._preflight()
        self.assertIsNone(w._prepared_key); self.assertFalse(w.start.isEnabled())
        # Actual Prepare button route: current inputs reach facade.prepare and _done/render
        # establishes the prepared key only from a successful prepare result.
        w._prepare()
        self.assertEqual(w._test_calls[-1][0], "prepare")
        self.assertEqual(w._test_calls[-1][1], w._inputs())
        self.assertIsNotNone(w._prepared_key); self.assertTrue(w.start.isEnabled())

        # Form mismatch alone blocks Start, with signal invalidation temporarily bypassed.
        key=w._prepared_key; w._invalidate=lambda *_: None
        w.project.setText(w.project.text()+"mismatch"); w._prepared_key=key; w._update_start()
        self.assertFalse(w.start.isEnabled()); w._invalidate=lambda *_: (setattr(w,"_prepared_key",None), w._update_start())
        w._prepare(); self.assertTrue(w.start.isEnabled())

        edits=(
            ("project", lambda: w.project.setText(w.project.text()+"x")),
            ("execution", lambda: w.execution.setText(w.execution.text()+"x")),
            ("initial", lambda: w.initial.setText(w.initial.text()+"x")),
            ("chunk_count", lambda: w.chunk_count.setCurrentText("3")),
            ("megapixels", lambda: w.megapixels.setValue(w.megapixels.value()+1)),
            ("length", lambda: w.length.setValue(w.length.value()+1)),
            ("steps", lambda: w.steps.setValue(w.steps.value()+1)),
            ("fps", lambda: w.fps.setValue(w.fps.value()+1)),
        )
        for name, edit in edits:
            w._prepare(); self.assertTrue(w.start.isEnabled()); edit(); self.assertFalse(w.start.isEnabled(), name)
        for i in range(6):
            w._prepare(); self.assertTrue(w.start.isEnabled())
            with patch("orquestador.ui.main_window.QFileDialog.getOpenFileName", return_value=(f"ref-{i}", "")):
                w._choose_reference(i)
            self.assertFalse(w.start.isEnabled(), f"reference {i}")
        for i in range(3):
            w._prepare(); self.assertTrue(w.start.isEnabled()); w.prompts[i].setText(f"prompt-{i}"); self.assertFalse(w.start.isEnabled(), f"prompt {i}")

        w._prepare(); self.assertTrue(w.start.isEnabled())
        w.render(ExecutionSnapshot(state="pending", can_start=False)); self.assertFalse(w.start.isEnabled())
        w._prepare(); self.assertTrue(w.start.isEnabled()); w.render(ExecutionSnapshot(state="running", can_start=True, busy=True)); self.assertFalse(w.start.isEnabled()); w.render(ExecutionSnapshot(state="pending", can_start=True, busy=False)); self.assertTrue(w.start.isEnabled()); w._busy=True; w._update_start(); self.assertFalse(w.start.isEnabled()); w._busy=False
        w._prepare(); self.assertTrue(w.start.isEnabled()); w.render(ExecutionSnapshot(state="pending", can_start=False)); w._worker=_Noop(); w._thread=_Noop(); w._busy=False; w._cleanup(); self.assertFalse(w.start.isEnabled())

        w._prepare(); self.assertTrue(w.start.isEnabled()); before_counts={k:[c[0] for c in w._test_calls].count(k) for k in ("prepare","preflight")}
        w._start_chain(); self.assertEqual([c[0] for c in w._test_calls[-1:]], ["start"])
        self.assertEqual({k:[c[0] for c in w._test_calls].count(k) for k in before_counts}, before_counts)

    def test_gui_start_uses_prepared_selection_without_resending_source_paths(self):
        w=self._window(); self.addCleanup(w.close)
        w.project.setText("typed-project"); w.execution.setText("typed-execution")
        w.initial.setText(str(self.root / "absolute-initial.png"))
        w._prepared_key=w._form_key(); w._auth_can_start=True; w._update_start()
        # A durable prepare may canonicalize IDs; Start must hand off only that
        # selection, never the stale absolute form payload.
        w._prepared_selection=("durable-project", "durable-execution")
        w._run=lambda op, kind="other": op()
        w._start_chain()
        self.assertEqual(w._test_calls[-1], ("start", ("durable-project", "durable-execution")))

    def test_facade_start_failure_preserves_selected_context(self):
        from orquestador.application.gui_facade import GuiFacade
        facade=GuiFacade(chain=lambda *_a, **_k: (_ for _ in ()).throw(ValueError("durable mismatch")),
                         snapshot=lambda project_id, execution_id: {
                             "project_id": project_id, "execution_id": execution_id,
                             "state": "pending", "can_start": True})
        result=facade.start_chain("p", "e")
        self.assertFalse(result.success)
        self.assertEqual((result.snapshot.project_id, result.snapshot.execution_id), ("p", "e"))
        self.assertEqual(result.message, "durable mismatch")

    def test_facade_start_keyword_failure_preserves_selected_context_and_error(self):
        from orquestador.application.gui_facade import GuiFacade
        facade=GuiFacade(chain=lambda **_k: (_ for _ in ()).throw(ValueError("keyword mismatch")),
                         snapshot=lambda project_id, execution_id: {
                             "project_id": project_id, "execution_id": execution_id,
                             "state": "pending", "can_start": True})
        result=facade.start_chain(project_id="keyword-project", execution_id="keyword-execution")
        self.assertFalse(result.success)
        self.assertEqual((result.snapshot.project_id, result.snapshot.execution_id),
                         ("keyword-project", "keyword-execution"))
        self.assertEqual(result.message, "keyword mismatch")
        self.assertIsInstance(result.detail, ValueError)

    def test_gui_L_widget_defaults_use_authoritative_constants(self):
        w=self._window(); self.addCleanup(w.close)
        self.assertEqual(w.megapixels.value(), DEFAULT_MEGAPIXELS)
        self.assertEqual(w.length.value(), DEFAULT_LENGTH)
        self.assertEqual(w.steps.value(), DEFAULT_STEPS)
        self.assertEqual(w.fps.value(), DEFAULT_FPS)

    def test_gui_reference_rows_and_initial_confirmation_are_explicit(self):
        w=self._window(); self.addCleanup(w.close)
        self.assertEqual([x.text() for x in w.reference_labels], [f"Reference {i}: empty — choose a file" for i in range(1,7)])
        self.assertIn("empty", w.initial_confirmation.text())
        w.initial.setText(self.files[0]); self.assertIn(self.files[0], w.initial_confirmation.text())
        w.references.addItems(self.files[1:7]); w._update_reference_labels()
        self.assertIn(self.files[1], w.reference_labels[0].text())

    def test_gui_length_step_is_one(self):
        w=self._window(); self.addCleanup(w.close)
        self.assertEqual(w.length.singleStep(), DEFAULT_FPS)
        w.length.setValue(101); w.fps.setValue(30); self.app.processEvents()
        self.assertEqual(w.length.singleStep(), 30); self.assertEqual(w.length.value(), 101)

    def test_active_prompt_and_reference_order_are_exact(self):
        result=PreflightGuiUseCase(Repo(), self.root)(**self.candidate(count=3, prompts=["a","b","c"]))
        cfg=result["generation_config"]
        self.assertEqual(cfg["prompts"],["a","b","c"])
        self.assertEqual(cfg["references"],self.files[1:7])

    def test_h3_binding_compacts_zero_one_six_and_sparse_order(self):
        from orquestador.profiles.minimax_h3 import load_api_template, bind_inputs
        template = load_api_template()
        with self.assertRaises(Exception):
            bind_inputs(template, references=[f"r{i}" for i in range(7)])
        for n in (0, 1, 6):
            bound = bind_inputs(template, prompt="p", first_frame="f", references=[f"r{i}" for i in range(n)], megapixels=1.0, steps=20, width=1, height=1, length=24, ref_image_size="match", also_ref_first_frame=False, fps=24)
            keys = [k for k in bound["129"]["inputs"] if k.startswith("ref_images.ref_image_")]
            self.assertEqual(keys, [f"ref_images.ref_image_{i}" for i in range(n)])
            nodes = set(bound)
            for node in bound.values():
                for value in node["inputs"].values():
                    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str): self.assertIn(value[0], nodes)
            branch_ids = [(130,133,156),(131,134,157),(132,135,158),(150,153,159),(151,154,161),(152,155,160)]
            self.assertFalse(any(str(node) in nodes for branch in branch_ids[n:] for node in branch))
            self.assertFalse(any("dummy" in str(v).lower() for v in bound.values()))

    def test_sparse_reference_slots_use_gui_collection_boundary(self):
        from orquestador.ui.main_window import MainWindow
        class Facade:
            def refresh(self): return ExecutionSnapshot(state="pending", can_start=True)
        w = MainWindow(Facade()); self.addCleanup(w.close)
        w.references.addItem(self.files[1]); w.references.addItem(""); w.references.addItem(self.files[2])
        collected = w._inputs()["references"]
        self.assertEqual(collected, [self.files[1], self.files[2]])
        from orquestador.profiles.minimax_h3 import bind_inputs, load_api_template
        bound = bind_inputs(load_api_template(), references=collected)
        self.assertEqual([k for k in bound["129"]["inputs"] if k.startswith("ref_images.ref_image_")], ["ref_images.ref_image_0", "ref_images.ref_image_1"])

    def test_prepare_persists_and_reloads_zero_one_six_refs(self):
        from orquestador.application.prepare_gui import PrepareGuiUseCase
        for n in (0, 1, 6):
            root = Path(tempfile.mkdtemp(dir=str(self.root))); repo = SQLiteProjectRepository(root)
            try:
                result = PrepareGuiUseCase(repo, root, lambda p,e: {"project_id":p,"execution_id":e})(
                    project_id=f"p{n}", execution_id=f"e{n}", initial_image=self.files[0],
                    references=self.files[1:1+n], prompts=["a","b"], chunk_count=2)
                repo.close(); repo = SQLiteProjectRepository(root)
                _, executions = repo.load(f"p{n}"); self.assertEqual(executions[0].defaults["references"], [f"inputs/{i}.png" for i in range(1,1+n)])
            finally:
                repo.close(); shutil.rmtree(root, ignore_errors=True)

    def test_prepare_persists_and_reloads_exact_execution_snapshot(self):
        repo=SQLiteProjectRepository(self.root)
        try:
            snapshot=lambda p,e:{"project_id":p,"execution_id":e,"can_start":True,"state":"pending"}
            from orquestador.application.prepare_gui import PrepareGuiUseCase
            result=PrepareGuiUseCase(repo,self.root,snapshot)(**self.candidate(count=3,prompts=["a","b","c"]), megapixels=2.5,length=123,steps=17,fps=25)
            repo.close(); repo=SQLiteProjectRepository(self.root)
            project, executions=repo.load("p"); execution=next(x for x in executions if str(x.id)=="e")
            self.assertEqual(execution.defaults["initial_image"],"inputs/0.png")
            self.assertEqual(execution.defaults["references"],[f"inputs/{i}.png" for i in range(1,7)])
            for k,v in {"prompts":["a","b","c"],"chunk_count":3,"megapixels":2.5,"length":123,"steps":17,"fps":25}.items(): self.assertEqual(execution.defaults[k],v)
            self.assertEqual(len(execution.chunks),3); self.assertEqual(project.defaults,{})
        finally: repo.close()

    def _prepared(self, root, repo):
        from orquestador.application.prepare_gui import PrepareGuiUseCase
        return PrepareGuiUseCase(repo, root, lambda p,e:{"project_id":p,"execution_id":e})(project_id="p", execution_id="e", initial_image=self.files[0], references=self.files[1:7], prompts=["old","two"], chunk_count=2)

    def test_reprepare_before_start_reuses_id_and_replaces_snapshot(self):
        root = Path(tempfile.mkdtemp(dir=str(self.root))); repo = SQLiteProjectRepository(root)
        try:
            first=self._prepared(root,repo); second=self._prepared(root,repo)
            self.assertEqual(first["execution_id"], second["execution_id"])
            from orquestador.application.prepare_gui import PrepareGuiUseCase
            PrepareGuiUseCase(repo,root,lambda p,e:{"project_id":p,"execution_id":e})(project_id="p",execution_id="e",initial_image=self.files[0],references=self.files[1:2],prompts=["new","snapshot"],chunk_count=2)
            _,es=repo.load("p"); self.assertEqual(len(es),1); self.assertEqual(es[0].defaults["prompts"],["new","snapshot"]); self.assertEqual(es[0].defaults["references"],["inputs/1.png"])
        finally: repo.close(); shutil.rmtree(root,ignore_errors=True)

    def test_reprepare_rejected_for_attempt_external_job_artifact_and_started_state(self):
        from orquestador.application.prepare_gui import PrepareGuiUseCase, PreparationError
        for mode in ("attempt", "job", "artifact", "started"):
            root=Path(tempfile.mkdtemp(dir=str(self.root))); repo=SQLiteProjectRepository(root)
            try:
                self._prepared(root,repo); project,es=repo.load("p"); ex=es[0]; chunk=ex.chunks[0]
                artifacts=[]
                if mode in ("attempt","job","artifact"):
                    a=chunk.new_attempt()
                    if mode=="job": a.assign_external_job_ref(BackendJobRef("job-1"))
                    if mode=="artifact":
                        a.state=Lifecycle.SUCCEEDED; a.output=OutputRef("outputs/out.mp4"); a.evidence=Evidence("durable")
                        artifacts=[Artifact(ex.project_id,ex.id,chunk.id,a.id,Phase.OUTPUT,a.output)]
                if mode=="started": ex.state=Lifecycle.RUNNING
                repo.save(project,[ex],artifacts=artifacts)
                before=repr(repo.load("p"))
                with self.assertRaises(PreparationError):
                    PrepareGuiUseCase(repo,root,lambda p,e:{"project_id":p,"execution_id":e})(project_id="p",execution_id="e",initial_image=self.files[0],references=self.files[1:7],prompts=["new","snapshot"],chunk_count=2)
                self.assertEqual(before,repr(repo.load("p")))
            finally: repo.close(); shutil.rmtree(root,ignore_errors=True)

    def test_health_composition_differentiates_unhealthy_and_exception(self):
        from orquestador.ui.app import compose, AppConfig
        class Client:
            def __init__(self, mode): self.mode=mode; self.calls=0
            def health(self):
                self.calls+=1
                if isinstance(self.mode, Exception): raise self.mode
                return self.mode
        for mode, marker in [({"healthy":False},"unhealthy"),(RuntimeError("offline"),"failed")]:
            client=Client(mode)
            class CF:
                def __new__(cls,*a): return client
            root=self.root / marker; root.mkdir()
            facade,_=compose(AppConfig(root), client_factory=CF)
            bad=facade.preflight(**self.candidate(refs=self.files[1:6])); self.assertFalse(bad.success); self.assertEqual(client.calls,1)
            good=facade.preflight(**self.candidate())
            self.assertFalse(good.success); self.assertIn("health", good.message.lower()); self.assertEqual(client.calls,2)

    def test_real_worker_preflight_one_reference_fails_before_health(self):
        from orquestador.ui.app import compose, AppConfig
        from orquestador.ui.main_window import MainWindow
        class Client:
            def __init__(self,*a): self.calls=0
            def health(self): self.calls += 1; return {"healthy": True}
        client=Client()
        class CF:
            def __new__(cls,*a): return client
        facade, resources = compose(AppConfig(self.root), client_factory=CF)
        w=MainWindow(facade); self.addCleanup(w.close)
        w.project.setText("p"); w.execution.setText("e"); w.initial.setText(self.files[0]); w.references.addItem(self.files[1]); w._preflight()
        for _ in range(200):
            self.app.processEvents()
            if not w._busy: break
            time.sleep(0.01)
        self.assertFalse(w._busy); self.assertEqual(client.calls, 0)
        resources["repository"].close()

    def _wait_for_worker(self, window, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and (window._busy or window._thread is not None):
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        self.assertFalse(window._busy)
        self.assertIsNone(window._thread)

    def _real_window(self, client):
        from orquestador.ui.app import compose, AppConfig
        from orquestador.ui.main_window import MainWindow
        facade, resources = compose(AppConfig(self.root), client_factory=lambda endpoint: client)
        window = MainWindow(facade)
        self.addCleanup(window.close)
        self.addCleanup(resources["repository"].close)
        window.project.setText("p"); window.execution.setText("e")
        window.initial.setText(self.files[0]); window.references.addItems(self.files[1:7])
        window.chunk_count.setCurrentText("3")
        for edit, value in zip(window.prompts, ("first", "second", "third")): edit.setText(value)
        self.app.processEvents()
        return window

    def test_real_worker_prepare_success_persists_and_enables_start(self):
        class Client:
            def __init__(self, endpoint): self.health_calls = 0
            def health(self): self.health_calls += 1; return {"healthy": True}
        client = Client("unused")
        window = self._real_window(client)
        window._prepare()
        self._wait_for_worker(window)
        self.assertTrue(window.start.isEnabled())
        self.assertNotIn("sqlite", window.log.toPlainText().lower())
        verifier = SQLiteProjectRepository(self.root)
        try:
            project, executions = verifier.load("p")
            execution = next(e for e in executions if str(e.id) == "e")
            self.assertEqual(len(execution.chunks), 3)
            self.assertEqual(execution.defaults["prompts"], ["first", "second", "third"])
            self.assertEqual(len(execution.defaults["references"]), 6)
            self.assertEqual(execution.defaults["initial_image"], "inputs/0.png")
        finally:
            verifier.close()

    def test_real_worker_prepare_one_reference_is_valid_with_optional_cardinality(self):
        class Client:
            def __init__(self, endpoint): self.health_calls = 0
            def health(self): self.health_calls += 1; return {"healthy": True}
        client = Client("unused")
        from orquestador.ui.app import compose, AppConfig
        from orquestador.ui.main_window import MainWindow
        facade, resources = compose(AppConfig(self.root), client_factory=lambda endpoint: client)
        window = MainWindow(facade); self.addCleanup(window.close); self.addCleanup(resources["repository"].close)
        window.project.setText("p"); window.execution.setText("e"); window.initial.setText(self.files[0]); window.references.addItem(self.files[1])
        window.chunk_count.setCurrentText("2"); window.prompts[0].setText("one"); window.prompts[1].setText("two")
        window._prepare(); self._wait_for_worker(window)
        log = window.log.toPlainText().lower()
        self.assertNotIn("exactly six nonblank references are required", log)
        self.assertNotIn("sqlite", log); self.assertEqual(client.health_calls, 0); self.assertTrue(window.start.isEnabled())

    def test_real_worker_start_uses_worker_local_sqlite_repository(self):
        """Exercise the actual StartGuiChainUseCase through MainWindow/QThread.

        The chain runner is a controlled generation boundary; Start itself still
        performs durable SQLite loading, static materialization, workflow
        binding, and dispatches from the worker thread.
        """
        from orquestador.ui.app import compose, AppConfig

        class Client:
            def __init__(self, endpoint):
                self.health_calls = 0
                self.uploads = []
            def health(self):
                self.health_calls += 1
                return {"healthy": True}
            def upload_image(self, path, **kwargs):
                self.uploads.append((Path(path).name, kwargs))
                return {"type": "input", "name": kwargs["requested_filename"], "subfolder": kwargs["subfolder"]}

        from orquestador.application.chain_execution import ChainExecutionUseCase

        class ControlledChain(ChainExecutionUseCase):
            calls = []
            repositories = []
            orchestrators = []
            def __init__(self, repository, coordinator, recovery=None, orchestrator=None):
                super().__init__(repository, coordinator, recovery=recovery, orchestrator=orchestrator)
                ControlledChain.repositories.append(repository)
                ControlledChain.orchestrators.append(orchestrator)
            def run(self, project, execution, bound, **kwargs):
                ControlledChain.calls.append((str(project.id), str(execution.id), len(bound)))
                return type("Outcome", (), {"outcome": "complete", "execution_id": str(execution.id)})()

        client = Client("unused")
        with patch("orquestador.ui.app.ChainExecutionUseCase", ControlledChain):
            facade, resources = compose(AppConfig(self.root), client_factory=lambda endpoint: client)
            from orquestador.ui.main_window import MainWindow
            window = MainWindow(facade)
            self.addCleanup(window.close)
            self.addCleanup(resources["repository"].close)
            window.project.setText("p"); window.execution.setText("e")
            window.initial.setText(self.files[0]); window.references.addItems(self.files[1:3])
            window.chunk_count.setCurrentText("2")
            window.prompts[0].setText("first"); window.prompts[1].setText("second")
            window._prepare(); self._wait_for_worker(window)
            self.assertTrue(window.start.isEnabled())
            window._start_chain(); self._wait_for_worker(window)

        self.assertEqual(ControlledChain.calls, [("p", "e", 2)])
        self.assertEqual(len(ControlledChain.repositories), 2)
        self.assertIs(ControlledChain.repositories[0], resources["repository"])
        self.assertIsNot(ControlledChain.repositories[1], resources["repository"])
        self.assertIsNotNone(ControlledChain.orchestrators[1])
        self.assertEqual(len(client.uploads), 3)
        self.assertNotIn("sqlite", window.log.toPlainText().lower())
        self.assertNotIn("thread", window.log.toPlainText().lower())
        verifier = SQLiteProjectRepository(self.root)
        try:
            project, executions = verifier.load("p")
            self.assertEqual(str(project.id), "p")
            self.assertEqual(str(executions[0].id), "e")
        finally:
            verifier.close()


if __name__ == "__main__":
    unittest.main()
