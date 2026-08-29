import json, unittest
from urllib.parse import parse_qsl, urlencode, urlsplit
from unittest.mock import Mock, patch
from orquestador.adapters import *

class EventsTests(unittest.TestCase):
    def setUp(self):
        self.ref = BackendJobRef('job-1'); self.client = Mock(); self.client.endpoint='https://host:8188/base'
    def test_production_transport_exact_final_url(self):
        for endpoint in ('http://host:123/base','https://host:123/base'):
            final=ComfyUIObservation.websocket_url(endpoint,'cid'); ws=Mock(create_connection=Mock(return_value=Mock()))
            with patch('orquestador.adapters.events.importlib.import_module',return_value=ws): WebSocketClientTransport().connect(final,client_id='cid')
            ws.create_connection.assert_called_once_with(final)
    def test_production_transport_never_re_normalizes(self):
        ws=Mock(create_connection=Mock(return_value=Mock()))
        with patch('orquestador.adapters.events.importlib.import_module',return_value=ws), patch.object(ComfyUIObservation,'websocket_url',side_effect=AssertionError): WebSocketClientTransport().connect('ws://host/ws?clientId=x',client_id='x')
    def test_optional_import_failure_maps(self):
        with patch('orquestador.adapters.events.importlib.import_module',side_effect=ImportError):
            with self.assertRaises(ComfyUITransportError): WebSocketClientTransport().connect('ws://host/ws',client_id='x')

    def test_websocket_client_receive_normalizes_dependency_timeout(self):
        class DependencyTimeout(Exception): pass
        sock=Mock(); original=DependencyTimeout('receive timeout'); sock.recv.side_effect=original
        ws=Mock(create_connection=Mock(return_value=sock), WebSocketTimeoutException=DependencyTimeout)
        transport=WebSocketClientTransport()
        with patch('orquestador.adapters.events.importlib.import_module',return_value=ws): transport.connect('ws://host/ws',client_id='x')
        with self.assertRaises(ComfyUITimeoutError) as caught: transport.receive(1)
        self.assertIs(caught.exception.__cause__, original)

    def test_websocket_client_settimeout_and_connect_timeout_normalize_only_dependency(self):
        class DependencyTimeout(Exception): pass
        sock=Mock(); sock.settimeout.side_effect=DependencyTimeout('set timeout')
        ws=Mock(create_connection=Mock(return_value=sock), WebSocketTimeoutException=DependencyTimeout)
        transport=WebSocketClientTransport()
        with patch('orquestador.adapters.events.importlib.import_module',return_value=ws):
            transport.connect('ws://host/ws',client_id='x')
            with self.assertRaises(ComfyUITimeoutError): transport.receive(1)
            ws.create_connection.side_effect=DependencyTimeout('connect timeout')
            with self.assertRaises(ComfyUITimeoutError): transport.connect('ws://host/ws',client_id='x')

    def test_websocket_client_generic_exception_preserved(self):
        class DependencyTimeout(Exception): pass
        class GenericFailure(Exception): pass
        sock=Mock(); failure=GenericFailure('boom'); sock.recv.side_effect=failure
        ws=Mock(create_connection=Mock(return_value=sock), WebSocketTimeoutException=DependencyTimeout)
        transport=WebSocketClientTransport()
        with patch('orquestador.adapters.events.importlib.import_module',return_value=ws): transport.connect('ws://host/ws',client_id='x')
        with self.assertRaises(GenericFailure) as caught: transport.receive(1)
        self.assertIs(caught.exception, failure)

    def test_production_transport_timeout_observe_reconnect_and_terminal_fallback(self):
        class DependencyTimeout(Exception): pass
        sock=Mock(); sock.recv.side_effect=DependencyTimeout('live timeout')
        ws=Mock(create_connection=Mock(return_value=sock), WebSocketTimeoutException=DependencyTimeout)
        self.client.history.return_value=HistoryResult(self.ref,HistoryState.SUCCEEDED)
        transport=WebSocketClientTransport()
        with patch('orquestador.adapters.events.importlib.import_module',return_value=ws):
            out=list(ComfyUIObservation(self.client,transport=transport,reconnects=2,backoff=0).observe(self.ref))
        self.assertEqual(ws.create_connection.call_count,3); self.assertEqual(sock.close.call_count,3)
        self.assertEqual(out[-1].kind,ObservationKind.COMPLETED); self.assertEqual(out[-1].job_ref,self.ref); self.assertEqual(out[-1].issue_kind,ObservationIssueKind.TIMEOUT)
    def test_connection_failure_preserves_oserror(self):
        ws=Mock(); ws.create_connection.side_effect=OSError('refused')
        with patch('orquestador.adapters.events.importlib.import_module',return_value=ws):
            with self.assertRaises(OSError): WebSocketClientTransport().connect('ws://host/ws',client_id='x')
    def test_observe_production_route(self):
        sock=Mock(); sock.recv.return_value=json.dumps({'type':'execution_success','data':{'prompt_id':'job-1'}}); ws=Mock(create_connection=Mock(return_value=sock)); self.client.endpoint='http://host:123/base'
        with patch('orquestador.adapters.events.importlib.import_module',return_value=ws): out=list(ComfyUIObservation(self.client,reconnects=0).observe(self.ref))
        ws.create_connection.assert_called_once_with(ComfyUIObservation.websocket_url(self.client.endpoint,'orquestador')); self.assertEqual(out[0].kind,ObservationKind.COMPLETED)
    def test_url_encoding_and_scheme(self):
        u=ComfyUIObservation.websocket_url('https://host:8188/base?x=1','a &?#% ü')
        self.assertTrue(u.startswith('wss://host:8188/base/ws?x=1&clientId=')); self.assertIn('%26',u)
    def test_strict_correlation_and_shapes(self):
        self.assertIsNone(ComfyUIObservation._event(self.ref, {'type':'execution_start','data':{'prompt_id':'other'}}))
        self.assertEqual(ComfyUIObservation._event(self.ref, {'type':'progress','data':{'prompt_id':'job-1','value':2,'max':4}}).progress,.5)
        self.assertIsNone(ComfyUIObservation._event(self.ref, {'type':'progress','data':{'prompt_id':'job-1','value':2}}).progress)
        unsupported = ComfyUIObservation._event(self.ref, {'type':'unknown','data':{'prompt_id':'job-1'}})
        self.assertEqual(unsupported.kind, ObservationKind.UNKNOWN)
        self.assertEqual(unsupported.issue_kind, ObservationIssueKind.PROTOCOL)
    def test_malformed_and_terminal_dedup(self):
        t=Mock(); t.receive.side_effect=[b'not-json', json.dumps({'type':'execution_success','data':{'prompt_id':'job-1'}})]
        self.client.history.return_value=HistoryResult(self.ref,HistoryState.UNKNOWN); self.client.queue.return_value=QueueSnapshot()
        o=ComfyUIObservation(self.client,transport=t,reconnects=0)
        out=list(o.observe(self.ref)); self.assertEqual(out[-1].kind, ObservationKind.UNKNOWN); self.assertEqual(out[-1].issue_kind, ObservationIssueKind.PROTOCOL)
        t.close.assert_called()
    def test_structurally_invalid_event_data_fails_closed_without_accepting_later_success(self):
        t=Mock(); t.receive.side_effect=[
            json.dumps({'type':'execution_start','data':[]}),
            json.dumps({'type':'execution_success','data':{'prompt_id':'job-1'}}),
        ]
        self.client.history.return_value=HistoryResult(self.ref,HistoryState.UNKNOWN); self.client.queue.return_value=QueueSnapshot()
        out=list(ComfyUIObservation(self.client,transport=t,reconnects=2,backoff=0).observe(self.ref))
        self.assertEqual(t.receive.call_count, 1)
        self.assertNotIn(ObservationKind.COMPLETED, [e.kind for e in out])
        self.assertEqual(out[0].kind, ObservationKind.UNKNOWN)
        self.assertEqual(out[0].issue_kind, ObservationIssueKind.PROTOCOL)
    def test_timeout_fallback_unknown(self):
        t=Mock(); t.connect.side_effect=TimeoutError(); self.client.history.return_value=Mock(state=HistoryState.UNKNOWN,raw=None,error='x'); self.client.queue.return_value=Mock(running=(),pending=())
        self.assertEqual(list(ComfyUIObservation(self.client,transport=t,reconnects=1).observe(self.ref))[-1].kind,ObservationKind.UNKNOWN)

    def test_comfyui_timeout_receive_inconclusive_is_unknown_timeout(self):
        t=Mock(); t.receive.side_effect=ComfyUITimeoutError('timed out')
        self.client.history.return_value=HistoryResult(self.ref,HistoryState.UNKNOWN); self.client.queue.return_value=QueueSnapshot()
        out=list(ComfyUIObservation(self.client,transport=t,reconnects=0).observe(self.ref))
        self.assertEqual(out[-1].kind, ObservationKind.UNKNOWN)
        self.assertEqual(out[-1].issue_kind, ObservationIssueKind.TIMEOUT)

    def test_builtin_timeout_receive_inconclusive_is_unknown_timeout(self):
        t=Mock(); t.receive.side_effect=TimeoutError('timed out')
        self.client.history.return_value=HistoryResult(self.ref,HistoryState.UNKNOWN); self.client.queue.return_value=QueueSnapshot()
        out=list(ComfyUIObservation(self.client,transport=t,reconnects=0).observe(self.ref))
        self.assertEqual(out[-1].kind, ObservationKind.UNKNOWN)
        self.assertEqual(out[-1].issue_kind, ObservationIssueKind.TIMEOUT)

    def test_oserror_receive_inconclusive_is_unknown_transport(self):
        t=Mock(); t.receive.side_effect=OSError('socket down')
        self.client.history.return_value=HistoryResult(self.ref,HistoryState.UNKNOWN); self.client.queue.return_value=QueueSnapshot()
        out=list(ComfyUIObservation(self.client,transport=t,reconnects=0).observe(self.ref))
        self.assertEqual(out[-1].kind, ObservationKind.UNKNOWN)
        self.assertEqual(out[-1].issue_kind, ObservationIssueKind.TRANSPORT)

    def test_http_endpoint_maps_ws(self): self.assertEqual(ComfyUIObservation.websocket_url('http://host:1','x'),'ws://host:1/ws?clientId=x')
    def test_https_endpoint_maps_wss(self): self.assertTrue(ComfyUIObservation.websocket_url('https://host:1','x').startswith('wss://'))
    def test_existing_ws_not_duplicated(self): self.assertNotIn('/ws/ws',ComfyUIObservation.websocket_url('http://host/base/ws','x'))
    def test_base_path_preserved(self): self.assertIn('/base/ws?',ComfyUIObservation.websocket_url('http://host/base/','x'))
    def test_fragment_rejected(self): self.assertRaises(ValueError,ComfyUIObservation.websocket_url,'http://host/a#f','x')
    def test_invalid_scheme_rejected(self): self.assertRaises(ValueError,ComfyUIObservation.websocket_url,'ftp://host','x')
    def test_missing_host_rejected(self): self.assertRaises(ValueError,ComfyUIObservation.websocket_url,'http:///a','x')
    def test_execution_start_correlated(self): self.assertEqual(ComfyUIObservation._event(self.ref,{'type':'execution_start','data':{'prompt_id':'job-1'}}).kind,ObservationKind.RUNNING)
    def test_wrong_prompt_ignored(self): self.assertIsNone(ComfyUIObservation._event(self.ref,{'type':'execution_start','data':{'prompt_id':'x'}}))
    def test_success_correlated(self): self.assertEqual(ComfyUIObservation._event(self.ref,{'type':'execution_success','data':{'prompt_id':'job-1'}}).kind,ObservationKind.COMPLETED)
    def test_error_requires_message(self): self.assertEqual(ComfyUIObservation._event(self.ref,{'type':'execution_error','data':{'prompt_id':'job-1'}}).kind,ObservationKind.UNKNOWN)
    def test_reconnect_bound_exact(self):
        t=Mock(); t.connect.side_effect=TimeoutError(); self.client.history.return_value=Mock(state=HistoryState.UNKNOWN,raw=None,error='x'); self.client.queue.return_value=Mock(running=(),pending=()); list(ComfyUIObservation(self.client,transport=t,reconnects=2,backoff=0).observe(self.ref)); self.assertEqual(t.connect.call_count,3)
    def test_reconnect_success(self):
        t=Mock(); t.connect.side_effect=[TimeoutError(),None]; t.receive.return_value=json.dumps({'type':'execution_success','data':{'prompt_id':'job-1'}}); self.assertEqual(list(ComfyUIObservation(self.client,transport=t,reconnects=1,backoff=0).observe(self.ref))[0].kind,ObservationKind.COMPLETED)
    def test_ref_identity(self):
        t=Mock(); t.receive.return_value=json.dumps({'type':'execution_success','data':{'prompt_id':'job-1'}}); self.assertIs(list(ComfyUIObservation(self.client,transport=t,reconnects=0).observe(self.ref))[0].job_ref,self.ref)

    def test_timeout_classification_and_reconnect(self):
        t=Mock(); t.connect.side_effect=[TimeoutError(),None]; t.receive.return_value=json.dumps({'type':'execution_success','data':{'prompt_id':'job-1'}}); out=list(ComfyUIObservation(self.client,transport=t,reconnects=1,backoff=0).observe(self.ref)); self.assertEqual(out[-1].kind,ObservationKind.COMPLETED); self.assertEqual(t.connect.call_count,2)
    def test_transport_error_reconnect(self):
        t=Mock(); t.connect.side_effect=[ComfyUITransportError('down'),None]; t.receive.return_value=json.dumps({'type':'execution_success','data':{'prompt_id':'job-1'}}); self.assertEqual(list(ComfyUIObservation(self.client,transport=t,reconnects=1,backoff=0).observe(self.ref))[-1].kind,ObservationKind.COMPLETED)
    def test_protocol_error_fail_closed(self):
        t=Mock(); t.connect.side_effect=ComfyUIProtocolError('bad'); self.client.history.return_value=HistoryResult(self.ref,HistoryState.UNKNOWN); self.client.queue.return_value=QueueSnapshot(); self.assertEqual(list(ComfyUIObservation(self.client,transport=t,reconnects=2).observe(self.ref))[0].kind,ObservationKind.UNKNOWN); self.assertEqual(t.connect.call_count,1)
    def test_binary_unsupported_and_malformed_frames(self):
        t=Mock(); t.receive.side_effect=[b'\xff',json.dumps({'type':'execution_success','data':{'prompt_id':'job-1'}})]; self.client.history.return_value=HistoryResult(self.ref,HistoryState.UNKNOWN); self.client.queue.return_value=QueueSnapshot(); out=list(ComfyUIObservation(self.client,transport=t,reconnects=0).observe(self.ref)); self.assertEqual(out[-1].issue_kind, ObservationIssueKind.PROTOCOL); self.assertNotIn(ObservationKind.COMPLETED,[e.kind for e in out])

    def test_unrelated_unsupported_ignored(self):
        t=Mock(); t.receive.side_effect=[json.dumps({'type':'bogus','data':{'prompt_id':'other'}}), json.dumps({'type':'execution_success','data':{'prompt_id':'job-1'}})]
        self.assertEqual(list(ComfyUIObservation(self.client,transport=t,reconnects=0).observe(self.ref))[0].kind, ObservationKind.COMPLETED)

    def test_correlated_unsupported_event_closes_ws_attempt(self):
        t=Mock(); t.receive.side_effect=[json.dumps({'type':'bogus','data':{'prompt_id':'job-1'}}), json.dumps({'type':'execution_success','data':{'prompt_id':'job-1'}})]
        self.client.history.return_value=HistoryResult(self.ref,HistoryState.UNKNOWN); self.client.queue.return_value=QueueSnapshot()
        out=list(ComfyUIObservation(self.client,transport=t,reconnects=0).observe(self.ref))
        self.assertEqual(out[0].kind, ObservationKind.UNKNOWN)
        self.assertEqual(out[0].issue_kind, ObservationIssueKind.PROTOCOL)
        self.assertEqual(t.receive.call_count, 1)
        self.assertNotIn(ObservationKind.COMPLETED, [event.kind for event in out])

    def test_fallback_oserror_is_transport_unknown(self):
        t=Mock(); t.connect.side_effect=TimeoutError(); self.client.history.side_effect=OSError('down'); out=list(ComfyUIObservation(self.client,transport=t,reconnects=0).observe(self.ref)); self.assertEqual(out[-1].kind, ObservationKind.UNKNOWN); self.assertEqual(out[-1].issue_kind, ObservationIssueKind.TRANSPORT)
    def test_progress_valid_and_missing(self):
        self.assertEqual(ComfyUIObservation._event(self.ref,{'type':'progress','data':{'prompt_id':'job-1','value':3,'max':4}}).progress,.75); self.assertIsNone(ComfyUIObservation._event(self.ref,{'type':'progress','data':{'prompt_id':'job-1'}}).progress)
    def test_progress_invalid_max_no_terminal(self):
        for m in (0,-1,'4'):
            e=ComfyUIObservation._event(self.ref,{'type':'progress','data':{'prompt_id':'job-1','value':2,'max':m}}); self.assertIsNone(e.progress); self.assertNotIn(e.kind,(ObservationKind.COMPLETED,ObservationKind.FAILED))
    def test_execution_error_valid_and_malformed(self):
        self.assertEqual(ComfyUIObservation._event(self.ref,{'type':'execution_error','data':{'prompt_id':'job-1','exception_message':'boom'}}).kind,ObservationKind.FAILED); self.assertEqual(ComfyUIObservation._event(self.ref,{'type':'execution_error','data':{'prompt_id':'job-1'}}).kind,ObservationKind.UNKNOWN)
    def test_cleanup_all_exception_paths(self):
        for exc in (None,TimeoutError(),ComfyUITransportError('x'),ComfyUIProtocolError('x')):
            t=Mock(); t.receive.return_value=json.dumps({'type':'execution_success','data':{'prompt_id':'job-1'}})
            if exc: t.connect.side_effect=exc
            self.client.history.return_value=HistoryResult(self.ref,HistoryState.UNKNOWN); self.client.queue.return_value=QueueSnapshot(); list(ComfyUIObservation(self.client,transport=t,reconnects=0).observe(self.ref)); t.close.assert_called()
    def test_reconnect_exact_zero_and_positive(self):
        for n in (0,2):
            t=Mock(); t.connect.side_effect=TimeoutError(); self.client.history.return_value=HistoryResult(self.ref,HistoryState.UNKNOWN); self.client.queue.return_value=QueueSnapshot(); list(ComfyUIObservation(self.client,transport=t,reconnects=n,backoff=0).observe(self.ref)); self.assertEqual(t.connect.call_count,n+1)
    def test_history_terminal_and_queue_fallbacks(self):
        for state,kind in ((HistoryState.SUCCEEDED,ObservationKind.COMPLETED),(HistoryState.FAILED,ObservationKind.FAILED)):
            self.client.history.return_value=HistoryResult(self.ref,state); t=Mock(); t.connect.side_effect=TimeoutError(); self.assertEqual(list(ComfyUIObservation(self.client,transport=t,reconnects=0).observe(self.ref))[-1].kind,kind)
        for running,pending,kind in (((self.ref,),(),ObservationKind.RUNNING),((),(self.ref,),ObservationKind.QUEUED)):
            self.client.history.return_value=HistoryResult(self.ref,HistoryState.UNKNOWN); self.client.queue.return_value=QueueSnapshot(running=running,pending=pending); t=Mock(); t.connect.side_effect=TimeoutError(); self.assertEqual(list(ComfyUIObservation(self.client,transport=t,reconnects=0).observe(self.ref))[-1].kind,kind)
    def test_ambiguous_and_insufficient_evidence_unknown(self):
        self.client.history.return_value=HistoryResult(self.ref,HistoryState.UNKNOWN); self.client.queue.return_value=QueueSnapshot(running=(self.ref,),pending=(self.ref,)); t=Mock(); t.connect.side_effect=TimeoutError(); self.assertEqual(list(ComfyUIObservation(self.client,transport=t,reconnects=0).observe(self.ref))[-1].kind,ObservationKind.UNKNOWN)
        self.client.queue.return_value=QueueSnapshot(); self.assertEqual(list(ComfyUIObservation(self.client,transport=t,reconnects=0).observe(self.ref))[-1].kind,ObservationKind.UNKNOWN)
    def test_client_id_encoding_special_cases(self):
        endpoint = 'https://host:8188/base?existing=one&blank='
        client_id = ' id &?#% ñ '
        stripped = client_id.strip()
        final = ComfyUIObservation.websocket_url(endpoint, client_id)
        parts = urlsplit(final)
        existing_query = parse_qsl(urlsplit(endpoint).query, keep_blank_values=True)
        expected_pairs = existing_query + [('clientId', stripped)]
        expected_query = urlencode(expected_pairs, doseq=True)
        self.assertEqual((parts.scheme, parts.netloc, parts.path), ('wss', 'host:8188', '/base/ws'))
        self.assertEqual(parts.query, expected_query)
        self.assertEqual(parse_qsl(parts.query, keep_blank_values=True), expected_pairs)
        self.assertEqual(parse_qsl(parts.query, keep_blank_values=True).count(('clientId', stripped)), 1)
        self.assertEqual(final, 'wss://host:8188/base/ws?' + expected_query)

if __name__ == '__main__': unittest.main()
