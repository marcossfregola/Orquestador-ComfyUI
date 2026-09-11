import inspect, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen'); os.environ.setdefault('PYTHONDONTWRITEBYTECODE','1')
from orquestador.ui.app import AppConfig, StartupConfigurationError, compose, parse_config
from orquestador.persistence.sqlite import SQLiteProjectRepository
from orquestador.adapters.http import ComfyUIClient
from orquestador.adapters.cancellation import ComfyUICancellationAdapter
from orquestador.adapters.assembly import FFmpegAssemblyAdapter
from orquestador.application.chain_execution import ChainExecutionUseCase
from orquestador.application.recover_execution import ResumeExecutionUseCase, RecoverExecutionUseCase, RetryExecutionUseCase
from orquestador.application.assembly import AssembleExecutionUseCase
class CompositionTests(unittest.TestCase):
 def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name).resolve(); self.config=AppConfig(self.root)
 def tearDown(self):
  if hasattr(self,'repo'):
   try: self.repo.close()
   except Exception: pass
  self.tmp.cleanup()
 def _compose(self):
  f,r=compose(self.config); self.repo=r['repository']; return f,r
 def test_parser_required_and_absolute(self):
  with self.assertRaises(SystemExit): parse_config([])
  with self.assertRaises(StartupConfigurationError): AppConfig(Path('relative')).check()
 def test_config_template_and_defaults(self):
  t=self.root/'workflow.json'; t.write_text('{}'); c=parse_config(['--project-root',str(self.root),'--workflow-template',str(t)])
  self.assertEqual(c.workflow_template,t); self.assertEqual(c.comfyui_endpoint,'http://127.0.0.1:8188'); self.assertEqual(c.ffmpeg,'ffmpeg')
 def test_missing_template_fails_closed(self):
  with self.assertRaises(StartupConfigurationError): AppConfig(self.root,workflow_template=self.root/'missing.json').check()
 def test_real_sqlite_repository(self):
  _,r=self._compose(); self.assertIsInstance(r['repository'],SQLiteProjectRepository); r['repository'].close()
 def test_real_client_cancel_without_contact(self):
  with patch.object(ComfyUIClient,'health',side_effect=AssertionError) as h: _,r=self._compose()
  self.assertIsInstance(r['client'],ComfyUIClient); self.assertIsInstance(r['cancellation'],ComfyUICancellationAdapter); h.assert_not_called(); r['repository'].close()
 def test_real_chain_stack(self):
  _,r=self._compose(); self.assertIsInstance(r['chain'],ChainExecutionUseCase); self.assertTrue(hasattr(r['coordinator'],'execute')); r['repository'].close()
 def test_real_resume_recover_distinct_retry(self):
  _,r=self._compose(); self.assertIsInstance(r['resume'],ResumeExecutionUseCase); self.assertIsInstance(r['recover'],RecoverExecutionUseCase); self.assertIsInstance(r['retry'],RetryExecutionUseCase); self.assertIsNot(r['retry'],r['resume']); self.assertIs(r['retry'].resume_usecase,r['resume']); r['repository'].close()
 def test_real_assembly_no_ffmpeg(self):
  with patch('subprocess.run',side_effect=AssertionError) as run: _,r=self._compose()
  self.assertIsInstance(r['assembler'],FFmpegAssemblyAdapter); self.assertIsInstance(r['assemble'],AssembleExecutionUseCase); run.assert_not_called(); r['repository'].close()
 def test_facade_routes(self):
  f,r=self._compose()
  for n in ('start_chain','resume_execution','recover_execution','retry_execution','cancel_pending','assemble','refresh'): self.assertTrue(callable(getattr(f,n)))
  self.assertEqual(f._ops['chain'].__name__, 'start_chain'); self.assertEqual(f._ops['retry'].__name__, 'retry_route'); r['repository'].close()
 def test_compose_zero_external_calls(self):
  with patch.object(ComfyUIClient,'health',side_effect=AssertionError),patch.object(ComfyUIClient,'history',side_effect=AssertionError),patch('subprocess.run',side_effect=AssertionError) as run: _,r=self._compose()
  run.assert_not_called(); r['repository'].close()
 def test_snapshot_missing_fails_closed(self):
  f,r=self._compose(); self.assertEqual(f.refresh('missing').state,'error'); r['repository'].close()
 def test_entrypoint_import_side_effect_free(self):
  with patch('orquestador.ui.app.compose',side_effect=AssertionError): __import__('orquestador.__main__')
if __name__=='__main__': unittest.main()





