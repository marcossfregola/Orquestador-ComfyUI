import tempfile
import unittest
from pathlib import Path

from orquestador.domain import (Artifact, BackendJobRef, Chunk, Evidence,
    Execution, Lifecycle, OutputRef, Phase, Project, TransitionFrame)
from orquestador.domain.core import DomainError
from orquestador.application.chain_execution import ChainExecutionUseCase, ChainOutcome
from orquestador.application.chunk_execution import ChunkExecutionResult
from orquestador.persistence.sqlite import SQLiteProjectRepository, PersistenceDataError
from orquestador.application.recover_execution import ResumeExecutionUseCase, RecoveryOutcome
from orquestador.application.bridge import SubmitAttemptUseCase
from orquestador.application.chunk_execution import ChunkExecutionCoordinator
from orquestador.adapters.http import HistoryResult, HistoryState
from orquestador.adapters.outputs import OutputCorrelationResult, OutputCorrelationStatus, OutputDescriptor
from orquestador.adapters.physical_outputs import PhysicalOutputEvidence, PhysicalOutputStatus


class _Runner:
    def __init__(self, repo, fail_at=None):
        self.repo, self.fail_at, self.calls, self.prompts = repo, fail_at, [], []

    def execute(self, project, execution, chunk_id, prompt):
        self.calls.append(str(chunk_id)); self.prompts.append(dict(prompt))
        chunk = next(c for c in execution.chunks if c.id == chunk_id)
        attempt = chunk.new_attempt(); attempt.assign_external_job_ref(BackendJobRef(f"job-{chunk.order}-{len(self.calls)}"))
        attempt.transition(Lifecycle.RUNNING)
        if self.fail_at == chunk.order:
            attempt.transition(Lifecycle.FAILED, error=__import__('orquestador.domain', fromlist=['ErrorRecord']).ErrorRecord('failed','simulated'))
            chunk.transition(Lifecycle.RUNNING); chunk.transition(Lifecycle.FAILED)
            self.repo.save(project, [execution]); return ChunkExecutionResult(False, 'failed', str(attempt.id))
        out = OutputRef(f"media/chunk-{chunk.order}.mp4")
        attempt.transition(Lifecycle.SUCCEEDED, output=out, evidence=Evidence('valid'))
        chunk.transition(Lifecycle.RUNNING)
        chunk.transition(Lifecycle.SUCCEEDED)
        artifact = Artifact(project.id, execution.id, chunk.id, attempt.id, Phase.OUTPUT, out)
        transition = TransitionFrame(project.id, execution.id, chunk.id, attempt.id, out, 4, 5)
        return ChunkExecutionResult(True, 'completed', str(attempt.id), artifact, transition)


