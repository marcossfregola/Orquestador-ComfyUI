import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from orquestador.adapters.assembly import FFmpegAssemblyAdapter, AssemblyError
from orquestador.application.assembly import AssembleExecutionUseCase

class F8AssemblyTests(unittest.TestCase):
    def test_concat_copy_validates_and_preserves_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); a=root/'a.mp4'; b=root/'b.mp4'; out=root/'final.mp4'; a.write_bytes(b'a'); b.write_bytes(b'b')
            probe=json.dumps({'streams':[{'codec_type':'video','codec_name':'h264','width':10,'height':10,'pix_fmt':'yuv420p','r_frame_rate':'24/1','time_base':'1/24'}]})
            def run(args,**kw):
                if args[0]=='probe': return type('P',(),{'stdout':probe})()
                Path(args[-1]).write_bytes(b'final'); return type('P',(),{})()
            with patch('subprocess.run',side_effect=run): FFmpegAssemblyAdapter('probe','ff').assemble([a,b],out)
            self.assertTrue(out.exists()); self.assertTrue(a.exists()); self.assertTrue(b.exists())
    def test_incompatible_and_existing_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d); a=r/'a'; b=r/'b'; a.write_bytes(b'x'); b.write_bytes(b'y')
            p1=json.dumps({'streams':[{'codec_type':'video','codec_name':'h264','width':1}]}); p2=json.dumps({'streams':[{'codec_type':'video','codec_name':'hevc','width':1}]})
            with patch('subprocess.run',side_effect=[type('P',(),{'stdout':p1})(),type('P',(),{'stdout':p2})()]):
                with self.assertRaises(AssemblyError): FFmpegAssemblyAdapter().assemble([a,b],r/'o')
    def test_application_rejects_escape(self):
        result=AssembleExecutionUseCase(None, tempfile.gettempdir()).execute(['..\\x','y'], 'o')
        self.assertFalse(result.success)

    def test_unique_recognized_temp_and_non_overwrite_race(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); a=root/'a.mp4'; b=root/'b.mp4'; out=root/'final.mp4'; unrelated=root/'keep.tmp'
            a.write_bytes(b'a'); b.write_bytes(b'b'); unrelated.write_bytes(b'keep')
            probe=json.dumps({'streams':[{'codec_type':'video','codec_name':'h264','codec_tag_string':'avc1','width':10,'height':10,'pix_fmt':'yuv420p','r_frame_rate':'24/1','time_base':'1/24'}]})
            def run(args,**kw):
                if args[0] == 'probe': return type('P',(),{'stdout':probe})()
                self.assertTrue(Path(args[-1]).suffix == '.mp4')
                Path(args[-1]).write_bytes(b'final'); out.write_bytes(b'appeared')
                return type('P',(),{})()
            with patch('subprocess.run',side_effect=run):
                with self.assertRaises(AssemblyError): FFmpegAssemblyAdapter('probe','ff').assemble([a,b],out)
            self.assertEqual(out.read_bytes(), b'appeared'); self.assertEqual(unrelated.read_bytes(), b'keep')

    def test_failed_final_validation_leaves_no_destination(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); a=root/'a.mp4'; b=root/'b.mp4'; out=root/'final.mp4'; a.write_bytes(b'a'); b.write_bytes(b'b')
            probe=json.dumps({'streams':[{'codec_type':'video','codec_name':'h264','width':10}]})
            calls=[]
            def run(args,**kw):
                if args[0]=='probe':
                    calls.append(args[-1])
                    if len(calls) == 3:
                        raise RuntimeError('simulated final validation failure')
                    return type('P',(),{'stdout':probe})()
                Path(args[-1]).write_bytes(b'final'); return type('P',(),{})()
            with patch('subprocess.run',side_effect=run):
                with self.assertRaises(AssemblyError): FFmpegAssemblyAdapter('probe','ff').assemble([a,b],out)
            self.assertFalse(out.exists())

    def test_destination_suffix_is_explicitly_mp4(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); a=root/'a.mp4'; b=root/'b.mp4'; a.write_bytes(b'a'); b.write_bytes(b'b')
            adapter=FFmpegAssemblyAdapter()
            for name in ('final.mkv','final','final.MP4'):
                if name.endswith('MP4'):
                    continue
                with self.assertRaises(AssemblyError): adapter.assemble([a,b],root/name)
