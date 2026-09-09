import json, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import TestCase

from orquestador.adapters.http import ComfyUIClient, ComfyUIRejectedError
from orquestador.application.f11_1b import InputMaterializationService

class _Handler(BaseHTTPRequestHandler):
    reject_prompt = False
    def do_POST(self):
        if self.path == '/prompt':
            if self.reject_prompt:
                self.send_response(400); self.end_headers(); self.wfile.write(b'bad'); return
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(b'{"prompt_id":"job-1"}')
        elif self.path == '/upload/image':
            n=int(self.headers.get('Content-Length','0')); body=self.rfile.read(n).decode('latin1')
            import re
            m=re.search(r'filename="([^"]+)"', body); sm=re.search(r'name="subfolder"\r\n\r\n([^\r]+)', body)
            name=m.group(1) if m else ''; subfolder=sm.group(1) if sm else ''
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(json.dumps({'type':'input','name':name,'subfolder':subfolder}).encode())
        else: self.send_response(400); self.end_headers()
    def do_GET(self):
        if self.path == '/history/job-1':
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(b'{"job-1":{"outputs":{}}}')
        elif self.path == '/system_stats':
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(b'{"system":{"os":"test"}}')
        elif self.path == '/readyz':
            self.send_response(200); self.send_header('Content-Type','text/plain'); self.end_headers(); self.wfile.write(b'ready')
        else: self.send_response(404); self.end_headers()
    def log_message(self, *args): pass

class F111BIntegratedHarnessTests(TestCase):
    def _server(self, handler):
        s=HTTPServer(('127.0.0.1',0),handler); ready=threading.Event()
        def run():
            ready.set(); s.serve_forever()
        t=threading.Thread(target=run,daemon=True); t.start(); self.assertTrue(ready.wait(2)); return s,t
    def _wait_ready(self, client, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                import urllib.request
                with urllib.request.urlopen(client.endpoint + '/readyz', timeout=0.2) as r:
                    if r.status == 200 and r.read() == b'ready': return
            except Exception: pass
        self.fail('local /readyz probe timed out')
    def test_real_http_transport_and_materialization_cardinality(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); initial=root/'initial.png'; initial.write_bytes(b'x')
            refs=[root/f'r{i}.png' for i in range(6)]
            for p in refs: p.write_bytes(b'r')
            s,t=self._server(_Handler)
            try:
                c=ComfyUIClient(f'http://127.0.0.1:{s.server_port}')
                self._wait_ready(c)
                self.assertTrue(c.health().healthy)
                self.assertEqual(str(c.submit({'1': {'class_type':'X'}})), 'job-1')
                materialized = InputMaterializationService(c, root).materialize(initial, refs[:1])
                self.assertEqual(materialized.initial.subfolder, 'orquestador/static')
                self.assertEqual(materialized.initial.name, 'initial-' + __import__('hashlib').sha256(b'x').hexdigest()[:16] + '.png')
                for n in (0,1,6): self.assertEqual(len(InputMaterializationService().materialize(initial,refs[:n]).references), n)
            finally: s.shutdown(); s.server_close(); t.join(2); self.assertFalse(t.is_alive())

    def test_definite_http_400_is_rejection(self):
        class Reject(_Handler): reject_prompt = True
        s,t=self._server(Reject)
        try:
            c=ComfyUIClient(f'http://127.0.0.1:{s.server_port}'); self._wait_ready(c); self.assertTrue(c.health().healthy)
            with self.assertRaises(ComfyUIRejectedError): c.submit({})
        finally: s.shutdown(); s.server_close(); t.join(2); self.assertFalse(t.is_alive())
