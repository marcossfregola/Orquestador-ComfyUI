import json, sqlite3, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from orquestador.application.clone_configuration import CloneConfigurationUseCase
from orquestador.application.drafts import DraftUseCase
from orquestador.application.global_defaults import GlobalDefaultsUseCase
from orquestador.application.technical_presets import TechnicalPresetError, TechnicalPresetsUseCase
from orquestador.domain.config import GLOBAL_DEFAULT_KEYS, GlobalDefaults
from orquestador.domain import Lifecycle, ProjectId
from orquestador.persistence import SQLiteProjectRepository

class F134TechnicalPresetsTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.root=Path(self.temp.name)
  self.repo=SQLiteProjectRepository(self.root); self.presets=TechnicalPresetsUseCase(self.repo); self.drafts=DraftUseCase(self.repo)
 def tearDown(self): self.repo.close(); self.temp.cleanup()
 def mapping(self,**more): return {**GlobalDefaults().to_mapping(),**more}
 def draft(self,ident='draft'):
  return self.drafts.create('p',execution_id=ident,defaults={'label':'opaque','profile_ref':'minimax-h3-ui'},chunks=[{'prompt':'one'},{'prompt':'two','steps':27}])
 def full_draft(self,ident='full'):
  return self.drafts.create('full',execution_id=ident,defaults={
   'initial_image':'inputs/source.png','references':('inputs/reference.png',),
   'prompts':('one','two'),'chunk_count':2,'profile_ref':'minimax-h3-ui',
   'label':'opaque','metadata':{'preserve':True},
  },chunks=[{'prompt':'one'},{'prompt':'two','steps':27}])
 def test_exact_mapping_names_crud_and_reopen(self):
  for bad in ({}, {'steps':22}, {**self.mapping(),'profile_ref':'x'}, {**self.mapping(),'seed':1}):
   with self.assertRaises(TechnicalPresetError): self.presets.create('x',bad)
  first=self.presets.create('  Caf\u00e9  ',self.mapping(steps=31),preset_id='opaque-id')
  self.assertEqual(first.name,'Caf\u00e9'); self.assertEqual(first.id,'opaque-id'); self.assertEqual(set(first.mapping),GLOBAL_DEFAULT_KEYS)
  with self.assertRaises(TechnicalPresetError): self.presets.create('CAFE\u0301',self.mapping())
  changed=self.presets.update(first.id,self.mapping(fps=12)); renamed=self.presets.rename(first.id,' Fast ')
  self.assertEqual(changed.mapping['fps'],12); self.assertGreaterEqual(changed.updated_at,changed.created_at); self.assertEqual(renamed.name,'Fast'); self.repo.close(); self.repo=SQLiteProjectRepository(self.root); self.presets=TechnicalPresetsUseCase(self.repo)
  self.assertEqual(self.presets.read('opaque-id').mapping['fps'],12); self.presets.delete('opaque-id'); self.assertEqual(self.presets.list(),())
 def test_default_is_atomic_and_never_auto_applies(self):
  a=self.presets.create('a',self.mapping(steps=31),is_default=True); b=self.presets.create('b',self.mapping(fps=12))
  self.presets.set_default(b.id); self.assertEqual([x.id for x in self.presets.list() if x.is_default],[b.id]); self.presets.clear_default(); self.assertFalse(any(x.is_default for x in self.presets.list()))
  created=self.draft(); self.assertEqual(created.defaults['steps'],20)
 def test_apply_by_copy_preserves_full_snapshot_and_is_nonretroactive(self):
  preset=self.presets.create('p',self.mapping(steps=31,fps=12)); created=self.full_draft()
  before=dict(created.defaults)
  applied=self.presets.apply(preset.id,'full',created.execution_id)
  expected={**before,**preset.mapping}
  self.assertEqual(applied.defaults,expected); self.assertEqual(applied.defaults['initial_image'],'inputs/source.png'); self.assertEqual(applied.defaults['references'],['inputs/reference.png']); self.assertEqual(applied.defaults['label'],'opaque'); self.assertEqual(applied.defaults['metadata'],{'preserve':True}); self.assertEqual(applied.defaults['profile_ref'],'minimax-h3-ui'); self.assertEqual(applied.chunks,created.chunks); self.assertNotIn('preset_id',applied.defaults); self.assertNotIn('technical_preset_id',applied.defaults)
  _,executions=self.repo.load(ProjectId('full')); execution=next(item for item in executions if str(item.id)==created.execution_id); self.assertEqual(execution.workflow_profile_ref.value,'minimax-h3-ui')
  self.presets.update(preset.id,self.mapping(steps=42)); self.presets.delete(preset.id)
  self.assertEqual(self.drafts.reopen('full',created.execution_id).defaults,expected)
 def test_apply_rejects_live_queue_or_runtime_evidence(self):
  preset=self.presets.create('p',self.mapping()); created=self.draft()
  self.repo.db.execute("INSERT INTO queue_items VALUES('q',?,0,'queued','2020-01-01T00:00:00+00:00','2020-01-01T00:00:00+00:00',NULL)",(created.execution_id,))
  with self.assertRaises(TechnicalPresetError): self.presets.apply(preset.id,'p',created.execution_id)
  runtime=self.draft('runtime'); project,executions=self.repo.load(ProjectId('p')); execution=next(item for item in executions if str(item.id)==runtime.execution_id); execution.transition(Lifecycle.RUNNING); execution.chunks[0].new_attempt(); self.repo.save(project,[execution])
  with self.assertRaises(TechnicalPresetError): self.presets.apply(preset.id,'p',runtime.execution_id)
 def test_migration_and_corruption_fail_closed(self):
  expected_globals=self.mapping(steps=31); GlobalDefaultsUseCase(self.repo).update(expected_globals); history=self.draft('history'); history_defaults=dict(history.defaults)
  self.repo.close(); db=sqlite3.connect(self.root/'orquestador.sqlite3'); db.execute('DROP TABLE technical_presets'); db.execute('DROP TABLE chunk_templates'); db.execute('UPDATE schema_version SET version=5'); db.commit(); db.close()
  self.repo=SQLiteProjectRepository(self.root); self.assertEqual(self.repo.db.execute('SELECT version FROM schema_version').fetchone()[0],7); self.presets=TechnicalPresetsUseCase(self.repo)
  self.assertEqual(self.repo.load_global_defaults().to_mapping(),expected_globals); self.assertEqual(DraftUseCase(self.repo).reopen('p',history.execution_id).defaults,history_defaults); self.assertEqual(self.presets.list(),())
  self.repo.db.execute("INSERT INTO technical_presets VALUES('bad','bad','bad','{}',1,0,'x','x')")
  with self.assertRaises(TechnicalPresetError): self.presets.list()
 def test_corrupt_identity_name_key_and_timestamps_fail_closed(self):
  timestamp='2026-01-01T00:00:00+00:00'
  mapping=json.dumps(self.mapping(),sort_keys=True,separators=(',',':'))
  cases=(
   (sqlite3.Binary(b'id'), 'valid', 'valid', timestamp, timestamp),
   ('', 'valid', 'valid', timestamp, timestamp),
   ('   ', 'valid', 'valid', timestamp, timestamp),
   ('id', '', '', timestamp, timestamp),
   ('id', ' padded ', 'padded', timestamp, timestamp),
   ('id', 'Cafe\u0301', 'caf\u00e9', timestamp, timestamp),
   ('id', 'valid', 'wrong-key', timestamp, timestamp),
   ('id', 'valid', 'valid', 'invalid', timestamp),
   ('id', 'valid', 'valid', '2026-01-01T00:00:00', timestamp),
   ('id', 'valid', 'valid', '2026-01-01T00:00:00+01:00', timestamp),
   ('id', 'valid', 'valid', '2026-01-02T00:00:00+00:00', timestamp),
  )
  for ident,name,key,created,updated in cases:
   with self.subTest(ident=ident,name=name,key=key,created=created,updated=updated):
    self.repo.db.execute('DELETE FROM technical_presets')
    self.repo.db.execute('PRAGMA ignore_check_constraints=ON')
    self.repo.db.execute('INSERT INTO technical_presets VALUES(?,?,?,?,?,?,?,?)',(ident,name,key,mapping,1,0,created,updated))
    self.repo.db.execute('PRAGMA ignore_check_constraints=OFF')
    with self.assertRaises(TechnicalPresetError): self.presets.list()
 def test_future_preset_config_version_fails_closed(self):
  mapping=json.dumps(self.mapping(),sort_keys=True,separators=(',',':'))
  self.repo.db.execute('PRAGMA ignore_check_constraints=ON')
  self.repo.db.execute("INSERT INTO technical_presets VALUES('future','future','future',?,2,0,'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')",(mapping,))
  self.repo.db.execute('PRAGMA ignore_check_constraints=OFF')
  with self.assertRaises(TechnicalPresetError): self.presets.list()
 def test_corrupt_default_value_and_duplicate_default_fail_closed(self):
  mapping=json.dumps(self.mapping(),sort_keys=True,separators=(',',':')); timestamp='2026-01-01T00:00:00+00:00'
  self.repo.db.execute('PRAGMA ignore_check_constraints=ON')
  self.repo.db.execute('INSERT INTO technical_presets VALUES(?,?,?,?,?,?,?,?)',('bad-default','bad-default','bad-default',mapping,1,'invalid',timestamp,timestamp))
  self.repo.db.execute('PRAGMA ignore_check_constraints=OFF')
  with self.assertRaises(TechnicalPresetError): self.presets.list()
  self.repo.db.execute('DELETE FROM technical_presets'); self.repo.db.execute('DROP INDEX technical_presets_one_default')
  self.repo.db.execute('INSERT INTO technical_presets VALUES(?,?,?,?,?,?,?,?)',('one','one','one',mapping,1,1,timestamp,timestamp)); self.repo.db.execute('INSERT INTO technical_presets VALUES(?,?,?,?,?,?,?,?)',('two','two','two',mapping,1,1,timestamp,timestamp))
  with self.assertRaises(TechnicalPresetError): self.presets.list()
 def test_forced_transaction_rollback_keeps_prior_default(self):
  first=self.presets.create('first',self.mapping(),is_default=True)
  self.repo.db.execute("CREATE TRIGGER reject_preset BEFORE INSERT ON technical_presets WHEN NEW.name='blocked' BEGIN SELECT RAISE(ABORT,'forced'); END")
  with self.assertRaises(TechnicalPresetError): self.presets.create('blocked',self.mapping(steps=31),is_default=True)
  remaining=self.presets.list(); self.assertEqual([(item.id,item.is_default) for item in remaining],[(first.id,True)])
 def test_clone_and_draft_creation_never_look_up_presets(self):
  with patch.object(self.repo,'list_technical_presets',side_effect=AssertionError('draft consulted presets')),patch.object(self.repo,'get_technical_preset',side_effect=AssertionError('draft consulted presets')):
   self.draft('no-preset')
  inputs=self.root/'inputs'; inputs.mkdir(); (inputs/'source.png').write_bytes(b'source'); (inputs/'reference.png').write_bytes(b'reference')
  source=self.full_draft('source')
  with patch.object(self.repo,'list_technical_presets',side_effect=AssertionError('clone consulted presets')),patch.object(self.repo,'get_technical_preset',side_effect=AssertionError('clone consulted presets')):
   CloneConfigurationUseCase(self.repo)('full',source.execution_id)

if __name__=='__main__': unittest.main()
