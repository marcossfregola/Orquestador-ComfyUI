"""Application-layer, ID-stable editing of preparatory chunk sequences."""
from ..domain.core import DomainError, Lifecycle, Chunk
from ..domain.config import merge_chunk_overrides, GenerationConfigError

class EditChunkSequenceUseCase:
    def __init__(self, repository=None, *, repository_factory=None):
        self.repository, self.repository_factory = repository, repository_factory
    def __call__(self, project_id, execution_id, operation, chunk_id=None, **kwargs):
        owned=self.repository_factory() if self.repository_factory else None
        previous,self.repository=self.repository,(owned or self.repository)
        try:
            project,executions=self.repository.load(project_id); matches=[e for e in executions if str(e.id)==str(execution_id)]
            if len(matches)!=1: raise DomainError('execution selection is missing or ambiguous')
            e=matches[0]
            if e.state is not Lifecycle.PENDING or self.repository.load_transitions(e.id) or any(c.state is not Lifecycle.PENDING or c.attempts or getattr(c,'artifacts',None) or getattr(c,'errors',None) for c in e.chunks): raise DomainError('started execution or runtime evidence locks sequence edits')
            before=[(c.id,c.order,dict(c.defaults),c.state,list(c.attempts),c.first_frame) for c in e.chunks]
            if operation=='add': e.add_chunk(Chunk(order=len(e.chunks),defaults=kwargs.get('defaults',{})))
            elif operation=='remove': e.remove_chunk(chunk_id)
            elif operation=='move':
                ids=[str(c.id) for c in e.chunks]; i=ids.index(str(chunk_id)); j=i+int(kwargs.get('delta',0))
                if j<0 or j>=len(ids): raise DomainError('chunk move out of range')
                ids[i],ids[j]=ids[j],ids[i]; e.reorder_chunks(ids)
            elif operation=='duplicate': e.duplicate_chunk(chunk_id)
            elif operation in ('update_prompt','set_override','clear_override'):
                c=next((c for c in e.chunks if str(c.id)==str(chunk_id)),None)
                if c is None: raise DomainError('chunk not found')
                key,value=('prompt',kwargs['prompt']) if operation=='update_prompt' else (kwargs['key'],kwargs.get('value'))
                if operation=='set_override': merge_chunk_overrides({key:value})
                d=dict(c.defaults); d.pop(key,None) if operation=='clear_override' else d.__setitem__(key,value); c.defaults=d
            elif operation=='read_provenance':
                c=next((c for c in e.chunks if str(c.id)==str(chunk_id)),None)
                if c is None: raise DomainError('chunk not found')
                eff=c.effective_parameters(project,e.defaults)
                return {k:{'value':v,'source':'override' if k in c.defaults else ('execution' if k in e.defaults else ('project' if k in project.defaults else 'unset')),'overridden':k in c.defaults} for k,v in eff.items()}
            elif operation=='read_effective':
                c=next((c for c in e.chunks if str(c.id)==str(chunk_id)),None)
                if c is None: raise DomainError('chunk not found')
                return c.effective_parameters(project,e.defaults)
            else: raise DomainError('unsupported sequence operation')
            try: self.repository.save(project,executions)
            except Exception:
                e.chunks[:]=e.chunks[:len(before)]
                for c,s in zip(e.chunks,before): c.id,c.order,d,c.state,c.attempts,c.first_frame=s; c.defaults=d
                raise
            return e
        except GenerationConfigError as exc: raise DomainError(str(exc)) from exc
        finally:
            self.repository=previous
            if owned is not None: owned.close()
