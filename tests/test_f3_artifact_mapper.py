import tempfile
import unittest
from pathlib import Path

from orquestador.adapters import (BackendJobRef, OutputDescriptor, PhysicalOutputEvidence,
                                   PhysicalOutputStatus, validate_physical_output)
from orquestador.application.bridge import BackendEvidence, map_verified_artifact_observation
from orquestador.domain.recovery import BackendJobState


class ArtifactMapperTests(unittest.TestCase):
    def setUp(self):
        self.ref = BackendJobRef("prompt-1")
        self.desc = OutputDescriptor(self.ref, "92", "clip.mp4", "nested\\sub", "video")
        self.base = Path(tempfile.mkdtemp(prefix="orq-f3-"))
        (self.base / "nested" / "sub").mkdir(parents=True)
        (self.base / "nested" / "sub" / "clip.mp4").write_bytes(b"x")
        self.physical = validate_physical_output(self.desc, self.base)
        self.evidence = BackendEvidence("p", "e", "c", "a", self.ref, BackendJobState.COMPLETED, (self.desc,))

    def tearDown(self):
        import shutil; shutil.rmtree(self.base, ignore_errors=True)

    def map(self, evidence=None, physical=None, **kw):
        return map_verified_artifact_observation(evidence=evidence or self.evidence,
            physical=physical or self.physical, project_id=kw.get("project_id", "p"),
            execution_id=kw.get("execution_id", "e"), chunk_id=kw.get("chunk_id", "c"),
            attempt_id=kw.get("attempt_id", "a"), job_ref=kw.get("job_ref", self.ref))

    def test_verified_mapping_is_coarse_and_deterministic(self):
        before = (self.evidence, self.physical)
        one = self.map(); two = self.map()
        self.assertEqual(one, two); self.assertEqual(one.output.uri, str(self.physical.resolved_path))
        self.assertTrue(one.exists and one.integrity_valid); self.assertEqual((self.evidence, self.physical), before)

    def test_provenance_and_descriptor_mismatch_fail_closed(self):
        self.assertIsNone(self.map(job_ref=BackendJobRef("other")))
        bad = BackendEvidence("p", "e", "c", "a", self.ref, BackendJobState.COMPLETED,
                              (OutputDescriptor(self.ref, "91", "other.mp4", "nested/sub", "video"),))
        self.assertIsNone(self.map(evidence=bad))
        self.assertIsNone(self.map(project_id="other"))

    def test_identity_and_physical_coherence_fail_closed(self):
        for field in ("execution_id", "chunk_id", "attempt_id"):
            self.assertIsNone(self.map(**{field: "mismatch"}))
        self.assertIsNone(self.map(physical=PhysicalOutputEvidence(self.desc, PhysicalOutputStatus.EXISTS, self.base, None)))
        distinct = OutputDescriptor(self.ref, "93", "clip.mp4", "nested\\sub", "video")
        self.assertIsNone(self.map(physical=PhysicalOutputEvidence(distinct, PhysicalOutputStatus.EXISTS, self.base, self.physical.resolved_path)))

    def test_every_non_exists_physical_status_fails_closed(self):
        for status in PhysicalOutputStatus:
            if status is PhysicalOutputStatus.EXISTS: continue
            ev = PhysicalOutputEvidence(self.desc, status, self.base, self.physical.resolved_path)
            self.assertIsNone(self.map(physical=ev))

    def test_no_logical_or_terminal_observation(self):
        self.assertIsNone(self.map(evidence=BackendEvidence("p", "e", "c", "a", self.ref, BackendJobState.COMPLETED, ())))
        for state in (BackendJobState.QUEUED, BackendJobState.RUNNING, BackendJobState.UNKNOWN,
                      BackendJobState.FAILED, BackendJobState.CANCELLED):
            self.assertIsNone(self.map(evidence=BackendEvidence("p", "e", "c", "a", self.ref, state, (self.desc,))))

    def test_multiple_logical_outputs_fail_closed(self):
        second_desc = OutputDescriptor(self.ref, "93", "second.mp4", "nested\\sub", "video")
        evidence = BackendEvidence("p", "e", "c", "a", self.ref, BackendJobState.COMPLETED,
                                    (self.desc, second_desc))
        coherent_physical = PhysicalOutputEvidence(self.desc, PhysicalOutputStatus.EXISTS,
                                                    self.base, self.physical.resolved_path)
        self.assertIsNone(map_verified_artifact_observation(
            evidence=evidence,
            physical=coherent_physical,
            project_id="p",
            execution_id="e",
            chunk_id="c",
            attempt_id="a",
            job_ref=self.ref,
        ))

    def test_containment_rejection_is_delegated_to_physical_validator(self):
        outside = self.base.parent / "orq-f3-task-owned-outside.mp4"
        outside.write_bytes(b"x")
        try:
            escaping = OutputDescriptor(self.ref, "92", outside.name, "..", "video")
            rejected = validate_physical_output(escaping, self.base)
            self.assertEqual(rejected.status, PhysicalOutputStatus.OUTSIDE_ROOT)
            coherent = BackendEvidence("p", "e", "c", "a", self.ref,
                                        BackendJobState.COMPLETED, (escaping,))
            self.assertIsNone(self.map(evidence=coherent, physical=rejected))
        finally:
            outside.unlink(missing_ok=True)


if __name__ == "__main__": unittest.main()
