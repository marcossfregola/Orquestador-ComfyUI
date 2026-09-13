"""F13.5 durable, installation-wide prompt/chunk templates."""
from __future__ import annotations

import json
import sqlite3
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from ..domain.config import GenerationConfigError, validate_prompt
from ..domain.core import Chunk
from ..persistence.sqlite import PersistenceError
from .drafts import DraftError, DraftUseCase


class ChunkTemplateError(ValueError):
    """A template operation could not safely change durable draft data."""


@dataclass(frozen=True)
class ChunkTemplate:
    id: str
    name: str
    prompts: tuple[str, ...]
    created_at: datetime
    updated_at: datetime


class ChunkTemplatesUseCase:
    """CRUD and by-value application of reusable prompt sequences."""

    TEMPLATE_VERSION = 1

    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _id(value, label="template"):
        if not isinstance(value, str) or not value.strip():
            raise ChunkTemplateError(f"{label} id must be nonblank")
        return value.strip()

    @staticmethod
    def _name(value):
        if not isinstance(value, str):
            raise ChunkTemplateError("template name must be text")
        display = unicodedata.normalize("NFC", value.strip())
        if not display:
            raise ChunkTemplateError("template name must be nonblank")
        return display, display.casefold()

    @staticmethod
    def _prompts(value):
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            raise ChunkTemplateError("template prompts must be a sequence")
        try:
            prompts = tuple(validate_prompt(prompt) for prompt in value)
        except GenerationConfigError as exc:
            raise ChunkTemplateError(f"template prompt is invalid: {exc}") from exc
        if len(prompts) < 2:
            raise ChunkTemplateError("template requires at least two prompts")
        return prompts

    @staticmethod
    def _timestamp(value):
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
                raise ValueError
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError) as exc:
            raise ChunkTemplateError("invalid chunk template timestamp") from exc

    def _record(self, row):
        try:
            if (
                not isinstance(row[0], str)
                or not row[0]
                or row[0] != row[0].strip()
            ):
                raise ValueError
            if (
                not isinstance(row[1], str)
                or not row[1]
                or row[1] != unicodedata.normalize("NFC", row[1].strip())
            ):
                raise ValueError
            if not isinstance(row[2], str) or row[2] != self._name(row[1])[1]:
                raise ValueError
            if type(row[4]) is not int or row[4] != self.TEMPLATE_VERSION:
                raise ValueError
            if not isinstance(row[3], str):
                raise ValueError
            created_at = self._timestamp(row[5])
            updated_at = self._timestamp(row[6])
            if updated_at < created_at:
                raise ValueError
            return ChunkTemplate(
                row[0], row[1], self._prompts(json.loads(row[3])), created_at, updated_at
            )
        except (
            IndexError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
            ChunkTemplateError,
        ) as exc:
            raise ChunkTemplateError("invalid durable chunk template") from exc

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _serialized_prompts(prompts):
        return json.dumps(list(prompts), ensure_ascii=False, separators=(",", ":"))

    def _transaction(self, action):
        db = self.repository.db
        try:
            db.execute("BEGIN")
            result = action(db)
            db.execute("COMMIT")
            return result
        except Exception as exc:
            if db.in_transaction:
                db.execute("ROLLBACK")
            if isinstance(exc, ChunkTemplateError):
                raise
            if isinstance(exc, sqlite3.IntegrityError):
                raise ChunkTemplateError("chunk template name conflict") from exc
            raise ChunkTemplateError(f"chunk template persistence failed: {exc}") from exc

    def list(self):
        try:
            return tuple(self._record(row) for row in self.repository.list_chunk_templates())
        except PersistenceError as exc:
            raise ChunkTemplateError(f"chunk template list failed: {exc}") from exc

    def read(self, template_id):
        ident = self._id(template_id)
        try:
            return self._record(self.repository.get_chunk_template(ident))
        except PersistenceError as exc:
            raise ChunkTemplateError(f"chunk template read failed: {exc}") from exc

    def create(self, name, prompts, *, template_id=None):
        display, key = self._name(name)
        values = self._prompts(prompts)
        ident = str(uuid4()) if template_id is None else self._id(template_id)
        now = self._now()

        def action(db):
            db.execute(
                "INSERT INTO chunk_templates VALUES(?,?,?,?,?,?,?)",
                (
                    ident,
                    display,
                    key,
                    self._serialized_prompts(values),
                    self.TEMPLATE_VERSION,
                    now,
                    now,
                ),
            )
            return self._record(
                db.execute(
                    "SELECT id,name,name_key,prompts,template_version,created_at,updated_at "
                    "FROM chunk_templates WHERE id=?",
                    (ident,),
                ).fetchone()
            )

        return self._transaction(action)

    def rename(self, template_id, name):
        current = self.read(template_id)
        display, key = self._name(name)
        now = self._now()

        def action(db):
            if db.execute(
                "UPDATE chunk_templates SET name=?,name_key=?,updated_at=? WHERE id=?",
                (display, key, now, current.id),
            ).rowcount != 1:
                raise ChunkTemplateError("chunk template not found")
            return self._record(
                db.execute(
                    "SELECT id,name,name_key,prompts,template_version,created_at,updated_at "
                    "FROM chunk_templates WHERE id=?",
                    (current.id,),
                ).fetchone()
            )

        return self._transaction(action)

    def update(self, template_id, prompts):
        current = self.read(template_id)
        values = self._prompts(prompts)
        now = self._now()

        def action(db):
            if db.execute(
                "UPDATE chunk_templates SET prompts=?,template_version=1,updated_at=? WHERE id=?",
                (self._serialized_prompts(values), now, current.id),
            ).rowcount != 1:
                raise ChunkTemplateError("chunk template not found")
            return self._record(
                db.execute(
                    "SELECT id,name,name_key,prompts,template_version,created_at,updated_at "
                    "FROM chunk_templates WHERE id=?",
                    (current.id,),
                ).fetchone()
            )

        return self._transaction(action)

    def duplicate(self, template_id, name, *, new_template_id=None):
        source = self.read(template_id)
        return self.create(name, source.prompts, template_id=new_template_id)

    def delete(self, template_id):
        current = self.read(template_id)

        def action(db):
            if db.execute("DELETE FROM chunk_templates WHERE id=?", (current.id,)).rowcount != 1:
                raise ChunkTemplateError("chunk template not found")

        self._transaction(action)

    @staticmethod
    def _apply_prompts(execution, prompts):
        """Replace only the prompt plan, retaining extant chunk overrides by order."""
        prior = list(execution.chunks)
        replacement = []
        for order, prompt in enumerate(prompts):
            if order < len(prior):
                chunk = prior[order]
                chunk.order = order
                chunk.defaults = {**dict(chunk.defaults), "prompt": prompt}
            else:
                chunk = Chunk(order=order, execution_id=execution.id, defaults={"prompt": prompt})
            replacement.append(chunk)
        execution.defaults = {
            **dict(execution.defaults),
            "chunk_count": len(prompts),
            "prompts": list(prompts),
        }
        execution.chunks = replacement

    @staticmethod
    def _restore(execution, defaults, chunks):
        execution.defaults = defaults
        for chunk, order, values in chunks:
            chunk.order = order
            chunk.defaults = values
        execution.chunks = [chunk for chunk, _, _ in chunks]

    def apply(self, template_id, project_id, execution_id):
        template = self.read(template_id)
        drafts = DraftUseCase(self.repository)
        original_defaults = None
        original_chunks = None
        try:
            project, executions = drafts._load(drafts._id(project_id, "project"))
            if project is None:
                raise DraftError("draft execution selection is missing or ambiguous")
            execution = drafts._require_draft(executions, drafts._id(execution_id, "execution"))
            original_defaults = dict(execution.defaults)
            original_chunks = [
                (chunk, chunk.order, dict(chunk.defaults)) for chunk in execution.chunks
            ]
            self._apply_prompts(execution, template.prompts)
            result = drafts._record(execution)
            self.repository.save_preparation_sequence(project, execution)
            return result
        except (DraftError, PersistenceError, sqlite3.Error, TypeError, ValueError, AttributeError) as exc:
            if original_defaults is not None and original_chunks is not None:
                self._restore(execution, original_defaults, original_chunks)
            raise ChunkTemplateError(f"template application failed: {exc}") from exc