class F7ChainExecutionTests(unittest.TestCase):
    def make(self, n=2):
        root = Path(tempfile.mkdtemp()); (root/'media').mkdir()
        for i in range(n): (root/f'media/chunk-{i}.mp4').write_bytes(b'x')
        repo = SQLiteProjectRepository(root, 'f7.sqlite3'); p = Project(); e = Execution(p.id)
        for i in range(n): e.add_chunk(Chunk(order=i))
        repo.save(p, [e]); return root, repo, p, e

    def run_chain(self, n=2, runner=None, repo=None, p=None, e=None):
        if repo is None: root, repo, p, e = self.make(n)
        runner = runner or _Runner(repo)
        out = ChainExecutionUseCase(repo, runner).run(p, e, lambda i, c: {'seed': i}, transition_materializer=lambda t: t.source_output.uri)
        return out, runner, repo, p, e

    def test_clean_two_chunk_chain_exactly_one_ordered_link(self):
        out, r, repo, p, e = self.run_chain(2)
        self.assertEqual(out.outcome, ChainOutcome.COMPLETE); links = repo.load_transitions(e.id)
        self.assertEqual(len(links), 1); self.assertEqual((links[0].source_chunk_id, links[0].target_chunk_id), (e.chunks[0].id, e.chunks[1].id)); repo.close()

    def test_clean_three_chunk_chain_n_minus_one_ordered_links(self):
        out, r, repo, p, e = self.run_chain(3); self.assertEqual(out.outcome, ChainOutcome.COMPLETE)
        links = repo.load_transitions(e.id); self.assertEqual(len(links), 2); self.assertEqual([x.target_chunk_id for x in links], [e.chunks[1].id, e.chunks[2].id]); repo.close()

    def test_next_first_frame_is_exact_durable_transition_output(self):
        out, r, repo, p, e = self.run_chain(2); link = repo.load_transitions(e.id)[0]
        self.assertEqual(r.prompts[1]['first_frame'], link.source_output.uri)
        repo.close(); repo = SQLiteProjectRepository(Path(repo.root), 'f7.sqlite3'); _, es = repo.load(p.id)
        self.assertEqual(es[0].chunks[1].first_frame.source_output, link.source_output); repo.close()

    def test_close_reopen_after_chunk_one_resumes_without_resubmit(self):
        root, repo, p, e = self.make(2); r = _Runner(repo); e.transition(Lifecycle.RUNNING); repo.save(p,[e]);
        first = r.execute(p,e,e.chunks[0].id,{'seed':0}); e.link_transition(e.chunks[1], first.transition); repo.save(p,[e],artifacts=[first.artifact],transitions=[__import__('dataclasses').replace(first.transition,target_chunk_id=e.chunks[1].id)]); repo.close()
        repo = SQLiteProjectRepository(root,'f7.sqlite3'); p,es = repo.load(p.id); e=es[0]; r2=_Runner(repo); out=ChainExecutionUseCase(repo,r2).run(p,e,lambda i,c:{'seed':i},transition_materializer=lambda t:t.source_output.uri); self.assertEqual(out.outcome,ChainOutcome.COMPLETE); self.assertEqual(r2.calls,[str(e.chunks[1].id)]); repo.close()

    def test_three_chunk_reopen_last_safe_point(self):
        out,r,repo,p,e=self.run_chain(3); self.assertEqual(out.outcome,ChainOutcome.COMPLETE); calls=len(r.calls); repo.close(); repo=SQLiteProjectRepository(Path(repo.root),'f7.sqlite3'); p,es=repo.load(p.id); e=es[0]; r2=_Runner(repo); self.assertEqual(ChainExecutionUseCase(repo,r2).run(p,e,lambda i,c:{}).outcome,ChainOutcome.COMPLETE); self.assertEqual(r2.calls,[]); self.assertEqual(len(repo.load_transitions(e.id)),2); repo.close(); self.assertEqual(calls,3)

    def test_crash_window_provisional_without_target_fails_closed(self):
        root,repo,p,e=self.make(2); e.transition(Lifecycle.RUNNING); a=e.chunks[0].new_attempt(); a.transition(Lifecycle.RUNNING); a.transition(Lifecycle.SUCCEEDED,output=OutputRef('media/chunk-0.mp4'),evidence=Evidence('ok')); e.chunks[0].transition(Lifecycle.RUNNING); e.chunks[0].transition(Lifecycle.SUCCEEDED); t=TransitionFrame(p.id,e.id,e.chunks[0].id,a.id,a.output,4,5); repo.save(p,[e],transitions=[t]); r=_Runner(repo); out=ChainExecutionUseCase(repo,r).run(p,e,lambda i,c:{}); self.assertEqual(out.outcome,ChainOutcome.BLOCKED); self.assertEqual(r.calls,[]); repo.close()

    def test_failed_chunk_preserves_old_attempt_and_f6_retry_budget(self):
        root,repo,p,e=self.make(2); r=_Runner(repo,fail_at=0); out=ChainExecutionUseCase(repo,r).run(p,e,lambda i,c:{}); self.assertEqual(out.outcome,ChainOutcome.BLOCKED); repo.close(); repo=SQLiteProjectRepository(root,'f7.sqlite3'); _,es=repo.load(p.id); self.assertEqual(len(es[0].chunks[0].attempts),1); self.assertEqual(es[0].chunks[0].attempts[0].state,Lifecycle.FAILED); repo.close()

    def test_repeated_resume_is_idempotent_no_duplicate_submit_or_links(self):
        out,r,repo,p,e=self.run_chain(2); self.assertEqual(ChainExecutionUseCase(repo,r).run(p,e,lambda i,c:{}).outcome,ChainOutcome.COMPLETE); self.assertEqual(len(r.calls),2); self.assertEqual(len(repo.load_transitions(e.id)),1); repo.close()

    def test_missing_invalid_provenance_and_frame_fail_closed(self):
        root,repo,p,e=self.make(2); e.transition(Lifecycle.RUNNING); a=e.chunks[0].new_attempt(); a.transition(Lifecycle.RUNNING); a.transition(Lifecycle.SUCCEEDED,output=OutputRef('media/chunk-0.mp4'),evidence=Evidence('ok')); e.chunks[0].transition(Lifecycle.RUNNING); e.chunks[0].transition(Lifecycle.SUCCEEDED); repo.save(p,[e]); r=_Runner(repo); self.assertEqual(ChainExecutionUseCase(repo,r).run(p,e,lambda i,c:{}).outcome,ChainOutcome.BLOCKED); repo.close()
        with self.assertRaises(DomainError): TransitionFrame(p.id,e.id,e.chunks[0].id,a.id,a.output,5,5)

    def test_execution_never_succeeds_without_required_links(self):
        out,r,repo,p,e=self.run_chain(2); self.assertEqual(e.state,Lifecycle.SUCCEEDED); repo.db.execute('DELETE FROM transitions'); repo.db.execute("UPDATE executions SET state='running'"); repo.close(); repo=SQLiteProjectRepository(root:=Path(repo.root),'f7.sqlite3'); p,es=repo.load(p.id); e=es[0]; self.assertEqual(ChainExecutionUseCase(repo,_Runner(repo)).run(p,e,lambda i,c:{}).outcome,ChainOutcome.BLOCKED); repo.close()

    def test_f5_provisional_transition_compatibility(self):
        root,repo,p,e=self.make(2); a=e.chunks[0].new_attempt(); a.transition(Lifecycle.RUNNING); a.transition(Lifecycle.SUCCEEDED,output=OutputRef('media/chunk-0.mp4'),evidence=Evidence('ok')); e.chunks[0].transition(Lifecycle.RUNNING); e.chunks[0].transition(Lifecycle.SUCCEEDED); repo.save(p,[e],transitions=[TransitionFrame(p.id,e.id,e.chunks[0].id,a.id,a.output,4,5,None)]); self.assertIsNone(repo.load_transitions(e.id)[0].target_chunk_id); repo.close()

    def test_sqlite_reconciliation_rejects_mismatched_source_attempt(self):
        root,repo,p,e=self.make(2); a=e.chunks[0].new_attempt(); a.transition(Lifecycle.RUNNING); a.transition(Lifecycle.SUCCEEDED,output=OutputRef('media/chunk-0.mp4'),evidence=Evidence('ok')); e.chunks[0].transition(Lifecycle.RUNNING); e.chunks[0].transition(Lifecycle.SUCCEEDED); bad=TransitionFrame(p.id,e.id,e.chunks[0].id,a.id,OutputRef('media/other.mp4'),4,5,e.chunks[1].id)
        repo.save(p,[e],transitions=[bad]); repo.close()
        repo2=SQLiteProjectRepository(root,'f7.sqlite3')
        with self.assertRaises(PersistenceDataError): repo2.load(p.id)
        repo2.close()

    def test_three_chunk_reopen_at_both_safe_boundaries_with_real_sqlite(self):
        root, repo, p, e = self.make(3)
        class StopBeforeSubmit:
            def __init__(self, order): self.order = order
            def __call__(self, i, c):
                if c.order == self.order: raise RuntimeError('SAFE_BOUNDARY')
                return {'seed': i}
        r1 = _Runner(repo)
        with self.assertRaisesRegex(RuntimeError, 'SAFE_BOUNDARY'):
            ChainExecutionUseCase(repo, r1).run(p, e, StopBeforeSubmit(1), transition_materializer=lambda t:t.source_output.uri)
        self.assertEqual(r1.calls, [str(e.chunks[0].id)])
        links = repo.load_transitions(e.id); self.assertEqual(len(links), 1)
        repo.close()
        repo = SQLiteProjectRepository(root, 'f7.sqlite3'); p, es = repo.load(p.id); e = es[0]
        r2 = _Runner(repo)
        with self.assertRaisesRegex(RuntimeError, 'SAFE_BOUNDARY'):
            ChainExecutionUseCase(repo, r2).run(p, e, StopBeforeSubmit(2), transition_materializer=lambda t:t.source_output.uri)
        self.assertEqual(r2.calls, [str(e.chunks[1].id)])
        self.assertEqual(r2.prompts[0]['first_frame'], links[0].source_output.uri)
        links = repo.load_transitions(e.id); self.assertEqual(len(links), 2)
        repo.close()
        repo = SQLiteProjectRepository(root, 'f7.sqlite3'); p, es = repo.load(p.id); e = es[0]
        r3 = _Runner(repo); out = ChainExecutionUseCase(repo, r3).run(p, e, lambda i,c: {}, transition_materializer=lambda t:t.source_output.uri)
        self.assertEqual(out.outcome, ChainOutcome.COMPLETE)
        self.assertEqual(r3.calls, [str(e.chunks[2].id)])
        self.assertEqual(r3.prompts[0]['first_frame'], links[1].source_output.uri)
        self.assertEqual(len(repo.load_transitions(e.id)), 2); self.assertEqual(len(e.chunks[0].attempts), 1); self.assertEqual(len(e.chunks[1].attempts), 1); self.assertEqual(len(e.chunks[2].attempts), 1)
        repo.close()

    def test_in_chain_f6_resume_use_case_is_dispatched_for_failed_chunk(self):
        root, repo, p, e = self.make(2)
        failed = _Runner(repo, fail_at=0)
        self.assertEqual(ChainExecutionUseCase(repo, failed).run(p, e, lambda i,c:{}).outcome, ChainOutcome.BLOCKED)
        repo.close(); repo = SQLiteProjectRepository(root, 'f7.sqlite3'); p, es = repo.load(p.id); e = es[0]
        class Client:
            def __init__(self): self.submits=[]
            def submit(self, prompt, client_id=None): self.submits.append(prompt); return BackendJobRef('retry-2')
        class Backend:
            def __init__(self): self.observations=[]
            def observe(self, ref):
                self.observations.append(ref)
                if ref == BackendJobRef('job-0-1'):
                    from orquestador.domain.recovery import BackendJobObservation, BackendJobState
                    a=e.chunks[0].attempts[0]
                    return BackendJobObservation(str(p.id),str(e.id),str(e.chunks[0].id),str(a.id),BackendJobState.FAILED,ref)
                return HistoryResult(ref, HistoryState.SUCCEEDED, {'outputs': {}})
        client, backend = Client(), Backend(); submitter=SubmitAttemptUseCase(repo, client)
        descriptor=OutputDescriptor(BackendJobRef('retry-2'),'1','chunk-0.mp4','media','video')
        extractor=type('X',(),{'extract_last_frame':lambda self,*a:type('F',(),{'frame_index':4,'frame_count':5})()})()
        coordinator=ChunkExecutionCoordinator(repo,submitter,backend,extractor=extractor,trusted_root=root,
            correlator=lambda o,r: OutputCorrelationResult(r,OutputCorrelationStatus.VALID,(descriptor,)),
            physical_validator=lambda d,r: PhysicalOutputEvidence(d,PhysicalOutputStatus.EXISTS,r,r/'media'/'chunk-0.mp4'))
        recovery=ResumeExecutionUseCase(repo,backend,coordinator,submitter); self.assertIsInstance(recovery, ResumeExecutionUseCase); r = _Runner(repo)
        out = ChainExecutionUseCase(repo, r, recovery=recovery).run(p, e, lambda i,c:{}, transition_materializer=lambda t:t.source_output.uri)
        self.assertEqual(out.outcome, ChainOutcome.COMPLETE); self.assertEqual(len(backend.observations), 2); self.assertEqual(len(client.submits), 1); self.assertEqual(r.calls, [str(e.chunks[1].id)]); self.assertEqual(len(e.chunks[0].attempts), 2); self.assertEqual(e.chunks[0].attempts[0].state, Lifecycle.FAILED); self.assertEqual(e.chunks[0].attempts[1].state, Lifecycle.SUCCEEDED); self.assertEqual(len(repo.load_transitions(e.id)), 1); self.assertEqual(r.prompts[0]['first_frame'], 'media/chunk-0.mp4'); repo.close()

    def test_multiple_executions_recovery_reload_is_exact_and_isolated(self):
        root, repo, p, intended = self.make(2); intended.transition(Lifecycle.RUNNING); ia=intended.chunks[0].new_attempt(); ia.assign_external_job_ref(BackendJobRef('target')); ia.transition(Lifecycle.RUNNING); ia.transition(Lifecycle.FAILED,error=__import__('orquestador.domain',fromlist=['ErrorRecord']).ErrorRecord('x','target')); intended.chunks[0].transition(Lifecycle.RUNNING); intended.chunks[0].transition(Lifecycle.FAILED); other = Execution(p.id); other.add_chunk(Chunk(order=0)); other.add_chunk(Chunk(order=1)); other.transition(Lifecycle.RUNNING)
        oa=other.chunks[0].new_attempt(); oa.assign_external_job_ref(BackendJobRef('other')); oa.transition(Lifecycle.RUNNING); oa.transition(Lifecycle.FAILED, error=__import__('orquestador.domain',fromlist=['ErrorRecord']).ErrorRecord('x','other')); other.chunks[0].transition(Lifecycle.RUNNING); other.chunks[0].transition(Lifecycle.FAILED); repo.save(p,[other,intended]); repo.close(); repo=SQLiteProjectRepository(root,'f7.sqlite3'); p,es=repo.load(p.id); intended=next(x for x in es if x.id==intended.id); other=next(x for x in es if x.id==other.id)
        class B:
            def observe(self,ref):
                from orquestador.domain.recovery import BackendJobObservation,BackendJobState
                c=intended.chunks[0]; a=c.attempts[-1]; return BackendJobObservation(str(p.id),str(intended.id),str(c.id),str(a.id),BackendJobState.FAILED,ref)
        class C:
            def submit(self,prompt,client_id=None): return BackendJobRef('retry')
        class Recovery:
            def resume(self, project_id, execution_id, *, prompt, project):
                loaded = self.repo.load(project_id)[1]; target = next(x for x in loaded if x.id == execution_id)
                c = target.chunks[0]; a = c.new_attempt(); a.assign_external_job_ref(BackendJobRef('target-retry'))
                c.reopen_for_retry(); c.transition(Lifecycle.RUNNING); a.transition(Lifecycle.RUNNING); a.transition(Lifecycle.SUCCEEDED, output=OutputRef('media/chunk-0.mp4'), evidence=Evidence('recovered')); c.transition(Lifecycle.SUCCEEDED)
                out = OutputRef('media/chunk-0.mp4')
                self.repo.save(project, [target])
                return type('RR', (), {'completion': ChunkExecutionResult(True, 'completed', str(a.id), Artifact(project.id,target.id,c.id,a.id,Phase.OUTPUT,out), TransitionFrame(project.id,target.id,c.id,a.id,out,4,5))})()
            def __init__(self, repo): self.repo = repo
        recovery = Recovery(repo); runner = _Runner(repo)
        target, untouched = es[-1], es[0]
        self.assertNotEqual(repo.load(p.id)[1][0].id, target.id)  # old refreshed[0] would be wrong
        out = ChainExecutionUseCase(repo, runner, recovery=recovery).run(p, target, lambda i,c:{'seed':i}, transition_materializer=lambda t:t.source_output.uri)
        self.assertEqual(out.outcome, ChainOutcome.COMPLETE); self.assertEqual(runner.calls, [str(target.chunks[1].id)])
        _, reopened=repo.load(p.id); target=next(x for x in reopened if x.id==target.id); untouched=next(x for x in reopened if x.id==untouched.id)
        self.assertEqual(len(target.chunks[0].attempts),2); self.assertEqual(len(untouched.chunks[0].attempts),1); self.assertEqual(repo.load_transitions(untouched.id),[]); self.assertEqual(repo.load_transitions(target.id)[0].execution_id,target.id); repo.close()

    def test_reopen_for_retry_requires_exact_durable_window_a_state(self):
        valid = Chunk(order=0); valid.transition(Lifecycle.RUNNING); a1=valid.new_attempt(); a1.transition(Lifecycle.RUNNING); a1.transition(Lifecycle.FAILED, error=__import__('orquestador.domain',fromlist=['ErrorRecord']).ErrorRecord('x','x')); valid.transition(Lifecycle.FAILED); a2=valid.new_attempt(); a2.assign_external_job_ref(BackendJobRef('r'))
        valid.reopen_for_retry(); self.assertEqual(valid.state, Lifecycle.PENDING)
        def bad(chunk):
            with self.assertRaises(DomainError): chunk.reopen_for_retry()
        for state in (Lifecycle.RUNNING, Lifecycle.SUCCEEDED):
            c=Chunk(order=0); c.transition(Lifecycle.RUNNING); x=c.new_attempt(); x.transition(Lifecycle.RUNNING); x.transition(Lifecycle.FAILED, error=__import__('orquestador.domain',fromlist=['ErrorRecord']).ErrorRecord('x','x')); c.transition(Lifecycle.FAILED); y=c.new_attempt(); y.assign_external_job_ref(BackendJobRef('r')); y.state=state; bad(c)

    def test_resume_crash_after_attempt_two_bind_reopens_without_resubmit(self):
        root,repo,p,e=self.make(1); e.transition(Lifecycle.RUNNING); a=e.chunks[0].new_attempt(); a.assign_external_job_ref(BackendJobRef('a1')); a.transition(Lifecycle.RUNNING); a.transition(Lifecycle.FAILED,error=__import__('orquestador.domain',fromlist=['ErrorRecord']).ErrorRecord('x','f')); e.chunks[0].transition(Lifecycle.RUNNING); e.chunks[0].transition(Lifecycle.FAILED); repo.save(p,[e])
        class B:
            def __init__(self): self.n=0; self.refs=[]
            def observe(self,ref):
                self.n+=1; self.refs.append(ref)
                from orquestador.domain.recovery import BackendJobObservation,BackendJobState
                c=e.chunks[0]; a=c.attempts[-1]
                if self.n==1:return BackendJobObservation(str(p.id),str(e.id),str(c.id),str(a.id),BackendJobState.FAILED,ref)
                raise RuntimeError('SIMULATED_PROCESS_CRASH')
        class C:
            def __init__(self): self.submits=[]
            def submit(self,prompt,client_id=None): self.submits.append(prompt); return BackendJobRef('a2')
        b,c=B(),C()
        with self.assertRaisesRegex(RuntimeError,'SIMULATED_PROCESS_CRASH'): ResumeExecutionUseCase(repo,b,object(),SubmitAttemptUseCase(repo,c)).resume(p.id,e.id,prompt={},project=p)
        repo.close(); repo=SQLiteProjectRepository(root,'f7.sqlite3'); p,es=repo.load(p.id); e=es[0]; self.assertEqual(len(e.chunks[0].attempts),2); self.assertEqual(e.chunks[0].state,Lifecycle.PENDING); self.assertEqual(e.chunks[0].attempts[-1].external_job_ref,BackendJobRef('a2')); self.assertEqual(b.n,2); self.assertEqual(b.refs[-1],BackendJobRef('a2'))
        class Queued:
            def __init__(self): self.refs=[]
            def observe(self,ref):
                self.refs.append(ref); from orquestador.domain.recovery import BackendJobObservation,BackendJobState
                a=e.chunks[0].attempts[1]; return BackendJobObservation(str(p.id),str(e.id),str(e.chunks[0].id),str(a.id),BackendJobState.QUEUED,ref)
        qb=Queued(); sub=SubmitAttemptUseCase(repo,c); before_submits=len(c.submits); self.assertEqual(ResumeExecutionUseCase(repo,qb,object(),sub).resume(p.id,e.id,prompt={}).outcome,RecoveryOutcome.WAIT); self.assertEqual(qb.refs,[BackendJobRef('a2')]); self.assertEqual(len(c.submits),before_submits)

        # B4: a completely fresh process observes the durable Attempt 2 as
        # completed and executes the real F5 completion path.
        repo.close(); repo=SQLiteProjectRepository(root,'f7.sqlite3'); p,es=repo.load(p.id); e=es[0]; c=e.chunks[0]; a2=c.attempts[1]
        class CompletedBackend:
            def __init__(self): self.refs=[]
            def observe(self, ref):
                self.refs.append(ref)
                self.assert_ref = ref
                return HistoryResult(ref, HistoryState.SUCCEEDED, {'outputs': {}})
        class FreshSubmitter:
            def __init__(self): self.calls=[]
            def submit(self, prompt, client_id=None): self.calls.append(prompt); return BackendJobRef('unexpected')
        backend=CompletedBackend(); client=FreshSubmitter(); submitter=SubmitAttemptUseCase(repo,client)
        descriptor=OutputDescriptor(BackendJobRef('a2'),'1','chunk-0.mp4','media','video')
        correlation=OutputCorrelationResult(BackendJobRef('a2'),OutputCorrelationStatus.VALID,(descriptor,))
        physical=PhysicalOutputEvidence(descriptor,PhysicalOutputStatus.EXISTS,root,root/'media'/'chunk-0.mp4')
        extractor=type('X',(),{'extract_last_frame':lambda self,*args:type('F',(),{'frame_index':4,'frame_count':5})()})()
        coordinator=ChunkExecutionCoordinator(repo,submitter,backend,extractor=extractor,trusted_root=root,
            correlator=lambda observed,ref: correlation,
            physical_validator=lambda descriptor,root_path: physical)
        production=ResumeExecutionUseCase(repo,backend,coordinator,submitter)
        completed=production.resume(p.id,e.id,prompt={})
        self.assertEqual(completed.outcome,RecoveryOutcome.RETRIED_COMPLETE)
        self.assertEqual(backend.refs,[BackendJobRef('a2')]); self.assertEqual(client.calls,[])
        p,es=repo.load(p.id); e=es[0]
        self.assertEqual(len(e.chunks[0].attempts),2); self.assertEqual(e.chunks[0].attempts[0].state,Lifecycle.FAILED); self.assertEqual(e.chunks[0].attempts[1].state,Lifecycle.SUCCEEDED)
        self.assertEqual(e.chunks[0].attempts[1].id,a2.id); self.assertEqual(e.chunks[0].attempts[1].number,a2.number); self.assertEqual(e.chunks[0].attempts[1].external_job_ref,BackendJobRef('a2')); self.assertEqual(e.chunks[0].attempts[1].output,OutputRef('media/chunk-0.mp4')); self.assertIsNotNone(e.chunks[0].attempts[1].evidence)
        self.assertEqual(e.state,Lifecycle.SUCCEEDED); self.assertEqual(len(e.artifacts),1); self.assertEqual(len(repo.load_transitions(e.id)),1); self.assertEqual(repo.load_transitions(e.id)[0].source_frame_index,4); self.assertEqual(repo.load_transitions(e.id)[0].frame_count,5); repo.close()

        # B5: another fresh process resumes the completed execution idempotently.
        repo=SQLiteProjectRepository(root,'f7.sqlite3'); p,es=repo.load(p.id); e=es[0]; a2=e.chunks[0].attempts[1]
        backend2=CompletedBackend(); client2=FreshSubmitter(); submitter2=SubmitAttemptUseCase(repo,client2)
        coordinator2=ChunkExecutionCoordinator(repo,submitter2,backend2,extractor=extractor,trusted_root=root,
            correlator=lambda observed,ref: correlation, physical_validator=lambda descriptor,root_path: physical)
        production2=ResumeExecutionUseCase(repo,backend2,coordinator2,submitter2)
        again=production2.resume(p.id,e.id,prompt={})
        self.assertEqual(again.outcome,RecoveryOutcome.COMPLETE); self.assertEqual(backend2.refs,[]); self.assertEqual(client2.calls,[])
        p,es=repo.load(p.id); e=es[0]
        self.assertEqual(len(e.chunks[0].attempts),2); self.assertEqual(len(e.artifacts),1); self.assertEqual(len(repo.load_transitions(e.id)),1); self.assertEqual((e.chunks[0].attempts[1].id,e.chunks[0].attempts[1].number,e.chunks[0].attempts[1].external_job_ref,e.chunks[0].attempts[1].output),(a2.id,a2.number,BackendJobRef('a2'),OutputRef('media/chunk-0.mp4'))); self.assertEqual(e.state,Lifecycle.SUCCEEDED); repo.close()

    def test_chunk_reopen_for_retry_contract_is_exhaustive(self):
        def make(state=Lifecycle.FAILED, count=2, nums=None, s1=Lifecycle.FAILED, s2=Lifecycle.PENDING, ref=True):
            c=Chunk(order=0); c.state=state
            for i in range(count):
                a=__import__('orquestador.domain',fromlist=['Attempt']).Attempt(number=(nums or list(range(1,count+1)))[i])
                if i==0: a.state=s1
                elif i==1: a.state=s2; a.external_job_ref=BackendJobRef('retry') if ref else None
                c.attempts.append(a)
            return c
        cases=[make(state=Lifecycle.RUNNING), make(count=0), make(count=1), make(count=3), make(nums=[1,3]), make(s1=Lifecycle.RUNNING), make(s2=Lifecycle.RUNNING), make(ref=False)]
        for c in cases:
            with self.subTest(c):
                with self.assertRaises(DomainError): c.reopen_for_retry()
        c=make(); before=[(a.number,a.state,a.external_job_ref) for a in c.attempts]; c.reopen_for_retry()
        self.assertEqual(c.state,Lifecycle.PENDING); self.assertEqual([(a.number,a.state,a.external_job_ref) for a in c.attempts],before)

    def test_resume_window_a_bound_attempt_two_while_chunk_failed_recovers_end_to_end(self):
        root,repo,p,e=self.make(1); e.transition(Lifecycle.RUNNING); c=e.chunks[0]
        a1=c.new_attempt(); a1.assign_external_job_ref(BackendJobRef('a1')); a1.transition(Lifecycle.RUNNING); a1.transition(Lifecycle.FAILED,error=__import__('orquestador.domain',fromlist=['ErrorRecord']).ErrorRecord('x','failed'))
        c.transition(Lifecycle.RUNNING); c.transition(Lifecycle.FAILED); a2=c.new_attempt(); a2.assign_external_job_ref(BackendJobRef('a2')); repo.save(p,[e]); repo.close()
        class B:
            def __init__(self,state): self.state=state; self.refs=[]
            def observe(self,ref):
                self.refs.append(ref)
                if self.state=='wait':
                    from orquestador.domain.recovery import BackendJobObservation,BackendJobState
                    return BackendJobObservation(str(p.id),str(e.id),str(c.id),str(a2.id),BackendJobState.QUEUED,ref)
                return HistoryResult(ref,HistoryState.SUCCEEDED,{'outputs':{}})
        class S:
            def __init__(self): self.calls=[]
            def submit(self,*a,**k): self.calls.append(1); return BackendJobRef('unexpected')
        def composition(r,b,s):
            d=OutputDescriptor(BackendJobRef('a2'),'1','chunk-0.mp4','media','video'); corr=OutputCorrelationResult(BackendJobRef('a2'),OutputCorrelationStatus.VALID,(d,)); phys=PhysicalOutputEvidence(d,PhysicalOutputStatus.EXISTS,root,root/'media'/'chunk-0.mp4')
            ex=type('X',(),{'extract_last_frame':lambda self,*x:type('F',(),{'frame_index':4,'frame_count':5})()})()
            co=ChunkExecutionCoordinator(r,s,b,extractor=ex,trusted_root=root,correlator=lambda *_:corr,physical_validator=lambda *_:phys)
            return co
        repo=SQLiteProjectRepository(root,'f7.sqlite3'); p,es=repo.load(p.id); e=es[0]; c=e.chunks[0]; a2=c.attempts[1]; b=B('wait'); s=S(); u=ResumeExecutionUseCase(repo,b,composition(repo,b,s),SubmitAttemptUseCase(repo,s)); w=u.resume(p.id,e.id,prompt={}); self.assertEqual(w.outcome,RecoveryOutcome.WAIT); self.assertEqual(len(s.calls),0); repo.close()
        repo=SQLiteProjectRepository(root,'f7.sqlite3'); p,es=repo.load(p.id); e=es[0]; c=e.chunks[0]; a2=c.attempts[1]; b=B('done'); s=S(); u=ResumeExecutionUseCase(repo,b,composition(repo,b,s),SubmitAttemptUseCase(repo,s)); done=u.resume(p.id,e.id,prompt={}); self.assertEqual(done.outcome,RecoveryOutcome.RETRIED_COMPLETE); self.assertEqual(len(s.calls),0); repo.close(); repo=SQLiteProjectRepository(root,'f7.sqlite3'); p,es=repo.load(p.id); e=es[0]; a2=e.chunks[0].attempts[1]; self.assertEqual(len(e.artifacts),1); self.assertEqual(len(repo.load_transitions(e.id)),1); ids=(a2.id,a2.number,a2.external_job_ref); repo.close()
        repo=SQLiteProjectRepository(root,'f7.sqlite3'); p,es=repo.load(p.id); e=es[0]; b=B('done'); s=S(); u=ResumeExecutionUseCase(repo,b,composition(repo,b,s),SubmitAttemptUseCase(repo,s)); again=u.resume(p.id,e.id); self.assertEqual(again.outcome,RecoveryOutcome.COMPLETE); self.assertEqual(len(s.calls),0); self.assertEqual(len(e.artifacts),1); self.assertEqual(len(repo.load_transitions(e.id)),1); self.assertEqual((e.chunks[0].attempts[1].id,e.chunks[0].attempts[1].number,e.chunks[0].attempts[1].external_job_ref),ids); self.assertEqual(len(e.chunks[0].attempts),2); repo.close()

if __name__ == '__main__': unittest.main()
