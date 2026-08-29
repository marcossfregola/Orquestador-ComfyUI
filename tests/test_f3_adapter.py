import json, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from orquestador.adapters import (ComfyUIClient, ComfyUIProtocolError, ComfyUIRejectedError, ComfyUIServerError, ComfyUITimeoutError, ComfyUITransportError, QueueState, HistoryState, BackendJobRef)
class H(BaseHTTPRequestHandler):
 response=({},200)
 def do_GET(self): self.go()
 def do_POST(self): self.go()
 def go(self):
  b,s=self.response; raw=json.dumps(b).encode(); self.send_response(s); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
 def log_message(self,*a): pass
class AdapterTests(unittest.TestCase):
 @classmethod
 def setUpClass(c): c.s=HTTPServer(('127.0.0.1',0),H); threading.Thread(target=c.s.serve_forever,daemon=True).start(); c.base=f'http://127.0.0.1:{c.s.server_port}'
 @classmethod
 def tearDownClass(c): c.s.shutdown()
 def setUp(self): self.c=ComfyUIClient(self.base,.2)
 def put(self,b,s=200): H.response=(b,s)
 def test_valid_endpoint_schemes(self): ComfyUIClient('https://example.com/base/')
 def test_invalid_endpoint_scheme(self):
  with self.assertRaises(ValueError): ComfyUIClient('ftp://x')
 def test_missing_host(self):
  with self.assertRaises(ValueError): ComfyUIClient('http:///x')
 def test_query_fragment_rejection(self):
  for x in ('http://x/a?q=1','http://x/a#f'):
   with self.assertRaises(ValueError): ComfyUIClient(x)
 def test_base_path_trailing_slash(self): self.assertTrue(ComfyUIClient(self.base+'/api/').endpoint.endswith('/api'))
 def test_health_valid_live_like_shape(self): self.put({'system':{'os':'linux','python_version':'3.13'}}); self.assertTrue(self.c.health().healthy)
 def test_health_empty_system(self): self.put({'system':{}}); self.assertRaises(ComfyUIProtocolError,self.c.health)
 def test_health_malformed_object(self): self.put({}); self.assertRaises(ComfyUIProtocolError,self.c.health)
 def test_submit_success(self): self.put({'prompt_id':'abc'}); self.assertEqual(self.c.submit({}).value,'abc')
 def test_backend_ref_reuse_identity(self): r=BackendJobRef('abc'); self.put({'abc':{'status':{'status_str':'running'}}}); self.assertIs(self.c.history(r).prompt_id,r)
 def test_backend_job_ref_accepts_valid_string(self):
  value='abc'; ref=BackendJobRef(value); self.assertIs(ref.value,value)
 def test_backend_job_ref_rejects_empty_or_whitespace(self):
  for value in ('','   ','\t\n'):
   with self.assertRaises(ValueError): BackendJobRef(value)
 def test_backend_job_ref_rejects_non_string_values(self):
  for value in (1,True,[],{},None):
   with self.assertRaises(ValueError): BackendJobRef(value)
 def test_submit_invalid_prompt_ids(self):
  for v in (None,'','  ',True,1,[],{}): self.put({'prompt_id':v}); self.assertRaises(ComfyUIProtocolError,self.c.submit,{})
 def test_client_id_valid(self): self.put({'prompt_id':'x'}); self.c.submit({},' x ')
 def test_client_id_invalid(self):
  for v in ('','  ',1,False,[]): self.assertRaises(ComfyUIProtocolError,self.c.submit,{},v)
 def test_prompt_id_url_quoting(self): self.put({}); self.c.history('a/b c')
 def test_queue_running_known_shape(self):
  self.put({'queue_running':[[1,'run',{'prompt':{}},{'client_id':'c'},['node']]],'queue_pending':[]})
  snapshot=self.c.queue(); self.assertEqual(snapshot.state,QueueState.RUNNING); self.assertEqual([r.value for r in snapshot.running],['run'])
 def test_queue_pending_known_shape(self):
  self.put({'queue_running':[],'queue_pending':[[2,'wait',{'prompt':{}},{},['node']]]})
  snapshot=self.c.queue(); self.assertEqual(snapshot.state,QueueState.PENDING); self.assertEqual([r.value for r in snapshot.pending],['wait'])
 def test_queue_running_and_pending_extract_both_ids(self):
  self.put({'queue_running':[[1,'run',{}, {}, {}]],'queue_pending':[[2,'wait',{}, {}, {}]]})
  snapshot=self.c.queue(); self.assertEqual(snapshot.state,QueueState.RUNNING); self.assertEqual([r.value for r in snapshot.running],['run']); self.assertEqual([r.value for r in snapshot.pending],['wait'])
 def test_queue_empty(self): self.put({'queue_running':[],'queue_pending':[]}); self.assertEqual(self.c.queue().state,QueueState.EMPTY)
 def test_queue_malformed_lengths_fail_closed(self):
  for length in (3,4,6):
   self.put({'queue_running':[[1,'x'] + [{}] * (length-2)],'queue_pending':[]})
   self.assertEqual(self.c.queue().state,QueueState.UNKNOWN)
 def test_queue_invalid_first_field_fail_closed(self):
  for number in (True, '1', 1.0, None):
   self.put({'queue_running':[[number,'x',{}, {}, {}]],'queue_pending':[]})
   self.assertEqual(self.c.queue().state,QueueState.UNKNOWN)
 def test_queue_invalid_prompt_id_fail_closed(self):
  for prompt_id in (None, 2, '', '  ', '\t'):
   self.put({'queue_running':[[1,prompt_id,{}, {}, {}]],'queue_pending':[]})
   self.assertEqual(self.c.queue().state,QueueState.UNKNOWN)
 def test_queue_wrong_top_level_and_entry_types_fail_closed(self):
  self.put([])
  with self.assertRaises(ComfyUIProtocolError): self.c.queue()
  for body in ({'queue_running':{},'queue_pending':[]}, {'queue_running':[{}],'queue_pending':[]}):
   self.put(body); self.assertEqual(self.c.queue().state,QueueState.UNKNOWN)
 def test_queue_mixed_valid_and_malformed_fails_closed(self):
  self.put({'queue_running':[[1,'ok',{}, {}, {}],[2,'bad',{}, {}]],'queue_pending':[]})
  self.assertEqual(self.c.queue().state,QueueState.UNKNOWN)
 def test_history_not_found(self): self.put({}); self.assertEqual(self.c.history('x').state,HistoryState.NOT_FOUND)
 def test_history_queued(self): self.put({'x':{'status':{'status_str':'queued'}}}); self.assertEqual(self.c.history('x').state,HistoryState.QUEUED)
 def test_history_running(self): self.put({'x':{'status':{'status_str':'running'}}}); self.assertEqual(self.c.history('x').state,HistoryState.RUNNING)
 def test_history_success_completed(self): self.put({'x':{'status':{'status_str':'success','completed':True},'outputs':{}}}); self.assertEqual(self.c.history('x').state,HistoryState.SUCCEEDED)
 def test_history_contradictory_success_unknown(self): self.put({'x':{'status':{'status_str':'success','completed':False},'outputs':{}}}); self.assertEqual(self.c.history('x').state,HistoryState.UNKNOWN)
 def test_history_explicit_failure(self): self.put({'x':{'status':{'status_str':'error','exception_message':'bad'}}}); self.assertEqual(self.c.history('x').state,HistoryState.FAILED)
 def test_history_execution_error_form(self): self.put({'x':{'status':{'error':'bad'}}}); self.assertEqual(self.c.history('x').state,HistoryState.FAILED)
 def test_history_malformed_unknown(self): self.put({'x':{'status':{}}}); self.assertEqual(self.c.history('x').state,HistoryState.UNKNOWN)
 def test_refused_connection(self): self.assertRaises(ComfyUITransportError,ComfyUIClient('http://127.0.0.1:1',.1).health)
 def test_timeout(self):
  self.c._request=lambda *a,**k: (_ for _ in ()).throw(ComfyUITimeoutError('timeout'))
  self.assertRaises(ComfyUITimeoutError,self.c.health)
 def test_invalid_json(self):
  self.c._request=lambda *a,**k: (_ for _ in ()).throw(ComfyUIProtocolError('response was not valid JSON'))
  self.assertRaises(ComfyUIProtocolError,self.c.health)
 def test_404(self): self.put({},404); self.assertEqual(self.c.history('x').state,HistoryState.NOT_FOUND)
 def test_4xx(self): self.put({},400); self.assertRaises(ComfyUIRejectedError,self.c.submit,{})
 def test_5xx(self): self.put({},500); self.assertRaises(ComfyUIServerError,self.c.submit,{})
