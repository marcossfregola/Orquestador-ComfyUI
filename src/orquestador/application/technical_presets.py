"""F13.4 durable, installation-wide technical presets."""
from __future__ import annotations

import json
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from ..domain.config import GLOBAL_DEFAULT_KEYS, GlobalDefaults, GenerationConfigError
from ..domain.core import ProjectId
from ..persistence.sqlite import PersistenceError, PersistenceConflictError, PersistenceDataError
from .drafts import DraftUseCase, DraftError


class TechnicalPresetError(ValueError): pass

@dataclass(frozen=True)
class TechnicalPreset:
 id: str; name: str; mapping: dict; is_default: bool; created_at: datetime; updated_at: datetime

class TechnicalPresetsUseCase:
 def __init__(self, repository): self.repository=repository
 @staticmethod
 def _name(value):
  if not isinstance(value,str): raise TechnicalPresetError('preset name must be text')
  display=unicodedata.normalize('NFC',value.strip())
  if not display: raise TechnicalPresetError('preset name must be nonblank')
  return display,display.casefold()
 @staticmethod
 def _mapping(value):
  try:return GlobalDefaults.from_mapping(value).to_mapping()
  except GenerationConfigError as exc: raise TechnicalPresetError(f'invalid technical preset mapping: {exc}') from exc
 @staticmethod
 def _timestamp(value):
  try:
   parsed=datetime.fromisoformat(value)
   if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0): raise ValueError
   return parsed.astimezone(timezone.utc)
  except (TypeError,ValueError) as exc: raise TechnicalPresetError('invalid technical preset timestamp') from exc
 def _record(self,row):
  try:
   if not isinstance(row[0],str) or not row[0].strip(): raise ValueError
   if not isinstance(row[1],str) or row[1] != unicodedata.normalize('NFC',row[1].strip()) or not row[1]: raise ValueError
   if not isinstance(row[2],str) or row[2] != self._name(row[1])[1]: raise ValueError
   if row[4] != 1 or row[5] not in (0,1): raise ValueError
   created_at=self._timestamp(row[6]); updated_at=self._timestamp(row[7])
   if updated_at < created_at: raise ValueError
   return TechnicalPreset(row[0],row[1],self._mapping(json.loads(row[3])),bool(row[5]),created_at,updated_at)
  except (IndexError,json.JSONDecodeError,TypeError,ValueError,TechnicalPresetError) as exc: raise TechnicalPresetError('invalid durable technical preset') from exc
 def list(self):
  try:return tuple(self._record(row) for row in self.repository.list_technical_presets())
  except PersistenceError as exc: raise TechnicalPresetError(f'technical preset list failed: {exc}') from exc
 def read(self,preset_id):
  if not isinstance(preset_id,str) or not preset_id.strip(): raise TechnicalPresetError('preset id must be nonblank')
  try:return self._record(self.repository.get_technical_preset(preset_id))
  except PersistenceError as exc: raise TechnicalPresetError(f'technical preset read failed: {exc}') from exc
 @staticmethod
 def _now(): return datetime.now(timezone.utc).isoformat()
 def _transaction(self, action):
  db=self.repository.db
  try:
   db.execute('BEGIN'); result=action(db); db.execute('COMMIT'); return result
  except Exception as exc:
   if db.in_transaction: db.execute('ROLLBACK')
   if isinstance(exc,TechnicalPresetError): raise
   if isinstance(exc,sqlite3.IntegrityError): raise TechnicalPresetError('technical preset name/default conflict') from exc
   raise TechnicalPresetError(f'technical preset persistence failed: {exc}') from exc
 def create(self,name,mapping,*,is_default=False,preset_id=None):
  display,key=self._name(name); values=self._mapping(mapping)
  if type(is_default) is not bool: raise TechnicalPresetError('is_default must be boolean')
  ident=str(uuid4()) if preset_id is None else str(preset_id)
  if not ident.strip(): raise TechnicalPresetError('preset id must be nonblank')
  now=self._now()
  def action(db):
   if is_default: db.execute('UPDATE technical_presets SET is_default=0,updated_at=? WHERE is_default=1',(now,))
   db.execute('INSERT INTO technical_presets VALUES(?,?,?,?,?,?,?,?)',(ident,display,key,json.dumps(values,sort_keys=True,separators=(',',':'),ensure_ascii=False),1,int(is_default),now,now))
   return self._record(db.execute('SELECT id,name,name_key,mapping,config_version,is_default,created_at,updated_at FROM technical_presets WHERE id=?',(ident,)).fetchone())
  return self._transaction(action)
 def rename(self,preset_id,name):
  display,key=self._name(name); current=self.read(preset_id); now=self._now()
  def action(db):
   if db.execute('UPDATE technical_presets SET name=?,name_key=?,updated_at=? WHERE id=?',(display,key,now,current.id)).rowcount!=1: raise TechnicalPresetError('technical preset not found')
   return self._record(db.execute('SELECT id,name,name_key,mapping,config_version,is_default,created_at,updated_at FROM technical_presets WHERE id=?',(current.id,)).fetchone())
  return self._transaction(action)
 def update(self,preset_id,mapping):
  values=self._mapping(mapping); current=self.read(preset_id); now=self._now()
  def action(db):
   if db.execute('UPDATE technical_presets SET mapping=?,config_version=1,updated_at=? WHERE id=?',(json.dumps(values,sort_keys=True,separators=(',',':'),ensure_ascii=False),now,current.id)).rowcount!=1: raise TechnicalPresetError('technical preset not found')
   return self._record(db.execute('SELECT id,name,name_key,mapping,config_version,is_default,created_at,updated_at FROM technical_presets WHERE id=?',(current.id,)).fetchone())
  return self._transaction(action)
 def delete(self,preset_id):
  current=self.read(preset_id)
  def action(db):
   if db.execute('DELETE FROM technical_presets WHERE id=?',(current.id,)).rowcount!=1: raise TechnicalPresetError('technical preset not found')
  self._transaction(action)
 def set_default(self,preset_id):
  current=self.read(preset_id); now=self._now()
  def action(db):
   db.execute('UPDATE technical_presets SET is_default=0,updated_at=? WHERE is_default=1 AND id<>?',(now,current.id))
   if db.execute('UPDATE technical_presets SET is_default=1,updated_at=? WHERE id=?',(now,current.id)).rowcount!=1: raise TechnicalPresetError('technical preset not found')
   return self._record(db.execute('SELECT id,name,name_key,mapping,config_version,is_default,created_at,updated_at FROM technical_presets WHERE id=?',(current.id,)).fetchone())
  return self._transaction(action)
 def clear_default(self):
  now=self._now(); self._transaction(lambda db: db.execute('UPDATE technical_presets SET is_default=0,updated_at=? WHERE is_default=1',(now,)))
 def apply(self,preset_id,project_id,execution_id):
  preset=self.read(preset_id); drafts=DraftUseCase(self.repository)
  try:
   project,executions=drafts._load(drafts._id(project_id,'project'))
   if project is None: raise DraftError('draft execution selection is missing or ambiguous')
   execution=drafts._require_draft(executions,drafts._id(execution_id,'execution'))
   # Copy only the eight technical scalars; opaque metadata, profile binding,
   # inputs and per-chunk overrides remain owned by this execution.
   execution.defaults={**dict(execution.defaults),**preset.mapping}
   self.repository.save_preparation_sequence(project,execution)
   return drafts._record(execution)
  except (DraftError,PersistenceError) as exc: raise TechnicalPresetError(f'preset application failed: {exc}') from exc
