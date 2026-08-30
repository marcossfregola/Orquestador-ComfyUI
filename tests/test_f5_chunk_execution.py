import tempfile, unittest
from pathlib import Path
from unittest.mock import Mock
from orquestador.domain.core import (Artifact, Chunk, Execution, Evidence,
    Lifecycle, OutputRef, Phase, Project, TransitionFrame)
from orquestador.adapters import BackendJobRef, HistoryResult, HistoryState
from orquestador.application.chunk_execution import ChunkExecutionCoordinator
from orquestador.application.bridge import SubmitAttemptResult, SubmitOutcome

class F5ChunkTests(unittest.TestCase):
    def _coord_for(self, state, *, save=None):
        p=Project(); e=Execution(p.id); c=Chunk(order=0); e.add_chunk(c)
        ref=BackendJobRef('r'); a=c.new_attempt(); a.assign_external_job_ref(ref)
        submit=Mock(); submit.submit.return_value=SubmitAttemptResult(SubmitOutcome.SUCCEEDED,str(a.id),ref)
        coord=ChunkExecutionCoordinator(Mock() if save is None else save,submit,HistoryResult(ref,state),extractor=Mock(),trusted_root=tempfile.gettempdir())
        return coord,p,e,c,submit

    def test_monitor_unknown_never_succeeds(self):
        p=Project(); e=Execution(p.id); c=Chunk(order=0); e.add_chunk(c)
        ref=BackendJobRef('r'); a=c.new_attempt(); a.assign_external_job_ref(ref)
        submit=Mock(); submit.submit.return_value=SubmitAttemptResult(SubmitOutcome.SUCCEEDED,str(a.id),ref)
        coord=ChunkExecutionCoordinator(Mock(),submit,HistoryResult(ref,HistoryState.UNKNOWN),extractor=Mock(),trusted_root=tempfile.gettempdir())
        self.assertFalse(coord.execute(p,e,c.id,'x').success)

    def test_monitor_failed_cancelled_and_nonterminal_never_retry(self):
        for state in (HistoryState.FAILED, HistoryState.RUNNING, HistoryState.QUEUED, HistoryState.NOT_FOUND):
            with self.subTest(state=state):
                coord,p,e,c,submit=self._coord_for(state)
                result=coord.execute(p,e,c.id,'x')
                self.assertFalse(result.success); submit.submit.assert_called_once()

    def test_final_save_failure_does_not_mutate_in_memory(self):
        from orquestador.persistence.sqlite import SQLiteProjectRepository
        with tempfile.TemporaryDirectory() as d:
          real=SQLiteProjectRepository(d)
          class FailFinal:
            def __init__(self): self.calls=0
            def save(self,*args,**kwargs):
                self.calls += 1
                if self.calls == 2: raise RuntimeError('final completion save failed')
                return real.save(*args,**kwargs)
            def close(self): return real.close()
          repo=FailFinal()
          p=Project(); e=Execution(p.id); c=Chunk(order=0); e.add_chunk(c); real.save(p,[e]); ref=BackendJobRef('r'); a=c.new_attempt(); a.assign_external_job_ref(ref)
          real.save(p,[e])
          submit=Mock(); submit.submit.return_value=SubmitAttemptResult(SubmitOutcome.SUCCEEDED,str(a.id),ref)
          corr=Mock(status=type('S',(),{'value':'valid'})(),descriptors=(Mock(),))
          phys=Mock(resolved_path=Path(tempfile.gettempdir())/'x')
          extractor=Mock(); extractor.extract_last_frame.return_value=type('F',(),{'frame_index':0,'frame_count':1})()
          coord=ChunkExecutionCoordinator(repo,submit,HistoryResult(ref,HistoryState.SUCCEEDED,{}),extractor=extractor,trusted_root=tempfile.gettempdir(),correlator=lambda *_:corr,physical_validator=lambda *_:phys)
          result=coord.execute(p,e,c.id,'x')
          self.assertFalse(result.success); submit.submit.assert_called_once()
          repo.close()
          reopened=SQLiteProjectRepository(d)
          try:
            _,es=reopened.load(p.id); loaded=es[0].chunks[0]
            self.assertNotEqual(loaded.state,Lifecycle.SUCCEEDED)
            self.assertNotEqual(loaded.attempts[0].state,Lifecycle.SUCCEEDED)
            self.assertEqual(reopened.db.execute('SELECT count(*) FROM artifacts').fetchone()[0],0)
            self.assertEqual(reopened.db.execute('SELECT count(*) FROM transitions').fetchone()[0],0)
          finally: reopened.close()
          return

    def test_happy_path_durable_sqlite_reopen_preserves_output_and_transition(self):
        from orquestador.persistence.sqlite import SQLiteProjectRepository
        from orquestador.adapters.outputs import OutputCorrelationResult, OutputCorrelationStatus, OutputDescriptor
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); media=root/'media'; media.mkdir(); (media/'clip.mp4').write_bytes(b'video')
            repo=SQLiteProjectRepository(root)
            try:
              p=Project(); e=Execution(p.id); c=Chunk(order=0); e.add_chunk(c)
              prior=c.new_attempt(); prior.transition(Lifecycle.RUNNING); prior.transition(Lifecycle.SUCCEEDED, output=OutputRef('media/prior.mp4'), evidence=Evidence('prior'))
              (media/'prior.mp4').write_bytes(b'prior'); repo.save(p,[e],artifacts=[Artifact(p.id,e.id,c.id,prior.id,Phase.EXECUTE,OutputRef('media/prior.mp4'))])
              ref=BackendJobRef('durable-ref')
              def submit(*args,**kwargs):
                  a=c.new_attempt(); a.assign_external_job_ref(ref); return SubmitAttemptResult(SubmitOutcome.SUCCEEDED,str(a.id),ref)
              submitter=Mock(); submitter.submit.side_effect=submit
              desc=OutputDescriptor(ref,'1','clip.mp4','media','video')
              extractor=Mock(); extractor.extract_last_frame.return_value=type('F',(),{'frame_index':4,'frame_count':5})()
              corr=OutputCorrelationResult(ref,OutputCorrelationStatus.VALID,(desc,))
              coord=ChunkExecutionCoordinator(repo,submitter,HistoryResult(ref,HistoryState.SUCCEEDED,{'outputs':{}}),extractor=extractor,trusted_root=root,correlator=lambda *_:corr)
              result=coord.execute(p,e,c.id,'prompt')
              self.assertTrue(result.success, result.reason); repo.close()
              repo2=SQLiteProjectRepository(root)
              try:
                p2,es=repo2.load(p.id); c2=es[0].chunks[0]; a2=c2.attempts[-1]
                self.assertEqual(c2.state,Lifecycle.SUCCEEDED); self.assertEqual(a2.state,Lifecycle.SUCCEEDED)
                self.assertEqual(len(es[0].artifacts),2); self.assertEqual({a.phase for a in es[0].artifacts},{Phase.EXECUTE,Phase.OUTPUT})
                self.assertIsNotNone(result.transition)
              finally: repo2.close()
            finally:
              try: repo.close()
              except Exception: pass

    def test_transition_frame_target_none_and_second_chunk_reload(self):
        from orquestador.persistence.sqlite import SQLiteProjectRepository
        with tempfile.TemporaryDirectory() as d:
            repo=SQLiteProjectRepository(d); p=Project(); e=Execution(p.id)
            c0=Chunk(order=0); c1=Chunk(order=1); e.add_chunk(c0); e.add_chunk(c1)
            a=c0.new_attempt(); ref=BackendJobRef('j'); a.assign_external_job_ref(ref); a.transition(Lifecycle.RUNNING); a.transition(Lifecycle.SUCCEEDED, output=OutputRef('clip.mp4'), evidence=Evidence('ok'))
            repo.save(p,[e],artifacts=[Artifact(p.id,e.id,c0.id,a.id,Phase.OUTPUT,OutputRef('clip.mp4'))])
            t0=TransitionFrame(p.id,e.id,c0.id,a.id,OutputRef('clip.mp4'),2,3,None)
            t1=TransitionFrame(p.id,e.id,c0.id,a.id,OutputRef('clip.mp4'),2,3,c1.id)
            repo.save(p,[e],transitions=[t0,t1]); repo.close()
            repo2=SQLiteProjectRepository(d); _,loaded=repo2.load(p.id)
            rows=repo2.db.execute('SELECT project_id,execution_id,target_chunk_id,source_chunk_id,source_attempt_id,source_output,frame_index,frame_count FROM transitions ORDER BY target_chunk_id IS NOT NULL').fetchall()
            self.assertEqual(rows[0],(str(p.id),str(e.id),None,str(c0.id),str(a.id),'clip.mp4',2,3))
            self.assertEqual(rows[1],(str(p.id),str(e.id),str(c1.id),str(c0.id),str(a.id),'clip.mp4',2,3))
            self.assertIsNotNone(loaded[0].chunks[1].first_frame)
            repo2.close()

    def test_succeeded_without_outputs_and_ambiguous_outputs_submit_once(self):
        for raw in ({}, {'outputs':{'1':[{'filename':'a','subfolder':'','type':'x'},{'filename':'a','subfolder':'','type':'x'}]}}):
            with self.subTest(raw=raw):
                coord,p,e,c,submit=self._coord_for(HistoryState.SUCCEEDED)
                coord.monitor=HistoryResult(BackendJobRef('r'),HistoryState.SUCCEEDED,raw)
                self.assertFalse(coord.execute(p,e,c.id,'x').success); submit.submit.assert_called_once(); self.assertNotEqual(c.state,Lifecycle.SUCCEEDED)

    def test_reference_and_mapper_provenance_mismatch_fail_closed(self):
        coord,p,e,c,submit=self._coord_for(HistoryState.SUCCEEDED)
        coord.monitor=HistoryResult(BackendJobRef('other'),HistoryState.SUCCEEDED,{})
        self.assertFalse(coord.execute(p,e,c.id,'x').success); submit.submit.assert_called_once()
        coord,p,e,c,submit=self._coord_for(HistoryState.SUCCEEDED); coord.correlator=lambda *_: type('C',(),{'status':type('S',(),{'value':'valid'})(),'descriptors':(type('D',(),{'subfolder':'','filename':'x','type':'t'})(),)})()
        self.assertFalse(coord.execute(p,e,c.id,'x').success); submit.submit.assert_called_once()

    def test_extractor_bad_frame_count_and_index_each_fail_closed(self):
        for frame in (Exception('boom'), type('F',(),{'frame_index':0,'frame_count':0})(), type('F',(),{'frame_index':1,'frame_count':3})()):
            with self.subTest(frame=frame):
                coord,p,e,c,submit=self._coord_for(HistoryState.SUCCEEDED)
                coord.correlator=lambda *_: type('C',(),{'status':type('S',(),{'value':'valid'})(),'descriptors':(Mock(),)})()
                coord.physical_validator=lambda *_: type('P',(),{'resolved_path':Path(tempfile.gettempdir())/'x'})()
                coord.extractor.extract_last_frame.side_effect=frame if isinstance(frame,Exception) else None
                if not isinstance(frame,Exception): coord.extractor.extract_last_frame.return_value=frame
                self.assertFalse(coord.execute(p,e,c.id,'x').success); submit.submit.assert_called_once()
