import copy
import unittest

from orquestador.profiles.minimax_h3 import (
    IncompatibleWorkflowError,
    bind_inputs,
    load_api_template,
    rebind_first_frame,
)


class RebindFirstFrameTests(unittest.TestCase):
    def setUp(self):
        self.template = load_api_template()

    def test_rebind_accepts_reduced_live_case_and_preserves_contract(self):
        bound = bind_inputs(self.template, first_frame=None, references=["r0", "r1"])
        rebound = rebind_first_frame(bound, "orquestador/transitions/transition-test.png")
        self.assertEqual(rebound["114"]["inputs"]["image"], "orquestador/transitions/transition-test.png")
        self.assertEqual(rebound["129"]["inputs"]["first_frame"], ["119", 0])
        self.assertEqual(sorted(k for k in rebound["129"]["inputs"] if k.startswith("ref_images.ref_image_")),
                         ["ref_images.ref_image_0", "ref_images.ref_image_1"])

    def test_reduced_cardinalities_and_full_graph(self):
        for count in (0, 1, 2, 5):
            with self.subTest(count=count):
                rebound = rebind_first_frame(bind_inputs(self.template, references=[f"r{i}" for i in range(count)]), "frame.png")
                self.assertEqual(rebound["114"]["inputs"]["image"], "frame.png")
        full = bind_inputs(self.template, prompt="p", first_frame="old.png", references=[f"r{i}" for i in range(6)])
        self.assertEqual(rebind_first_frame(full, "frame.png")["114"]["inputs"]["image"], "frame.png")

    def test_off_reference_cardinalities_keep_baseline_slots(self):
        for count in (0, 1, 6):
            with self.subTest(count=count):
                bound = bind_inputs(self.template, first_frame="initial.png", references=[f"u{i}.png" for i in range(count)])
                refs = bound["129"]["inputs"]
                self.assertEqual(sorted(k for k in refs if k.startswith("ref_images.ref_image_")),
                                 [f"ref_images.ref_image_{i}" for i in range(count)])
                if count:
                    self.assertEqual(bound["130"]["inputs"]["image"], "u0.png")

    def test_primary_binding_has_dense_effective_order_and_no_node129_flag(self):
        for count in (0, 1, 3, 6):
            with self.subTest(count=count):
                users = [f"u{i}.png" for i in range(count)]
                bound = bind_inputs(self.template, first_frame="initial.png", references=users,
                                    first_frame_as_primary_reference=True)
                refs = bound["129"]["inputs"]
                self.assertEqual(sorted(k for k in refs if k.startswith("ref_images.ref_image_")),
                                 [f"ref_images.ref_image_{i}" for i in range(count + 1)])
                self.assertEqual(refs["ref_images.ref_image_0"], refs["first_frame"])
                self.assertNotIn("first_frame_as_primary_reference", refs)
                outputs = (["156",0],["157",0],["158",0],["159",0],["161",0],["160",0])
                for i in range(count):
                    self.assertEqual(refs[f"ref_images.ref_image_{i + 1}"], outputs[i])
                    self.assertEqual(bound[str((130,131,132,150,151,152)[i])]["inputs"]["image"], users[i])

    def test_primary_rebind_preserves_all_user_references_at_every_cardinality(self):
        for count in (0, 1, 3, 6):
            with self.subTest(count=count):
                users = [f"u{i}.png" for i in range(count)]
                bound = bind_inputs(self.template, first_frame="__ORQ_FIRST_FRAME__", references=users,
                                    first_frame_as_primary_reference=True)
                rebound = rebind_first_frame(bound, "transition.png", first_frame_as_primary_reference=True)
                refs = rebound["129"]["inputs"]
                self.assertEqual(rebound["114"]["inputs"]["image"], "transition.png")
                self.assertEqual(refs["ref_images.ref_image_0"], refs["first_frame"])
                for i in range(count):
                    self.assertEqual(rebound[str((130,131,132,150,151,152)[i])]["inputs"]["image"], users[i])

    def test_primary_rebind_reduced_zero_refs_materializes_transition(self):
        bound = bind_inputs(self.template, first_frame=None, references=[], first_frame_as_primary_reference=True)
        rebound = rebind_first_frame(bound, "transition.png", first_frame_as_primary_reference=True)
        self.assertEqual(rebound["114"]["inputs"]["image"], "transition.png")
        self.assertEqual(rebound["129"]["inputs"]["ref_images.ref_image_0"], ["119", 0])

    def test_malformed_reduced_graph_fails_closed(self):
        bound = bind_inputs(self.template, references=["r0", "r1"])
        missing = copy.deepcopy(bound)
        missing.pop("130")
        with self.assertRaises(IncompatibleWorkflowError):
            rebind_first_frame(missing, "frame.png")
        foreign = copy.deepcopy(bound)
        foreign["130"]["class_type"] = "Foreign.Node"
        with self.assertRaises(IncompatibleWorkflowError):
            rebind_first_frame(foreign, "frame.png")


if __name__ == "__main__":
    unittest.main()
