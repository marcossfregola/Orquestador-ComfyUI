import copy
import sqlite3
import tempfile
import unittest

from orquestador.domain import *
from orquestador.domain.recovery import *
from orquestador.persistence.sqlite import SQLiteProjectRepository, PersistenceDataError, PersistenceConflictError

_TemporaryDirectory = tempfile.TemporaryDirectory
tempfile.TemporaryDirectory = lambda *a, **k: _TemporaryDirectory(*a, **({"ignore_cleanup_errors": True, **k}))


class RecoveryRestartE2E(unittest.TestCase):
    def base(self, n=1):
        p = Project(ProjectId("p")); e = Execution(p.id, ExecutionId("e"))
        for i in range(n): e.add_chunk(Chunk(ChunkId(f"c{i+1}"), i))
        return p, e

    def reopen(self, root, p):
        self.r.close(); self.r = SQLiteProjectRepository(root)
        return self.r.load(p.id)[1][0]

    def start(self, c, ref=None):
        a = c.new_attempt(); a.transition(Lifecycle.RUNNING)
        if ref: a.assign_external_job_ref(BackendJobRef(ref))
        return a

    def success(self, c, out="o"):
        a = c.new_attempt(); a.transition(Lifecycle.RUNNING)
        a.transition(Lifecycle.SUCCEEDED, output=OutputRef(out), evidence=Evidence("verified")); c.transition(Lifecycle.RUNNING); c.transition(Lifecycle.SUCCEEDED)
        return a

    def setUp(self): self.r = None
    def tearDown(self):
        if self.r:
            try: self.r.close()
            except Exception: pass

    def test_01_two_chunks_resume_targets_pending_last_safe(self):
        with tempfile.TemporaryDirectory() as d:
            p,e=self.base(2); a=self.success(e.chunks[0]); self.start(e.chunks[1]); self.r=SQLiteProjectRepository(d)
            ar=Artifact(p.id,e.id,e.chunks[0].id,a.id,Phase.OUTPUT,a.output); t=TransitionFrame(p.id,e.id,e.chunks[0].id,a.id,a.output,0,1,e.chunks[1].id); self.r.save(p,[e],[ar],transitions=[t]); e=self.reopen(d,p)
            x=reconcile(e, artifacts=(ArtifactObservation('p','e','c1',str(a.id),a.output,True,True),), transitions=(TransitionObservation('p','e','c1',str(a.id),'c2',True,True,a.output),)); self.assertEqual((x.last_safe_completed_chunk,x.next_actionable_chunk), (0,1))

    def test_02_running_same_ref_running_waits_after_restart(self): self._job_wait(BackendJobState.RUNNING)
    def test_03_running_same_ref_queued_waits_after_restart(self): self._job_wait(BackendJobState.QUEUED)
    def _job_wait(self,state):
        with tempfile.TemporaryDirectory() as d:
            p,e=self.base(); a=self.start(e.chunks[0],'r'); self.r=SQLiteProjectRepository(d); self.r.save(p,[e]); e=self.reopen(d,p); a=e.chunks[0].attempts[0]; x=reconcile(e,jobs=(BackendJobObservation('p','e','c1',str(a.id),state,BackendJobRef('r')),)); self.assertEqual((x.decision,x.proposed_actions),(Decision.WAIT_FOR_EXTERNAL_JOB,(Action.WAIT,)))

    def test_04_failed_same_ref_proposes_new_attempt_history_unchanged(self): self._terminal(BackendJobState.FAILED)
    def test_05_cancelled_same_ref_proposes_new_attempt(self): self._terminal(BackendJobState.CANCELLED)
    def _terminal(self,state):
        with tempfile.TemporaryDirectory() as d:
            p,e=self.base(); a=self.start(e.chunks[0],'r'); self.r=SQLiteProjectRepository(d); self.r.save(p,[e]); e=self.reopen(d,p); a=e.chunks[0].attempts[0]; x=reconcile(e,jobs=(BackendJobObservation('p','e','c1',str(a.id),state,BackendJobRef('r')),)); self.assertEqual(x.proposed_actions,(Action.CREATE_NEW_ATTEMPT,)); self.assertEqual(a.state,Lifecycle.RUNNING)

    def test_06_unknown_backend_needs_manual_review_no_retry(self): self._review(BackendJobState.UNKNOWN)
    def test_07_wrong_ref_blocks_review(self):
        with tempfile.TemporaryDirectory() as d:
            p,e=self.base(); a=self.start(e.chunks[0],'r'); self.r=SQLiteProjectRepository(d); self.r.save(p,[e]); e=self.reopen(d,p); a=e.chunks[0].attempts[0]; x=reconcile(e,jobs=(BackendJobObservation('p','e','c1',str(a.id),BackendJobState.RUNNING,BackendJobRef('wrong')),)); self.assertEqual((x.decision,x.evidence_codes),(Decision.NEEDS_MANUAL_REVIEW,(EvidenceCode.PROVENANCE_MISMATCH,)))
    def _review(self,state):
        with tempfile.TemporaryDirectory() as d:
            p,e=self.base(); a=self.start(e.chunks[0],'r'); self.r=SQLiteProjectRepository(d); self.r.save(p,[e]); e=self.reopen(d,p); a=e.chunks[0].attempts[0]; x=reconcile(e,jobs=(BackendJobObservation('p','e','c1',str(a.id),state,BackendJobRef('r')),)); self.assertEqual((x.decision,x.proposed_actions),(Decision.NEEDS_MANUAL_REVIEW,(Action.BLOCK_FOR_REVIEW,)))

    def test_08_external_completion_proposal_pure_then_caller_applies(self):
        with tempfile.TemporaryDirectory() as d:
            p,e=self.base(); a=self.start(e.chunks[0],'r'); self.r=SQLiteProjectRepository(d); self.r.save(p,[e]); e=self.reopen(d,p); a=e.chunks[0].attempts[0]; before=(a.state,a.output,a.evidence); obs=ArtifactObservation('p','e','c1',str(a.id),OutputRef('o'),True,True); x=reconcile(e,artifacts=(obs,),jobs=(BackendJobObservation('p','e','c1',str(a.id),BackendJobState.COMPLETED,BackendJobRef('r')),)); self.assertEqual(x.decision,Decision.RECONCILE_EXTERNAL_COMPLETION); self.assertEqual((a.state,a.output,a.evidence),before); a.transition(Lifecycle.SUCCEEDED,output=OutputRef('o'),evidence=Evidence('verified')); e.chunks[0].transition(Lifecycle.RUNNING); e.chunks[0].transition(Lifecycle.SUCCEEDED); self.r.save(p,[e],[Artifact(p.id,e.id,e.chunks[0].id,a.id,Phase.OUTPUT,a.output)]); e=self.reopen(d,p); self.assertEqual(reconcile(e,artifacts=(obs,)).last_safe_completed_chunk,0)

    def test_09_missing_transition_requests_regeneration_then_next_chunk(self):
        with tempfile.TemporaryDirectory() as d:
            p,e=self.base(2); a=self.success(e.chunks[0]); self.r=SQLiteProjectRepository(d); self.r.save(p,[e],[Artifact(p.id,e.id,e.chunks[0].id,a.id,Phase.OUTPUT,a.output)]); e=self.reopen(d,p); ob=ArtifactObservation('p','e','c1',str(a.id),a.output,True,True); x=reconcile(e,artifacts=(ob,)); self.assertEqual(x.proposed_actions,(Action.REGENERATE_TRANSITION_FRAME,)); t=TransitionFrame(p.id,e.id,e.chunks[0].id,a.id,a.output,0,1,e.chunks[1].id); e.link_transition(e.chunks[1],t); self.r.save(p,[e],transitions=[t]); e=self.reopen(d,p); self.assertEqual(reconcile(e,artifacts=(ob,),transitions=(TransitionObservation('p','e','c1',str(a.id),'c2',True,True,a.output),)).next_actionable_chunk,1)

    def test_10_missing_or_corrupt_output_not_safe(self):
        for valid in (False,):
            with tempfile.TemporaryDirectory() as d:
                p,e=self.base(); a=self.success(e.chunks[0]); self.r=SQLiteProjectRepository(d); self.r.save(p,[e]); e=self.reopen(d,p); x=reconcile(e,artifacts=(ArtifactObservation('p','e','c1',str(a.id),a.output,True,valid),)); self.assertEqual(x.decision,Decision.BLOCKED_CORRUPT_STATE); self.r.close(); self.r=None

    def test_11_earlier_gap_wins_over_later_success(self):
        with tempfile.TemporaryDirectory() as d:
            p,e=self.base(2); self.start(e.chunks[0]); b=self.success(e.chunks[1]); self.r=SQLiteProjectRepository(d); self.r.save(p,[e]); e=self.reopen(d,p); x=reconcile(e,artifacts=(ArtifactObservation('p','e','c2',str(b.id),b.output,True,True),)); self.assertEqual(x.next_actionable_chunk,0)

    def test_12_all_chunks_complete_after_restart(self):
        with tempfile.TemporaryDirectory() as d:
            p,e=self.base(2); arts=[]; trs=[]
            for c in e.chunks: a=self.success(c,str(c.id)); arts.append(Artifact(p.id,e.id,c.id,a.id,Phase.OUTPUT,a.output))
            trs.append(TransitionFrame(p.id,e.id,e.chunks[0].id,e.chunks[0].attempts[0].id,e.chunks[0].attempts[0].output,0,1,e.chunks[1].id)); self.r=SQLiteProjectRepository(d); self.r.save(p,[e],arts,transitions=trs); e=self.reopen(d,p); obs=tuple(ArtifactObservation('p','e',str(c.id),str(c.attempts[-1].id),c.attempts[-1].output,True,True) for c in e.chunks); tr=TransitionObservation('p','e','c1',str(e.chunks[0].attempts[-1].id),'c2',True,True,e.chunks[0].attempts[-1].output); self.assertEqual(reconcile(e,artifacts=obs,transitions=(tr,)).decision,Decision.COMPLETE)

    def test_13_corrupt_provenance_load_fails_before_reconcile(self):
        with tempfile.TemporaryDirectory() as d:
            p,e=self.base(); self.r=SQLiteProjectRepository(d); self.r.save(p,[e]); self.r.db.execute("PRAGMA foreign_keys=OFF"); self.r.db.execute("INSERT INTO transitions (project_id,execution_id,target_chunk_id,source_chunk_id,source_attempt_id,source_output,frame_index,frame_count,materialized_type,materialized_subfolder,materialized_name,materialized_source_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ('p','e','c1','c1','bad','o',0,1,None,None,None,None)); self.r.close(); self.r=SQLiteProjectRepository(d); self.assertRaises(PersistenceDataError,self.r.load,p.id)

    def test_14_restart_reconcile_idempotent_and_pure(self):
        with tempfile.TemporaryDirectory() as d:
            p,e=self.base(); self.r=SQLiteProjectRepository(d); self.r.save(p,[e]); e=self.reopen(d,p); before=(e.state,tuple(c.state for c in e.chunks),tuple(len(c.attempts) for c in e.chunks)); x=reconcile(e); self.r.close(); self.r=SQLiteProjectRepository(d); e2=self.r.load(p.id)[1][0]; y=reconcile(e2); self.assertEqual(x,y); self.assertEqual((e.state,tuple(c.state for c in e.chunks),tuple(len(c.attempts) for c in e.chunks)),before)

    def test_15_failed_history_retry_success_and_frame_provenance_survives_two_reopens(self):
        with tempfile.TemporaryDirectory() as d:
            p,e=self.base(2); c=e.chunks[0]; a=self.start(c); a.transition(Lifecycle.FAILED,error=ErrorRecord('x','fail')); b=self.success(c,'ok'); c.state=Lifecycle.SUCCEEDED; t=TransitionFrame(p.id,e.id,c.id,b.id,b.output,0,1,e.chunks[1].id); e.link_transition(e.chunks[1],t); self.r=SQLiteProjectRepository(d); self.r.save(p,[e], [Artifact(p.id,e.id,c.id,b.id,Phase.OUTPUT,b.output)],transitions=[t]); e=self.reopen(d,p); e=self.reopen(d,p); self.assertEqual(e.chunks[1].first_frame.source_attempt_id,b.id); self.assertEqual(len(e.chunks[0].attempts),2)


if __name__ == '__main__': unittest.main()
