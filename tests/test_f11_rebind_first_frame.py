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
