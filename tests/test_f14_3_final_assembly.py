import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from orquestador.adapters.assembly import AssemblyError, FFmpegAssemblyAdapter
from orquestador.application.assembly import FinalizeExecutionUseCase
from orquestador.application.final_output import (
    FINAL_OUTPUT_FOLDER_KEY,
    FINAL_OUTPUT_FILENAME_KEY,
)
from orquestador.application.chain_execution import ChainExecutionUseCase, ChainOutcome
from orquestador.application.queue_recovery import ActiveQueueRecoveryUseCase
from orquestador.application.queue_operations import QueueOperationsUseCase
from orquestador.application.scheduler import (
    SchedulerExecutionBoundary, SchedulerInstanceLock, SchedulerTickOutcome,
    SingleExecutionScheduler,
)
from orquestador.domain import (
    Artifact, AssemblyAttempt, AssemblySourceEvidence, AssemblyState, Chunk,
    ErrorRecord, Evidence, Execution, ExecutionId, Lifecycle, OutputRef,
    Phase, Project, ProjectId, TransitionFrame,
)
from orquestador.persistence.sqlite import PersistenceConflictError, SQLiteProjectRepository


class FakeAssemblyAdapter:
    def __init__(self):
        self.calls=[]
        self.fail_stage=False
        self.fail_final_probe=False
        self.signature=("h264","avc1","High",40,32,32,"yuv420p",None,"5/1","1/10240",())
        self.payload=b"synthetic validated mp4"

    @staticmethod
    def _hash(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def stage(self,sources,destination,*,reencode=False):
        self.calls.append(("stage",tuple(map(Path,sources))))
        if self.fail_stage:
            self.fail_stage=False
            raise AssemblyError("simulated ffmpeg failure")
        destination=Path(destination)
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(self.payload)
        return SimpleNamespace(path=destination,sha256=self._hash(destination),probe_signature=self.signature)

    def inspect(self,path):
        path=Path(path)
        self.calls.append(("inspect",path))
        if self.fail_final_probe and path.name.startswith("assembled-"):
            raise AssemblyError("simulated final ffprobe failure")
        if not path.is_file() or path.stat().st_size==0:
            raise AssemblyError("missing or empty test video")
        return self._hash(path),self.signature

    def publish(self,staged,destination,*,expected_sha256):
        staged,destination=Path(staged),Path(destination)
        self.calls.append(("publish",destination))
        if destination.exists():
            raise AssemblyError("destination already exists")
        if self._hash(staged)!=expected_sha256:
            raise AssemblyError("staging digest mismatch")
        destination.parent.mkdir(parents=True,exist_ok=True)
        os.link(staged,destination)
        return destination

    def publish_external(self,source,destination,*,expected_sha256):
        source,destination=Path(source),Path(destination)
        self.calls.append(("publish_external",destination))
        if self._hash(source)!=expected_sha256:
            raise AssemblyError("external source mismatch")
        if destination.exists():
            if self._hash(destination)==expected_sha256:
                return destination
            raise AssemblyError("final video destination already exists with different content")
        if not destination.parent.is_dir():
            raise AssemblyError("final video folder is missing or inaccessible")
        destination.write_bytes(source.read_bytes())
        return destination


class CrashDuringStage(FakeAssemblyAdapter):
    def stage(self,*args,**kwargs):
        self.calls.append(("stage-crash",()))
        raise KeyboardInterrupt("simulated process interruption during ffmpeg")


class FailFinalSuccessSave:
    """Repository decorator that simulates a crash after publish, before DB success."""
    def __init__(self,repository):
        self.repository=repository
        self.root=repository.root
        self.failed=False

    def __getattr__(self,name):
        return getattr(self.repository,name)

    def save(self,project,executions,*args,**kwargs):
        if not self.failed and any(execution.state is Lifecycle.SUCCEEDED for execution in executions):
            self.failed=True
            raise RuntimeError("simulated crash before finalization evidence commit")
        return self.repository.save(project,executions,*args,**kwargs)


class F143FinalAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root=Path(self.temp.name)
        self.repo=SQLiteProjectRepository(self.root)
        self.project=Project(ProjectId("project"),name="Project")
        self.execution=Execution(self.project.id,ExecutionId("execution"))
        for order in range(2):
            self.execution.add_chunk(Chunk(order=order))
        self.repo.save(self.project,[self.execution])
        self.queue=None
        self.queue_item=None

    def tearDown(self):
        try:self.repo.close()
        except Exception:pass
        self.temp.cleanup()

    def complete_chunks(self,*,queued=False):
        if queued:
            self.queue=QueueOperationsUseCase(self.repo)
            self.queue_item=self.queue.enqueue(str(self.project.id),str(self.execution.id),queue_item_id="active-item")
            claim=self.repo.claim_next_queue_item()
            self.assertEqual(str(claim.item.id),str(self.queue_item.id))
        project,executions=self.repo.load(self.project.id)
        execution=next(item for item in executions if item.id==self.execution.id)
        execution.transition(Lifecycle.RUNNING)
        if queued:
            self.repo.start_execution_from_active_queue_claim(project,execution,self.queue_item.id)
        else:
            self.repo.save(project,[execution])
        artifacts=[]
        for index,chunk in enumerate(execution.chunks):
            chunk.transition(Lifecycle.RUNNING)
            attempt=chunk.new_attempt()
            attempt.transition(Lifecycle.RUNNING)
            output=OutputRef(f"outputs/chunk-{index}.mp4")
            path=self.root/output.uri
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(f"chunk-{index}-bytes".encode())
            attempt.transition(Lifecycle.SUCCEEDED,output=output,evidence=Evidence("verified chunk output"))
            chunk.transition(Lifecycle.SUCCEEDED)
            artifacts.append(Artifact(project.id,execution.id,chunk.id,attempt.id,Phase.OUTPUT,output))
            execution.artifacts.append(artifacts[-1])
        transition=TransitionFrame(project.id,execution.id,execution.chunks[0].id,
            execution.chunks[0].attempts[-1].id,execution.chunks[0].attempts[-1].output,
            0,1,execution.chunks[1].id)
        execution.link_transition(execution.chunks[1],transition)
        self.repo.save(project,[execution],artifacts=artifacts,transitions=(transition,))
        self.project,self.execution=project,execution
        return project,execution

    def finalizer(self,adapter=None,repository=None):
        return FinalizeExecutionUseCase(repository or self.repo,adapter or FakeAssemblyAdapter(),self.root)

    def test_chunks_do_not_finish_queue_item_until_validated_final_exists(self):
        project,execution=self.complete_chunks(queued=True)
        self.assertIs(execution.state,Lifecycle.RUNNING)
        self.assertIs(execution.assembly_state,AssemblyState.PENDING)
        with self.assertRaises(PersistenceConflictError):
            self.repo.finish_claimed_queue_item(self.queue_item.id,execution.id)
        self.assertEqual(self.repo.get_queue_item(self.queue_item.id).state.value,"active")

        adapter=FakeAssemblyAdapter()
        chain=ChainExecutionUseCase(self.repo,coordinator=None,finalizer=self.finalizer(adapter))
        result=chain.run(project,execution,[],queue_item_id=str(self.queue_item.id),queue_recovery=True)

        self.assertIs(result.outcome,ChainOutcome.COMPLETE)
        _,loaded=self.repo.load(project.id)
        final=next(item for item in loaded if item.id==execution.id)
        self.assertIs(final.state,Lifecycle.SUCCEEDED)
        self.assertTrue(self.finalizer(adapter).is_durably_complete(final))
        destination=self.root/f"assembled-{execution.id}.mp4"
        self.assertTrue(destination.is_file())
        published=self.root/"Project.mp4"
        self.assertTrue(published.is_file())
        self.assertEqual(published.read_bytes(),destination.read_bytes())
        self.assertEqual(Path(result.detail.output) if getattr(result,"detail",None) is not None and getattr(result.detail,"output",None) else published,published)
        self.repo.finish_claimed_queue_item(self.queue_item.id,execution.id)
        self.assertEqual(self.repo.get_queue_item(self.queue_item.id).state.value,"finished")

    def test_custom_folder_and_name_publish_human_final_without_removing_internal(self):
        output_dir=self.root/"published"
        output_dir.mkdir()
        project,execution=self.complete_chunks(queued=True)
        execution.defaults={
            **dict(execution.defaults),
            FINAL_OUTPUT_FOLDER_KEY:str(output_dir.resolve()),
            FINAL_OUTPUT_FILENAME_KEY:"Gisell final.mp4",
        }
        self.repo.save(project,[execution])
        adapter=FakeAssemblyAdapter()
        result=self.finalizer(adapter).execute(
            project.id,execution.id,queue_item_id=str(self.queue_item.id))
        self.assertTrue(result.success,result.reason)
        internal=self.root/f"assembled-{execution.id}.mp4"
        published=output_dir/"Gisell final.mp4"
        self.assertTrue(internal.is_file())
        self.assertTrue(published.is_file())
        self.assertEqual(internal.read_bytes(),published.read_bytes())
        self.assertEqual(result.output,published)
        self.assertTrue(self.finalizer(adapter).is_durably_complete(self.repo.load(project.id)[1][0]))

    def test_external_collision_never_overwrites_and_retry_reuses_internal_assembly(self):
        output_dir=self.root/"published"
        output_dir.mkdir()
        project,execution=self.complete_chunks(queued=True)
        execution.defaults={
            **dict(execution.defaults),
            FINAL_OUTPUT_FOLDER_KEY:str(output_dir.resolve()),
            FINAL_OUTPUT_FILENAME_KEY:"Project final.mp4",
        }
        self.repo.save(project,[execution])
        collision=output_dir/"Project final.mp4"
        collision.write_bytes(b"keep me")
        adapter=FakeAssemblyAdapter()
        finalizer=self.finalizer(adapter)
        failed=finalizer.execute(
            project.id,execution.id,queue_item_id=str(self.queue_item.id))
        self.assertFalse(failed.success)
        self.assertIn("different content",failed.reason)
        self.assertEqual(collision.read_bytes(),b"keep me")
        internal=self.root/f"assembled-{execution.id}.mp4"
        self.assertTrue(internal.is_file())
        self.assertEqual([call[0] for call in adapter.calls].count("stage"),1)

        collision.unlink()
        _,loaded=self.repo.load(project.id)
        current=loaded[0]
        self.assertTrue(finalizer.can_retry(current))
        retried=finalizer.retry(
            project.id,execution.id,queue_item_id=str(self.queue_item.id))
        self.assertTrue(retried.success,retried.reason)
        self.assertEqual([call[0] for call in adapter.calls].count("stage"),1)
        self.assertEqual((output_dir/"Project final.mp4").read_bytes(),internal.read_bytes())
        _,loaded=self.repo.load(project.id)
        self.assertEqual(len(loaded[0].assembly_attempts),2)

    def test_assembly_failure_keeps_chunks_and_retry_does_not_recreate_attempts(self):
        project,execution=self.complete_chunks(queued=True)
        attempts_before=tuple(tuple((str(a.id),a.number,a.state) for a in c.attempts) for c in execution.chunks)
        transitions_before=self.repo.load_transitions(execution.id)
        adapter=FakeAssemblyAdapter(); adapter.fail_stage=True
        finalizer=self.finalizer(adapter)
        failed=finalizer.execute(project.id,execution.id,queue_item_id=str(self.queue_item.id))
        self.assertFalse(failed.success)
        self.assertIn("simulated ffmpeg failure",failed.reason)
        _,loaded=self.repo.load(project.id); current=loaded[0]
        self.assertIs(current.state,Lifecycle.RUNNING)
        self.assertIs(current.assembly_state,AssemblyState.FAILED)
        self.assertEqual(self.repo.get_queue_item(self.queue_item.id).state.value,"active")

        submit_calls=[]
        retried=finalizer.retry(project.id,execution.id,queue_item_id=str(self.queue_item.id))
        self.assertTrue(retried.success,retried.reason)
        _,loaded=self.repo.load(project.id); current=loaded[0]
        self.assertIs(current.state,Lifecycle.SUCCEEDED)
        self.assertEqual(tuple(tuple((str(a.id),a.number,a.state) for a in c.attempts) for c in current.chunks),attempts_before)
        self.assertEqual(self.repo.load_transitions(execution.id),transitions_before)
        self.assertEqual([call[0] for call in adapter.calls].count("stage"),2)
        self.assertEqual(submit_calls,[])
        self.repo.finish_claimed_queue_item(self.queue_item.id,execution.id)

    def test_ffprobe_failure_records_cause_and_never_overwrites_published_file(self):
        project,execution=self.complete_chunks(queued=True)
        adapter=FakeAssemblyAdapter(); adapter.fail_final_probe=True
        result=self.finalizer(adapter).execute(project.id,execution.id,queue_item_id=str(self.queue_item.id))
        self.assertFalse(result.success)
        self.assertIn("simulated final ffprobe failure",result.reason)
        _,loaded=self.repo.load(project.id); current=loaded[0]
        self.assertIs(current.state,Lifecycle.RUNNING)
        self.assertIs(current.assembly_state,AssemblyState.FAILED)
        final_path=self.root/f"assembled-{execution.id}.mp4"
        before=final_path.read_bytes()
        self.assertFalse(self.finalizer(adapter).can_retry(current))
        retried=self.finalizer(adapter).retry(project.id,execution.id,queue_item_id=str(self.queue_item.id))
        self.assertFalse(retried.success)
        self.assertEqual(final_path.read_bytes(),before)
        self.assertEqual(self.repo.get_queue_item(self.queue_item.id).state.value,"active")

    def test_existing_destination_and_ambiguous_source_fail_closed(self):
        project,execution=self.complete_chunks(queued=True)
        destination=self.root/f"assembled-{execution.id}.mp4"
        destination.write_bytes(b"preexisting file")
        adapter=FakeAssemblyAdapter()
        result=self.finalizer(adapter).execute(project.id,execution.id,queue_item_id=str(self.queue_item.id))
        self.assertFalse(result.success)
        self.assertIn("already exists",result.reason)
        self.assertEqual(destination.read_bytes(),b"preexisting file")
        self.assertEqual(adapter.calls,[])

        destination.unlink()
        duplicate=Artifact(project.id,execution.id,execution.chunks[0].id,
            execution.chunks[0].attempts[0].id,Phase.OUTPUT,execution.chunks[0].attempts[0].output)
        self.repo.save(project,[execution],artifacts=(duplicate,))
        ambiguous=self.finalizer(adapter).execute(project.id,execution.id,queue_item_id=str(self.queue_item.id))
        self.assertFalse(ambiguous.success)
        self.assertIn("ambiguous",ambiguous.reason)
        _,loaded=self.repo.load(project.id)
        self.assertIs(loaded[0].assembly_state,AssemblyState.FAILED)
        self.assertFalse(self.finalizer(adapter).can_retry(loaded[0]))
        self.assertEqual(self.repo.get_queue_item(self.queue_item.id).state.value,"active")
        self.assertEqual(adapter.calls,[])

    def test_missing_or_contradictory_transition_blocks_final_assembly(self):
        project,execution=self.complete_chunks(queued=True)
        self.repo.db.execute("DELETE FROM transitions WHERE source_chunk_id=?",
            (str(execution.chunks[0].id),))
        adapter=FakeAssemblyAdapter()
        result=self.finalizer(adapter).execute(
            project.id,execution.id,queue_item_id=str(self.queue_item.id))
        self.assertFalse(result.success)
        self.assertIn("continuity transition",result.reason)
        _,loaded=self.repo.load(project.id)
        self.assertIs(loaded[0].state,Lifecycle.RUNNING)
        self.assertIs(loaded[0].assembly_state,AssemblyState.FAILED)
        self.assertEqual(self.repo.get_queue_item(self.queue_item.id).state.value,"active")
        self.assertEqual(adapter.calls,[])

    def test_restart_during_ffmpeg_resumes_assembly_without_chunk_submit(self):
        project,execution=self.complete_chunks(queued=True)
        crashed=self.finalizer(CrashDuringStage())
        with self.assertRaises(KeyboardInterrupt):
            crashed.execute(project.id,execution.id,queue_item_id=str(self.queue_item.id))
        self.repo.close()
        self.repo=SQLiteProjectRepository(self.root)
        project,loaded=self.repo.load(project.id); execution=loaded[0]
        self.assertIs(execution.assembly_state,AssemblyState.ASSEMBLING)
        adapter=FakeAssemblyAdapter()
        result=self.finalizer(adapter).execute(project.id,execution.id,queue_item_id=str(self.queue_item.id))
        self.assertTrue(result.success,result.reason)
        self.assertEqual([call[0] for call in adapter.calls].count("stage"),1)
        self.assertTrue(self.finalizer(adapter).is_durably_complete(self.repo.load(project.id)[1][0]))

    def test_restart_after_last_chunk_runs_only_final_assembly_before_queue_release(self):
        project,execution=self.complete_chunks(queued=True)
        attempts_before=tuple(tuple(str(attempt.id) for attempt in chunk.attempts) for chunk in execution.chunks)
        adapter=FakeAssemblyAdapter()
        finalizer=self.finalizer(adapter)

        def resume_claimed(project_id,execution_id,queue_item_id):
            loaded_project,executions=self.repo.load(project_id)
            exact=next(item for item in executions if str(item.id)==execution_id)
            return ChainExecutionUseCase(self.repo,None,finalizer=finalizer).run(
                loaded_project,exact,[],queue_item_id=queue_item_id,queue_recovery=True)

        recovery=ActiveQueueRecoveryUseCase(
            self.repo,lambda *_:None,resume_claimed,
            completion_validator=finalizer.is_durably_complete)
        scheduler=SingleExecutionScheduler(self.repo,
            SchedulerExecutionBoundary(lambda *_:None,reconcile_active=recovery.reconcile),
            SchedulerInstanceLock(self.root))
        scheduler.start()
        try:
            result=scheduler.tick()
        finally:
            scheduler.stop()
        self.assertIs(result.outcome,SchedulerTickOutcome.FINISHED)
        self.assertEqual(self.repo.get_queue_item(self.queue_item.id).state.value,"finished")
        _,loaded=self.repo.load(project.id)
        self.assertEqual(tuple(tuple(str(attempt.id) for attempt in chunk.attempts) for chunk in loaded[0].chunks),attempts_before)
        self.assertEqual([call[0] for call in adapter.calls].count("stage"),1)

    def test_contradictory_published_file_never_reconciles_as_success(self):
        project,execution=self.complete_chunks(queued=True)
        adapter=FakeAssemblyAdapter()
        finalizer=self.finalizer(adapter)
        self.assertTrue(finalizer.execute(project.id,execution.id,queue_item_id=str(self.queue_item.id)).success)
        destination=self.root/f"assembled-{execution.id}.mp4"
        destination.write_bytes(b"changed after durable publication")
        self.repo.close(); self.repo=SQLiteProjectRepository(self.root)
        finalizer=self.finalizer(adapter)
        recovery=ActiveQueueRecoveryUseCase(
            self.repo,lambda *_:None,lambda *_:None,
            completion_validator=finalizer.is_durably_complete)
        scheduler=SingleExecutionScheduler(self.repo,
            SchedulerExecutionBoundary(lambda *_:None,reconcile_active=recovery.reconcile),
            SchedulerInstanceLock(self.root))
        scheduler.start()
        try:
            result=scheduler.tick()
        finally:
            scheduler.stop()
        self.assertIs(result.outcome,SchedulerTickOutcome.RECOVERY_REQUIRED)
        self.assertEqual(self.repo.get_queue_item(self.queue_item.id).state.value,"active")

    def test_restart_after_publish_before_success_evidence_adopts_only_matching_hash(self):
        project,execution=self.complete_chunks(queued=True)
        underlying=self.repo
        failing_repo=FailFinalSuccessSave(underlying)
        adapter=FakeAssemblyAdapter()
        result=FinalizeExecutionUseCase(failing_repo,adapter,self.root).execute(
            project.id,execution.id,queue_item_id=str(self.queue_item.id))
        self.assertFalse(result.success)
        final_path=self.root/f"assembled-{execution.id}.mp4"
        self.assertTrue(final_path.is_file())
        _,loaded=underlying.load(project.id); interrupted=loaded[0]
        self.assertIs(interrupted.state,Lifecycle.RUNNING)
        self.assertIs(interrupted.assembly_state,AssemblyState.ASSEMBLING)
        self.repo.close(); self.repo=SQLiteProjectRepository(self.root)
        project,loaded=self.repo.load(project.id); interrupted=loaded[0]
        recovered=self.finalizer(adapter).execute(project.id,execution.id,queue_item_id=str(self.queue_item.id))
        self.assertTrue(recovered.success,recovered.reason)
        _,loaded=self.repo.load(project.id); final=loaded[0]
        self.assertIs(final.state,Lifecycle.SUCCEEDED)
        self.assertTrue(self.finalizer(adapter).is_durably_complete(final))

    def test_restart_after_durable_final_before_queue_release_releases_only_after_reconcile(self):
        project,execution=self.complete_chunks(queued=True)
        adapter=FakeAssemblyAdapter()
        self.assertTrue(self.finalizer(adapter).execute(project.id,execution.id,queue_item_id=str(self.queue_item.id)).success)
        self.repo.close(); self.repo=SQLiteProjectRepository(self.root)
        project,loaded=self.repo.load(project.id); final=loaded[0]
        validator=self.finalizer(adapter)
        recovery=ActiveQueueRecoveryUseCase(self.repo,lambda *_:None,lambda *_:None,
            completion_validator=validator.is_durably_complete)
        scheduler=SingleExecutionScheduler(self.repo,
            SchedulerExecutionBoundary(lambda *_:None,reconcile_active=recovery.reconcile),
            SchedulerInstanceLock(self.root))
        scheduler.start()
        try:
            result=scheduler.tick()
        finally:
            scheduler.stop()
        self.assertIs(result.outcome,SchedulerTickOutcome.FINISHED)
        self.assertEqual(self.repo.get_queue_item(self.queue_item.id).state.value,"finished")

    def test_schema9_migration_preserves_legacy_success_and_queue_rows(self):
        project,execution=self.complete_chunks(queued=True)
        # This is an already-terminal pre-F14.3 row: retain readability, but do
        # not invent an assembly record from chunk outputs alone.
        self.repo.db.execute("UPDATE executions SET state='succeeded' WHERE id=?",(str(execution.id),))
        self.repo.db.execute("DROP TABLE execution_assembly_attempts")
        self.repo.db.execute("UPDATE schema_version SET version=9")
        self.repo.close()
        self.repo=SQLiteProjectRepository(self.root)
        self.assertEqual(self.repo.db.execute("SELECT version FROM schema_version").fetchone()[0],10)
        _,loaded=self.repo.load(project.id)
        self.assertIs(loaded[0].state,Lifecycle.SUCCEEDED)
        self.assertEqual(self.repo.get_queue_item(self.queue_item.id).state.value,"active")
        self.assertEqual(loaded[0].assembly_attempts,[])
        self.assertTrue(self.repo.db.execute("PRAGMA foreign_key_check").fetchall()==[])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),"FFmpeg/FFprobe binaries are unavailable")
    def test_real_ffmpeg_ffprobe_finalization_with_synthetic_clips(self):
        self.complete_chunks(queued=False)
        for index,chunk in enumerate(self.execution.chunks):
            path=self.root/chunk.attempts[0].output.uri
            subprocess.run([shutil.which("ffmpeg"),"-hide_banner","-loglevel","error","-f","lavfi","-i",
                f"color=c={'red' if index==0 else 'blue'}:s=32x32:r=5","-t","0.4","-an","-c:v","libx264",
                "-pix_fmt","yuv420p","-y",str(path)],check=True,capture_output=True,text=True)
        adapter=FFmpegAssemblyAdapter(shutil.which("ffprobe"),shutil.which("ffmpeg"))
        result=self.finalizer(adapter).execute(self.project.id,self.execution.id)
        self.assertTrue(result.success,result.reason)
        _,loaded=self.repo.load(self.project.id)
        final=loaded[0]
        self.assertIs(final.state,Lifecycle.SUCCEEDED)
        self.assertTrue(self.finalizer(adapter).is_durably_complete(final))
        self.assertGreater((self.root/f"assembled-{self.execution.id}.mp4").stat().st_size,0)


if __name__=="__main__":
    unittest.main()
