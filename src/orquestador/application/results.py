"""Resolve durable execution outputs into safe, currently usable file paths."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path, PureWindowsPath

from ..domain.core import AssemblyState, Lifecycle, Phase


@dataclass(frozen=True)
class OutputResolution:
    """A result file as authorized by durable evidence and current disk state."""

    status: str
    path: str | None = None
    message: str = ""
    attempt_number: int | None = None

    @property
    def available(self) -> bool:
        return self.status == "available" and self.path is not None


@dataclass(frozen=True)
class ExecutionResults:
    final: OutputResolution
    chunks: tuple[OutputResolution, ...]


class ExecutionResultsResolver:
    """Resolve only recorded outputs under the configured trusted roots.

    A relative chunk output paired with its durable OUTPUT Artifact is the
    project copy created by ``import_project_output``. It is never redirected
    to a same-named ComfyUI file if that project copy is missing. Historical
    absolute output paths are accepted only when they belong to exactly one
    configured root. Final assembly outputs are always project durable and
    must still match their recorded hash and successful assembly provenance.
    """

    def __init__(self, project_root: str | Path, comfyui_output_root: str | Path | None = None):
        self.project_root = Path(project_root).expanduser().resolve()
        self.comfyui_output_root = (
            Path(comfyui_output_root).expanduser().resolve()
            if comfyui_output_root is not None else None
        )

    def resolve(self, execution) -> ExecutionResults:
        chunks = tuple(self._resolve_chunk(execution, chunk) for chunk in execution.chunks)
        return ExecutionResults(self._resolve_final(execution), chunks)

    def _resolve_final(self, execution) -> OutputResolution:
        attempt = execution.latest_assembly_attempt()
        if (execution.state is not Lifecycle.SUCCEEDED or attempt is None
                or attempt.state is not AssemblyState.SUCCEEDED
                or not execution.has_valid_assembly_evidence()):
            return OutputResolution(
                "no_evidence", message="Todavía no hay evidencia durable de un ensamblado final exitoso."
            )
        if not attempt.expected_sha256 or attempt.probe_signature is None:
            return OutputResolution(
                "integrity_error", message="El ensamblado no tiene hash y firma FFprobe durables."
            )
        return self._resolve_file(
            attempt.destination_uri,
            roots=(self.project_root,),
            expected_sha256=attempt.expected_sha256,
            attempt_number=attempt.number,
        )

    def _resolve_chunk(self, execution, chunk) -> OutputResolution:
        successful = [
            attempt for attempt in chunk.attempts
            if attempt.state is Lifecycle.SUCCEEDED
            and attempt.output is not None
            and attempt.evidence is not None
            and isinstance(attempt.output.uri, str)
            and attempt.output.uri.strip()
        ]
        if not successful:
            return OutputResolution("no_evidence", message="No hay un output exitoso registrado.")

        authorized = []
        for attempt in successful:
            artifacts = [
                artifact for artifact in execution.artifacts
                if artifact.project_id == execution.project_id
                and artifact.execution_id == execution.id
                and artifact.chunk_id == chunk.id
                and artifact.attempt_id == attempt.id
                and artifact.phase is Phase.OUTPUT
                and artifact.output == attempt.output
            ]
            if len(artifacts) == 1:
                authorized.append((attempt, artifacts[0]))
        if not authorized:
            return OutputResolution(
                "integrity_error",
                message="El output exitoso no tiene un Artifact de salida inequívoco.",
            )

        assembly = execution.latest_assembly_attempt()
        assembled = (
            assembly is not None
            and assembly.state is AssemblyState.SUCCEEDED
            and execution.has_valid_assembly_evidence()
        )
        source = None
        if assembled:
            source_matches = [
                item for item in assembly.sources
                if item.chunk_id == chunk.id
            ]
            if len(source_matches) == 1:
                source = source_matches[0]
                authorized = [
                    pair for pair in authorized
                    if pair[0].id == source.attempt_id
                    and pair[0].output.uri == source.output_uri
                    and pair[1].id == source.artifact_id
                ]
                if len(authorized) != 1:
                    return OutputResolution(
                        "integrity_error",
                        message="La fuente del chunk no coincide con la evidencia del ensamblado.",
                    )

        if len(authorized) != 1:
            return OutputResolution(
                "ambiguous", message="Hay más de un output exitoso con evidencia durable."
            )

        attempt, _artifact = authorized[0]
        roots = (self.project_root,) if source is not None else (
            self._configured_roots()
            if self._is_absolute_uri(attempt.output.uri)
            else (self.project_root,)
        )
        return self._resolve_file(
            attempt.output.uri,
            roots=roots,
            expected_sha256=source.sha256 if source is not None else None,
            attempt_number=attempt.number,
        )

    def _configured_roots(self) -> tuple[Path, ...]:
        roots = [self.project_root]
        if self.comfyui_output_root is not None:
            roots.append(self.comfyui_output_root)
        # Path equality follows the host's path semantics (case insensitive on
        # Windows) and avoids treating an explicitly identical root as two.
        return tuple(dict.fromkeys(roots))

    @staticmethod
    def _under(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _is_absolute_uri(value: str) -> bool:
        return Path(value).is_absolute() or PureWindowsPath(value).is_absolute()

    @staticmethod
    def _valid_relative_uri(value: str) -> bool:
        if not value or "\\" in value or ":" in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            return False
        parts = value.split("/")
        return all(part not in {"", ".", ".."} for part in parts)

    def _resolve_candidates(self, uri: str, roots: tuple[Path, ...]):
        """Return (candidate, error) without searching names or traversing roots."""
        if not isinstance(uri, str) or not uri.strip():
            return None, OutputResolution("invalid", message="La ruta durable está vacía.")
        value = uri.strip()
        if "\x00" in value:
            return None, OutputResolution("invalid", message="La ruta durable contiene caracteres inválidos.")

        if self._is_absolute_uri(value):
            try:
                candidate = Path(value).expanduser().resolve(strict=False)
            except (OSError, RuntimeError, ValueError):
                return None, OutputResolution("invalid", message="La ruta durable no se puede resolver.")
            canonical_roots = [root.resolve(strict=False) for root in roots]
            matching_roots = [root for root in canonical_roots if self._under(candidate, root)]
            if not matching_roots:
                return None, OutputResolution("invalid", message="La ruta durable sale de las raíces configuradas.")
            if len(matching_roots) > 1:
                return None, OutputResolution("ambiguous", message="La ruta absoluta pertenece a más de una raíz configurada.")
            return candidate, None

        if not self._valid_relative_uri(value):
            return None, OutputResolution("invalid", message="La ruta durable no es relativa y contenida.")

        existing: dict[Path, Path] = {}
        escaped = False
        for configured_root in roots:
            try:
                root = configured_root.resolve(strict=True)
                if not root.is_dir():
                    continue
                candidate = (root / Path(*value.split("/"))).resolve(strict=False)
            except (OSError, RuntimeError, ValueError):
                continue
            if not self._under(candidate, root):
                escaped = True
                continue
            try:
                if candidate.exists():
                    existing.setdefault(candidate, candidate)
            except OSError:
                return None, OutputResolution("invalid", message="No se puede inspeccionar el archivo registrado.")

        if len(existing) > 1:
            return None, OutputResolution(
                "ambiguous", message="La ruta existe bajo más de una raíz configurada."
            )
        if existing:
            return next(iter(existing.values())), None
        if escaped:
            return None, OutputResolution("invalid", message="La ruta durable escapa de una raíz configurada.")
        return None, OutputResolution("missing", message="El archivo registrado no existe.")

    def _resolve_file(
        self,
        uri: str,
        *,
        roots: tuple[Path, ...],
        expected_sha256: str | None = None,
        attempt_number: int | None = None,
    ) -> OutputResolution:
        path, error = self._resolve_candidates(uri, roots)
        if error is not None:
            return OutputResolution(error.status, message=error.message, attempt_number=attempt_number)
        try:
            if not path.is_file():
                return OutputResolution("invalid", message="El output registrado no es un archivo regular.", attempt_number=attempt_number)
            if path.suffix.casefold() != ".mp4":
                return OutputResolution("invalid", message="El output registrado no tiene extensión MP4.", attempt_number=attempt_number)
            if path.stat().st_size <= 0:
                return OutputResolution("empty", message="El archivo registrado está vacío.", attempt_number=attempt_number)
            if not self._has_mp4_header(path):
                return OutputResolution("invalid", message="El archivo no tiene una cabecera MP4 básica válida.", attempt_number=attempt_number)
            if expected_sha256 is not None and self._sha256(path) != expected_sha256.lower():
                return OutputResolution("integrity_error", message="El contenido ya no coincide con el hash durable.", attempt_number=attempt_number)
        except (OSError, RuntimeError, ValueError):
            return OutputResolution("invalid", message="No se pudo leer el archivo registrado.", attempt_number=attempt_number)
        return OutputResolution("available", str(path), attempt_number=attempt_number)

    @staticmethod
    def _has_mp4_header(path: Path) -> bool:
        with path.open("rb") as stream:
            header = stream.read(24)
        if len(header) < 16 or header[4:8] != b"ftyp":
            return False
        box_size = int.from_bytes(header[:4], "big")
        if box_size == 1:
            if len(header) < 24:
                return False
            extended_size = int.from_bytes(header[8:16], "big")
            return 24 <= extended_size <= path.stat().st_size
        return box_size >= 16 and box_size <= path.stat().st_size

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()


__all__ = ["ExecutionResults", "ExecutionResultsResolver", "OutputResolution"]
