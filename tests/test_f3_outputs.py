import unittest
from dataclasses import FrozenInstanceError

from orquestador.adapters import (BackendJobRef, HistoryResult, HistoryState,
    OutputCorrelationStatus, correlate_outputs)


def history(ref, outputs, state=HistoryState.SUCCEEDED):
    return HistoryResult(ref, state, {"status": {"status_str": "success", "completed": True}, "outputs": outputs})


class OutputCorrelationTests(unittest.TestCase):
    def test_semantic_backend_ref_equality_preserves_caller_identity(self):
        caller = BackendJobRef("same-id")
        reconstructed = BackendJobRef("same-id")
        r = correlate_outputs(history(reconstructed, {"n": [{"filename": "a", "subfolder": "", "type": "opaque"}]}), caller)
        self.assertEqual(r.status, OutputCorrelationStatus.VALID)
        self.assertIs(r.prompt_id, caller)
        self.assertIs(r.descriptors[0].prompt_id, caller)

    def test_different_backend_ids_are_unknown(self):
        history_ref = BackendJobRef("history-id")
        caller = BackendJobRef("other-id")
        r = correlate_outputs(history(history_ref, {"n": [{"filename": "a", "subfolder": "", "type": "x"}]}), caller)
        self.assertEqual(r.status, OutputCorrelationStatus.UNKNOWN)

    def test_terminal_and_nonterminal_gating(self):
        ref = BackendJobRef("j")
        for state in (HistoryState.QUEUED, HistoryState.RUNNING, HistoryState.FAILED, HistoryState.UNKNOWN):
            self.assertNotEqual(correlate_outputs(history(ref, {"n": [{"filename":"a", "subfolder":"", "type":"x"}]}, state), ref).status, OutputCorrelationStatus.VALID)

    def test_raw_non_mapping_is_unknown(self):
        ref = BackendJobRef("j")
        self.assertEqual(correlate_outputs(HistoryResult(ref, HistoryState.SUCCEEDED, None), ref).status, OutputCorrelationStatus.UNKNOWN)

    def test_nested_metadata_without_descriptor_is_not_descriptor(self):
        ref = BackendJobRef("j")
        r = correlate_outputs(history(ref, {"n": [{"metadata": {"note": "x"}}]}), ref)
        self.assertEqual(r.status, OutputCorrelationStatus.MALFORMED)

    def test_subset_descriptor_fields_is_malformed(self):
        ref = BackendJobRef("j")
        r = correlate_outputs(history(ref, {"n": [{"filename": "a"}]}), ref)
        self.assertEqual(r.status, OutputCorrelationStatus.MALFORMED)

    def test_frozen_result_and_tuple_descriptors(self):
        ref = BackendJobRef("j")
        r = correlate_outputs(history(ref, {"n": [{"filename":"a", "subfolder":"", "type":"x"}]}), ref)
        self.assertIsInstance(r.descriptors, tuple)
        with self.assertRaises(FrozenInstanceError):
            r.status = OutputCorrelationStatus.UNKNOWN
        with self.assertRaises(FrozenInstanceError):
            r.descriptors = ()
        with self.assertRaises(FrozenInstanceError):
            r.descriptors[0].filename = "changed"

    def test_drive_relative_paths_are_rejected(self):
        ref = BackendJobRef("j")
        for field in ("filename", "subfolder"):
            item = {"filename": "safe.txt", "subfolder": "", "type": "x"}
            item[field] = "C:foo"
            self.assertEqual(
                correlate_outputs(history(ref, {"n": [item]}), ref).status,
                OutputCorrelationStatus.MALFORMED,
            )

    def test_backslash_relative_subfolder_is_preserved(self):
        ref = BackendJobRef("j")
        r = correlate_outputs(
            history(ref, {"n": [{"filename": "a", "subfolder": "folder\\nested", "type": "x"}]}),
            ref,
        )
        self.assertEqual(r.status, OutputCorrelationStatus.VALID)
        self.assertEqual(r.descriptors[0].subfolder, "folder\\nested")
    def test_valid_and_identity(self):
        ref = BackendJobRef("job")
        r = correlate_outputs(history(ref, {"node": {"files": [{"filename": "a.mp4", "subfolder": "x/y", "type": "opaque"}]}}), ref)
        self.assertEqual(r.status, OutputCorrelationStatus.VALID); self.assertEqual(len(r.descriptors), 1)
        self.assertIs(r.prompt_id, ref); self.assertIs(r.descriptors[0].prompt_id, ref)

    def test_multiple_and_stable_order(self):
        ref = BackendJobRef("j")
        out = {"z": [{"filename":"z","subfolder":"","type":"x"}], "a": [{"filename":"a","subfolder":"","type":"unknown"}]}
        r = correlate_outputs(history(ref, out), ref)
        self.assertEqual([d.node_id for d in r.descriptors], ["a", "z"])

    def test_states_and_shapes(self):
        ref = BackendJobRef("j")
        for h in (HistoryResult(ref, HistoryState.RUNNING), HistoryResult(ref, HistoryState.SUCCEEDED, None)):
            self.assertNotEqual(correlate_outputs(h, ref).status, OutputCorrelationStatus.VALID)
        for outputs, status in ((None, OutputCorrelationStatus.NO_OUTPUTS), ([], OutputCorrelationStatus.MALFORMED), ("x", OutputCorrelationStatus.MALFORMED), ({}, OutputCorrelationStatus.NO_OUTPUTS)):
            self.assertEqual(correlate_outputs(history(ref, outputs), ref).status, status)

    def test_succeeded_history_without_outputs_key_is_no_outputs(self):
        ref = BackendJobRef("j")
        raw = {"status": {"status_str": "success", "completed": True}}
        result = correlate_outputs(HistoryResult(ref, HistoryState.SUCCEEDED, raw), ref)
        self.assertEqual(result.status, OutputCorrelationStatus.NO_OUTPUTS)

    def test_validation_fail_closed_and_duplicates(self):
        ref = BackendJobRef("j")
        base = {"filename":"a", "subfolder":"", "type":"x"}
        for field, values in {"node": ["", 1], "filename":["", 1, "/a", "C:\\a", "\\\\server\\a", "a/b", ".", "..", "a\x00b"], "subfolder":[1, "/a", "C:\\a", "\\\\server\\a", ".", "..", "a/../b", "a\\..\\b", "a\x00b"], "type":["", 1]}.items():
            for value in values:
                item = dict(base); item[field] = value
                node = value if field == "node" else "n"
                self.assertEqual(correlate_outputs(history(ref, {node: [item]}), ref).status, OutputCorrelationStatus.MALFORMED)
        dup = {"a":[base], "b":[base]}
        self.assertEqual(correlate_outputs(history(ref, dup), ref).status, OutputCorrelationStatus.AMBIGUOUS)
        mixed = {"a":[base, {"filename":"bad", "type":"x"}]}
        self.assertEqual(correlate_outputs(history(ref, mixed), ref).status, OutputCorrelationStatus.MALFORMED)


if __name__ == '__main__': unittest.main()
