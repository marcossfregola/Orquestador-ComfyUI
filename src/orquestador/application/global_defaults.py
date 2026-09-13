"""F13.3 application boundary for durable global technical defaults."""
from __future__ import annotations

from ..domain.config import GlobalDefaults, GenerationConfigError
from ..persistence.sqlite import PersistenceError


class GlobalDefaultsError(ValueError):
    pass


class GlobalDefaultsUseCase:
    def __init__(self, repository):
        self.repository = repository

    def read(self) -> GlobalDefaults:
        try:
            return self.repository.load_global_defaults()
        except PersistenceError as exc:
            raise GlobalDefaultsError(f"global defaults read failed: {exc}") from exc

    def update(self, mapping) -> GlobalDefaults:
        try:
            defaults = GlobalDefaults.from_mapping(mapping)
            return self.repository.save_global_defaults(defaults)
        except (GenerationConfigError, PersistenceError) as exc:
            raise GlobalDefaultsError(f"global defaults update failed: {exc}") from exc
