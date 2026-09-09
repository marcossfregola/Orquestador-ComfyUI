"""Application boundary for assembling completed chunk artifacts."""
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from ..adapters.assembly import AssemblyError

@dataclass(frozen=True)
class AssemblyResult:
    success: bool
    output: Path|None = None
    reason: str = ''

class AssemblySourceRoot(str, Enum):
    PROJECT_DURABLE = 'project_durable'
    COMFY_OUTPUT = 'comfy_output'

@dataclass(frozen=True)
class AssemblySource:
    path: str|Path
    root_kind: AssemblySourceRoot

class AssembleExecutionUseCase:
    def __init__(self, assembler, trusted_root, source_roots=None):
        self.assembler = assembler
        roots = [trusted_root] if source_roots is None else list(source_roots)
        if trusted_root not in roots:
            roots.insert(0, trusted_root)
        self.source_roots = tuple(dict.fromkeys(Path(root).resolve() for root in roots))

    @staticmethod
    def _under(path, root):
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _resolve_source(self, value):
        kind = None
        if isinstance(value, AssemblySource):
            kind, value = value.root_kind, value.path
            try: kind = AssemblySourceRoot(kind)
            except (TypeError, ValueError): raise AssemblyError('invalid source root kind')
        raw = Path(value)
        roots = self.source_roots
        if kind is not None:
            if kind is AssemblySourceRoot.PROJECT_DURABLE: roots = (self.source_roots[0],)
            elif len(self.source_roots) < 2: raise AssemblyError('comfy output root unavailable')
            else: roots = (self.source_roots[1],)
        if raw.is_absolute():
            candidate = raw.resolve()
            if not any(self._under(candidate, root) for root in roots):
                raise AssemblyError('source outside trusted roots')
            candidates = [candidate]
        else:
            candidates = [(root / raw).resolve() for root in roots
                          if self._under((root / raw).resolve(), root)]
            candidates = [p for p in candidates if p.is_file() and p.stat().st_size > 0]
            if len(candidates) != 1:
                raise AssemblyError('source is missing, empty, or ambiguous under trusted roots')
        candidate = candidates[0]
        if not candidate.is_file() or candidate.stat().st_size == 0:
            raise AssemblyError('source is missing or empty')
        return candidate

    def execute(self, chunk_outputs, destination, *, reencode=False):
        try:
            dst = Path(destination).expanduser().resolve()
            paths = [self._resolve_source(value) for value in chunk_outputs]
            if dst.suffix.lower() != '.mp4':
                raise AssemblyError('destination must have .mp4 suffix')
            if dst.exists():
                raise AssemblyError('destination already exists')
            result=self.assembler.assemble(paths,dst,reencode=reencode)
            return AssemblyResult(True,result)
        except Exception as exc: return AssemblyResult(False,reason=str(exc))
