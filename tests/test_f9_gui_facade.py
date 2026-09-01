import unittest
from dataclasses import FrozenInstanceError
from orquestador.application.gui_facade import GuiFacade, ExecutionSnapshot

class F9FacadeTests(unittest.TestCase):
    def test_immutable_mapping_and_fail_closed(self):
        f=GuiFacade(snapshot=lambda *_:{"state":"READY","errors":["e"],"supported_parameters":["width"]})
        s=f.refresh("p","e"); self.assertEqual(s.state,"READY"); self.assertEqual(s.supported_parameters,("width",))
        with self.assertRaises(FrozenInstanceError): s.state="x"
        self.assertFalse(GuiFacade().preflight().success)
    def test_delegation_once_and_cancel_gate(self):
        calls=[]
        def op(*a,**k): calls.append((a,k)); return {"state":"DONE"}
        f=GuiFacade(preflight=op,chain=op,resume=op,recover=op,assemble=op,cancel=op,snapshot=lambda *_:{"state":"READY","can_cancel":False})
        for method,args in ((f.preflight,(1,)),(f.start_chain,(2,)),(f.resume_execution,(3,)),(f.recover_execution,(4,)),(f.assemble,("x",))): self.assertTrue(method(*args).success)
        self.assertFalse(f.cancel_pending().success); self.assertEqual(len(calls),5)
        f2=GuiFacade(cancel=op,snapshot=lambda *_:{"state":"QUEUED","can_cancel":True}); self.assertTrue(f2.cancel_pending().success); self.assertEqual(len(calls),6)

if __name__=='__main__': unittest.main()
