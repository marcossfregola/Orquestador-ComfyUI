"""Application boundary for assembling completed chunk artifacts."""
import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from ..adapters.assembly import AssemblyError
from ..domain.core import (AssemblyAttempt, AssemblySourceEvidence, AssemblyState,
                           ExecutionId, Lifecycle, Phase)
from .final_output import (
    FINAL_OUTPUT_FOLDER_KEY,
    FINAL_OUTPUT_FILENAME_KEY,
    FinalOutputConfigError,
    final_output_snapshot,
    final_output_target,
    requested_final_output_name,
)

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


@dataclass(frozen=True)
class FinalizationResult:
    success: bool
    execution_id: str
    state: str
    output: Path|None = None
    reason: str = ''


class FinalizeExecutionUseCase:
    """Durably finalize a chunk-complete execution through the shared video adapter."""
    def __init__(self, repository, assembler, trusted_root=None, publication_root=None):
        self.repository=repository
        self.assembler=assembler
        self.publication_root=publication_root
        configured=trusted_root if trusted_root is not None else getattr(repository,'root',None)
        if configured is None: raise ValueError('trusted project output root is required')
        self.root=Path(configured).resolve()
        if Path(getattr(repository,'root',self.root)).resolve()!=self.root:
            raise ValueError('assembly root must match the durable project root')

    @staticmethod
    def _under(path,root):
        try:path.relative_to(root); return True
        except ValueError:return False

    def _resolve(self,uri,*,must_exist=False):
        if not isinstance(uri,str) or not uri.strip(): raise AssemblyError('durable assembly path is empty')
        raw=Path(uri)
        if raw.is_absolute() or raw.drive or '\\' in uri or any(part in {'','..'} for part in uri.split('/')):
            raise AssemblyError('durable assembly path is not a contained project-relative path')
        path=(self.root/raw).resolve()
        if not self._under(path,self.root): raise AssemblyError('durable assembly path escapes project root')
        if must_exist and (not path.is_file() or path.stat().st_size==0): raise AssemblyError('durable assembly file is missing or empty')
        return path

    def _publication_root_value(self):
        value = self.publication_root() if callable(self.publication_root) else self.publication_root
        return self.root if value is None else value

    def _configured_publication_target(self, execution):
        defaults=dict(execution.defaults)
        if FINAL_OUTPUT_FOLDER_KEY not in defaults or FINAL_OUTPUT_FILENAME_KEY not in defaults:
            return None
        return final_output_target(
            defaults,
            project_name="video-final",
            project_root=self.root,
        )

    def _ensure_publication_snapshot(self, project, execution):
        defaults=dict(execution.defaults)
        if FINAL_OUTPUT_FOLDER_KEY in defaults and FINAL_OUTPUT_FILENAME_KEY in defaults:
            try:
                return final_output_target(
                    defaults,
                    project_name=project.name,
                    project_root=self.root,
                )
            except FinalOutputConfigError as exc:
                raise AssemblyError(str(exc)) from exc
        try:
            snapshot=final_output_snapshot(
                project.name,
                requested_final_output_name(defaults),
                defaults.get(FINAL_OUTPUT_FOLDER_KEY, self._publication_root_value()),
                project_root=self.root,
            )
        except FinalOutputConfigError as exc:
            raise AssemblyError(str(exc)) from exc
        merged={**defaults,**snapshot}
        execution.defaults=merged
        self.repository.save(project,[execution])
        return final_output_target(
            execution.defaults,
            project_name=project.name,
            project_root=self.root,
        )

    def _publication_matches(self, execution, expected_sha256):
        target=self._configured_publication_target(execution)
        if target is None or not target.is_file():
            return False
        digest,_=self.assembler.inspect(target)
        return digest==expected_sha256

    @staticmethod
    def _sha256(path):
        digest=hashlib.sha256()
        with Path(path).open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):
                digest.update(block)
        return digest.hexdigest()

    def _source_manifest(self,execution):
        if len(execution.chunks)<2 or any(chunk.state.value!='succeeded' for chunk in execution.chunks):
            raise AssemblyError('every execution chunk must be successful before final assembly')
        try:
            transitions=tuple(self.repository.load_transitions(execution.id))
        except Exception as exc:
            raise AssemblyError(f'durable chunk transitions are unavailable: {exc}') from exc
        entries=[]; paths=[]
        for order,chunk in enumerate(execution.chunks):
            if chunk.order!=order or str(chunk.execution_id)!=str(execution.id): raise AssemblyError('chunk order or ownership is inconsistent')
            attempts=[attempt for attempt in chunk.attempts if attempt.state.value=='succeeded' and attempt.output is not None and attempt.evidence is not None]
            if len(attempts)!=1: raise AssemblyError(f'chunk {order} has missing or ambiguous successful attempt')
            attempt=attempts[0]
            artifacts=[artifact for artifact in execution.artifacts
                       if artifact.execution_id==execution.id and artifact.chunk_id==chunk.id
                       and artifact.attempt_id==attempt.id and artifact.phase is Phase.OUTPUT]
            if len(artifacts)!=1 or artifacts[0].output!=attempt.output:
                raise AssemblyError(f'chunk {order} has missing or ambiguous durable output artifact')
            if order<len(execution.chunks)-1:
                links=[transition for transition in transitions
                       if transition.source_chunk_id==chunk.id
                       and transition.source_attempt_id==attempt.id]
                if len(links)!=1:
                    raise AssemblyError(f'chunk {order} has missing or ambiguous durable continuity transition')
                transition=links[0]
                if (transition.project_id!=execution.project_id or transition.execution_id!=execution.id
                        or transition.target_chunk_id!=execution.chunks[order+1].id
                        or transition.source_output!=attempt.output
                        or isinstance(transition.frame_count,bool) or not isinstance(transition.frame_count,int)
                        or transition.frame_count<=0
                        or isinstance(transition.source_frame_index,bool)
                        or not isinstance(transition.source_frame_index,int)
                        or transition.source_frame_index!=transition.frame_count-1):
                    raise AssemblyError(f'chunk {order} has contradictory durable continuity evidence')
            path=self._resolve(attempt.output.uri,must_exist=True)
            entries.append(AssemblySourceEvidence(order,chunk.id,attempt.id,artifacts[0].id,attempt.output.uri,self._sha256(path)))
            paths.append(path)
        return tuple(entries),tuple(paths)

    def _load_exact(self,project_id,execution_id):
        project,executions=self.repository.load(project_id)
        matches=[execution for execution in executions if str(execution.id)==str(execution_id)]
        if len(matches)!=1: raise AssemblyError('execution selection is missing or ambiguous')
        return project,matches[0]

    def _destination_uri(self,execution):
        return f'assembled-{execution.id}.mp4'

    @staticmethod
    def _staging_uri(execution,number):
        return f'.orquestador-assembly/{execution.id}/attempt-{number}.mp4'

    def can_retry(self,execution):
        latest=execution.latest_assembly_attempt()
        if (latest is None or latest.state is not AssemblyState.FAILED
                or execution.state is not Lifecycle.RUNNING
                or len(latest.sources)!=len(execution.chunks)
                or not execution.chunks or any(chunk.state is not Lifecycle.SUCCEEDED for chunk in execution.chunks)):
            return False
        try:
            sources,_=self._source_manifest(execution)
            if sources!=latest.sources: return False
            destination=self._resolve(latest.destination_uri)
            self._resolve(latest.staging_uri)
            if not destination.exists():
                return True
            if latest.expected_sha256 is None or latest.probe_signature is None:
                return False
            digest,signature=self.assembler.inspect(destination)
            if digest!=latest.expected_sha256 or tuple(signature)!=latest.probe_signature:
                return False
            target=self._configured_publication_target(execution)
            if target is not None and target.exists():
                published_hash,_=self.assembler.inspect(target)
                if published_hash!=latest.expected_sha256:
                    return False
            return True
        except (OSError,ValueError,AssemblyError):
            return False

    def is_durably_complete(self,execution):
        latest=execution.latest_assembly_attempt()
        if (execution.state is not Lifecycle.SUCCEEDED or latest is None
                or latest.state is not AssemblyState.SUCCEEDED
                or not execution.has_valid_assembly_evidence()): return False
        try:
            sources,_=self._source_manifest(execution)
            if sources!=latest.sources: return False
            destination=self._resolve(latest.destination_uri,must_exist=True)
            digest,signature=self.assembler.inspect(destination)
            if digest!=latest.expected_sha256 or tuple(signature)!=latest.probe_signature:
                return False
            # Legacy completed executions predate external publication metadata
            # and retain their existing completion contract.
            target=self._configured_publication_target(execution)
            if target is None:
                return True
            published_hash,published_signature=self.assembler.inspect(target)
            return (published_hash==latest.expected_sha256
                    and tuple(published_signature)==latest.probe_signature)
        except Exception:
            return False

    def execute(self,project_id,execution_id,*,queue_item_id=None,retry=False):
        try:
            project,execution=self._load_exact(project_id,execution_id)
            if execution.state is not Lifecycle.RUNNING:
                raise AssemblyError('only a running execution can be finalized')
            if not execution.chunks or any(chunk.state is not Lifecycle.SUCCEEDED for chunk in execution.chunks):
                raise AssemblyError('all chunks must be successful before finalization')
            if queue_item_id is not None:
                validator=getattr(self.repository,'validate_active_queue_claim',None)
                if not callable(validator): raise AssemblyError('active queue claim validation is unavailable')
                validator(queue_item_id,execution.id)
            elif self.repository.has_live_queue_item(execution.id):
                raise AssemblyError('a live queue item owns this execution')
            publication_target=self._ensure_publication_snapshot(project,execution)
            destination_uri=self._destination_uri(execution)
            destination=self._resolve(destination_uri)
            latest=execution.latest_assembly_attempt()
            try:
                sources,source_paths=self._source_manifest(execution)
            except Exception as exc:
                if latest is None:
                    attempt=AssemblyAttempt(execution.id,1,AssemblyState.FAILED,destination_uri,
                        self._staging_uri(execution,1),(),error=str(exc).strip() or 'chunk source validation failed')
                    execution.assembly_attempts.append(attempt)
                    self.repository.save(project,[execution])
                    return FinalizationResult(False,str(execution.id),AssemblyState.FAILED.value,reason=attempt.error)
                raise
            if latest is None:
                latest=AssemblyAttempt(execution.id,1,AssemblyState.PENDING,destination_uri,
                    self._staging_uri(execution,1),sources)
                execution.assembly_attempts.append(latest)
                self.repository.save(project,[execution])
            else:
                if latest.destination_uri!=destination_uri or latest.sources!=sources:
                    if latest.state in {AssemblyState.PENDING,AssemblyState.ASSEMBLING}:
                        return self._fail(project,execution,latest,'durable finalization provenance no longer matches completed chunks')
                    raise AssemblyError('durable finalization provenance no longer matches completed chunks')
                if latest.state is AssemblyState.SUCCEEDED:
                    if not self.is_durably_complete(execution): raise AssemblyError('recorded final MP4 failed provenance/hash/FFprobe/publication validation; destination will not be overwritten')
                    return FinalizationResult(True,str(execution.id),AssemblyState.SUCCEEDED.value,publication_target)
                if latest.state is AssemblyState.FAILED:
                    if not retry: return FinalizationResult(False,str(execution.id),AssemblyState.FAILED.value,reason=latest.error or 'assembly failed; explicit assembly retry is required')
                    if not self.can_retry(execution): raise AssemblyError('assembly retry is not safe for the current durable evidence')
                    previous=latest
                    reuse_internal=destination.exists()
                    number=latest.number+1
                    latest=AssemblyAttempt(execution.id,number,AssemblyState.PENDING,destination_uri,
                        self._staging_uri(execution,number),sources)
                    execution.assembly_attempts.append(latest)
                    self.repository.save(project,[execution])
                    if reuse_internal:
                        latest.transition(AssemblyState.ASSEMBLING)
                        latest.record_staged_output(previous.expected_sha256,previous.probe_signature)
                        self.repository.save(project,[execution])
                        return self._adopt_published(project,execution,latest,destination)
            latest=execution.latest_assembly_attempt()
            if latest.state is AssemblyState.SUCCEEDED:
                return FinalizationResult(True,str(execution.id),AssemblyState.SUCCEEDED.value,publication_target)
            if latest.state is AssemblyState.FAILED:
                return FinalizationResult(False,str(execution.id),AssemblyState.FAILED.value,reason=latest.error or 'assembly failed')
            staging=self._resolve(latest.staging_uri)
            if latest.state is AssemblyState.PENDING:
                if destination.exists(): return self._fail(project,execution,latest,'final MP4 destination already exists without matching durable assembly evidence')
                if staging.exists(): return self._fail(project,execution,latest,'staging MP4 already exists without matching durable output evidence')
                latest.transition(AssemblyState.ASSEMBLING)
                self.repository.save(project,[execution])
            if destination.exists():
                return self._adopt_published(project,execution,latest,destination)
            if latest.expected_sha256 is not None:
                if not staging.is_file(): return self._fail(project,execution,latest,'validated staged MP4 is missing after restart')
                try:
                    staged_hash,staged_probe=self.assembler.inspect(staging)
                    if staged_hash!=latest.expected_sha256 or tuple(staged_probe)!=latest.probe_signature:
                        return self._fail(project,execution,latest,'staged MP4 no longer matches durable assembly evidence')
                except Exception as exc:return self._fail(project,execution,latest,f'staged MP4 validation failed: {exc}')
            else:
                if staging.exists(): return self._fail(project,execution,latest,'interrupted staging file has no durable hash/probe identity; assembly retry is required')
                try:
                    staged=self.assembler.stage(source_paths,staging)
                    latest.record_staged_output(staged.sha256,staged.probe_signature)
                    self.repository.save(project,[execution])
                except Exception as exc:
                    return self._fail(project,execution,latest,str(exc))
            try:
                self.assembler.publish(staging,destination,expected_sha256=latest.expected_sha256)
            except Exception as exc:
                if destination.exists(): return self._adopt_published(project,execution,latest,destination)
                return self._fail(project,execution,latest,str(exc))
            return self._adopt_published(project,execution,latest,destination)
        except Exception as exc:
            return FinalizationResult(False,str(execution_id),AssemblyState.FAILED.value,reason=str(exc))

    def retry(self,project_id,execution_id,*,queue_item_id=None):
        return self.execute(project_id,execution_id,queue_item_id=queue_item_id,retry=True)

    def _adopt_published(self,project,execution,attempt,destination):
        if attempt.expected_sha256 is None or attempt.probe_signature is None:
            return self._fail(project,execution,attempt,'final destination exists without durable output hash/probe provenance; overwrite is prohibited')
        try:
            digest,signature=self.assembler.inspect(destination)
            if digest!=attempt.expected_sha256 or tuple(signature)!=attempt.probe_signature:
                return self._fail(project,execution,attempt,'published MP4 failed hash/FFprobe provenance validation; overwrite is prohibited')
            current_sources,_=self._source_manifest(execution)
            if current_sources!=attempt.sources:
                return self._fail(project,execution,attempt,'published MP4 source provenance changed during recovery')
            target=self._configured_publication_target(execution)
            if target is None:
                raise AssemblyError('final video publication target is missing')
            publisher=getattr(self.assembler,'publish_external',None)
            if not callable(publisher):
                raise AssemblyError('final video publication adapter is unavailable')
            published=publisher(destination,target,expected_sha256=attempt.expected_sha256)
            published_hash,published_signature=self.assembler.inspect(published)
            if (published_hash!=attempt.expected_sha256
                    or tuple(published_signature)!=attempt.probe_signature):
                raise AssemblyError('published final video failed integrity validation')
            attempt.transition(AssemblyState.SUCCEEDED)
            execution.transition(Lifecycle.SUCCEEDED)
            self.repository.save(project,[execution])
            return FinalizationResult(True,str(execution.id),AssemblyState.SUCCEEDED.value,Path(published))
        except Exception as exc:
            return self._fail(project,execution,attempt,f'published MP4 validation/finalization failed: {exc}')

    def _fail(self,project,execution,attempt,reason):
        detail=str(reason).strip() or 'assembly failed'
        try:
            if attempt.state is AssemblyState.PENDING:
                attempt.transition(AssemblyState.ASSEMBLING)
                self.repository.save(project,[execution])
            if attempt.state is AssemblyState.ASSEMBLING:
                attempt.transition(AssemblyState.FAILED,error=detail)
                self.repository.save(project,[execution])
        except Exception as exc:
            detail=f'{detail}; failure evidence could not be persisted: {exc}'
        return FinalizationResult(False,str(execution.id),AssemblyState.FAILED.value,reason=detail)
