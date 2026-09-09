import os, tempfile, unittest
from copy import copy
from pathlib import Path
from orquestador.domain import Project, ProjectId, Execution, ExecutionId, Chunk, ChunkId, BackendJobRef, Lifecycle, OutputRef, Evidence
from orquestador.application import SubmitAttemptUseCase, SubmitOutcome, ComfyUIJobBridge
from orquestador.persistence.sqlite import SQLiteProjectRepository, PersistenceError
from orquestador.adapters.http import ComfyUIRejectedError, ComfyUIProtocolError

class FakeClient:
    def __init__(self, result=None, error=None): self.result, self.error, self.calls, self.seen = result, error, 0, None
    def submit(self, prompt, client_id=None):
        self.calls += 1; self.seen = prompt['observe']();
        if self.error: raise self.error
        return self.result

class NonPersistenceBinding:
    def bind(self, *args, **kwargs): raise ValueError('binding identity mismatch')

class PreSubmitFailure:
    def save(self, *args): raise RuntimeError('pre-submit save failed')

class SubmitAttemptTests(unittest.TestCase):
    def make(self, repo):
        p=Project(ProjectId('p')); e=Execution(p.id,ExecutionId('e')); c=Chunk(ChunkId('c')); e.add_chunk(c); return p,e,c

    def test_structured_rejection_and_protocol_are_precise_and_durable(self):
        for error, outcome, marker in ((ComfyUIRejectedError('bad', 422, '{"error":"x"}'), SubmitOutcome.REJECTED, 'status=422'), (ComfyUIProtocolError('missing prompt_id'), SubmitOutcome.PROTOCOL_FAILED, 'protocol_failure')):
            with tempfile.TemporaryDirectory() as d:
                r=SQLiteProjectRepository(d); p,e,c=self.make(r); cl=FakeClient(error=error)
                x=SubmitAttemptUseCase(r,cl).submit(p,e,'c',{'observe':lambda:None})
                self.assertEqual(x.outcome,outcome); self.assertIn(marker,x.error); self.assertEqual(cl.calls,1)
                self.assertIsNone(r.load('p')[1][0].chunks[0].attempts[0].external_job_ref); r.close()
    def test_durable_before_submit_and_reload(self):
        with tempfile.TemporaryDirectory() as d:
            r=SQLiteProjectRepository(d); p,e,c=self.make(r); client=FakeClient(BackendJobRef('j'))
            result=SubmitAttemptUseCase(r,client).submit(p,e,'c',{'observe':lambda: r.load('p')[1][0].chunks[0].attempts[0].external_job_ref})
            self.assertIsNone(client.seen); self.assertEqual(result.outcome,SubmitOutcome.SUCCEEDED)
            self.assertEqual(r.load('p')[1][0].chunks[0].attempts[0].external_job_ref,BackendJobRef('j')); r.close()
    def test_runtime_error_propagates_and_is_not_ambiguous_or_retried(self):
        with tempfile.TemporaryDirectory() as d:
            r=SQLiteProjectRepository(d); p,e,c=self.make(r); cl=FakeClient(error=RuntimeError('unknown'))
            with self.assertRaises(RuntimeError): SubmitAttemptUseCase(r,cl).submit(p,e,'c',{'observe':lambda:None})
            self.assertEqual(cl.calls,1); self.assertEqual(len(e.chunks[0].attempts),1); r.close()
    def test_empty_and_unsupported_refs_are_invalid(self):
        for value in (None, '', object()):
            with tempfile.TemporaryDirectory() as d:
                r=SQLiteProjectRepository(d); p,e,c=self.make(r); cl=FakeClient(value)
                x=SubmitAttemptUseCase(r,cl).submit(p,e,'c',{'observe':lambda:None})
                self.assertEqual(x.outcome, SubmitOutcome.INVALID_REF); self.assertEqual(cl.calls, 1); r.close()
    def test_binding_domain_failure_is_distinct(self):
        with tempfile.TemporaryDirectory() as d:
            r=SQLiteProjectRepository(d); p,e,c=self.make(r); cl=FakeClient(BackendJobRef('j'))
            x=SubmitAttemptUseCase(r,cl,NonPersistenceBinding()).submit(p,e,'c',{'observe':lambda:None})
            self.assertEqual(x.outcome, SubmitOutcome.BIND_FAILED); self.assertEqual(cl.calls, 1); r.close()

    def test_pre_submit_save_failure_propagates_without_submit(self):
        p,e,c=self.make(None); cl=FakeClient(BackendJobRef('j'))
        with self.assertRaises(RuntimeError): SubmitAttemptUseCase(PreSubmitFailure(),cl).submit(p,e,'c',{'observe':lambda:None})
        self.assertEqual(cl.calls,0)

    def test_post_submit_bind_failure_is_honest_and_unbound(self):
        class BadRepo:
            def __init__(self): self.saved=0; self.snapshot=None
            def save(self, project, executions, *args):
                self.saved += 1
                if self.saved > 1: raise PersistenceError('disk')
                clones = []
                for execution in executions:
                    clone = copy(execution)
                    clone.chunks = [copy(chunk) for chunk in execution.chunks]
                    for cloned_chunk, source_chunk in zip(clone.chunks, execution.chunks):
                        cloned_chunk.attempts = [copy(attempt) for attempt in source_chunk.attempts]
                    clones.append(clone)
                self.snapshot = (copy(project), clones)
            def load(self, project_id):
                project, executions = self.snapshot
                clones = []
                for execution in executions:
                    clone = copy(execution)
                    clone.chunks = [copy(chunk) for chunk in execution.chunks]
                    for cloned_chunk, source_chunk in zip(clone.chunks, execution.chunks):
                        cloned_chunk.attempts = [copy(attempt) for attempt in source_chunk.attempts]
                    clones.append(clone)
                return copy(project), clones
        repo=BadRepo(); p,e,c=self.make(repo); cl=FakeClient(BackendJobRef('j'))
        x=SubmitAttemptUseCase(repo,cl).submit(p,e,'c',{'observe':lambda:None})
        self.assertEqual(x.outcome,SubmitOutcome.BIND_FAILED); self.assertEqual(cl.calls,1)
        self.assertIsNone(e.chunks[0].attempts[0].external_job_ref)
        reloaded = repo.load('p')[1][0].chunks[0].attempts[0]
        self.assertIsNone(reloaded.external_job_ref)

    def test_second_different_ref_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            r=SQLiteProjectRepository(d); p,e,c=self.make(r)
            bridge=ComfyUIJobBridge(r); a=c.new_attempt(); r.save(p,[e])
            bridge.bind(p,e,'c',str(a.id),BackendJobRef('first'),execution_id=e.id)
            with self.assertRaises(ValueError): bridge.bind(p,e,'c',str(a.id),BackendJobRef('second'),execution_id=e.id)
            r.close()

    def test_independent_use_cases_submit_once_and_create_separate_attempts(self):
        with tempfile.TemporaryDirectory() as d:
            r=SQLiteProjectRepository(d); p,e,c=self.make(r)
            client1=FakeClient(BackendJobRef('a'))
            a=SubmitAttemptUseCase(r,client1).submit(p,e,'c',{'observe':lambda:None})
            first_attempt = e.chunks[0].attempts[0]
            first_attempt.transition(Lifecycle.RUNNING)
            first_attempt.transition(Lifecycle.SUCCEEDED, output=OutputRef('file://first'), evidence=Evidence('valid output'))
            r.save(p,[e])
            client2=FakeClient(BackendJobRef('b'))
            b=SubmitAttemptUseCase(r,client2).submit(p,e,'c',{'observe':lambda:None})
            self.assertEqual(client1.calls,1); self.assertEqual(client2.calls,1)
            self.assertEqual(a.outcome,SubmitOutcome.SUCCEEDED); self.assertEqual(b.outcome,SubmitOutcome.SUCCEEDED)
            attempts=r.load('p')[1][0].chunks[0].attempts
            self.assertEqual(len(attempts),2); self.assertNotEqual(a.attempt_id,b.attempt_id)
            self.assertEqual(attempts[0].state, Lifecycle.SUCCEEDED)
            self.assertEqual(attempts[0].output, OutputRef('file://first'))
            self.assertEqual(attempts[0].evidence, Evidence('valid output'))
            r.close()

if __name__ == '__main__': unittest.main()
