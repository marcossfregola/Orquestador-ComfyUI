import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from orquestador.adapters.video import FFmpegVideoAdapter, VideoExtractionError

class VideoAdapterTests(unittest.TestCase):
    def test_exact_probe_and_n_minus_one(self):
        with tempfile.TemporaryDirectory() as d:
            dst=Path(d)/'x.png'
            def run(args, **kw):
                if args[0]=='probe': return type('P',(),{'stdout':json.dumps({'streams':[{'nb_read_frames':'4'}]})})()
                dst.write_bytes(b'x'); return type('P',(),{})()
            with patch('subprocess.run', side_effect=run) as call:
                out=FFmpegVideoAdapter('probe','mpeg').extract_last_frame(Path(d)/'a.mp4',dst)
            self.assertEqual((out.frame_index,out.frame_count),(3,4)); self.assertFalse(call.call_args_list[0].kwargs['shell']); self.assertFalse(call.call_args_list[1].kwargs['shell'])
            self.assertEqual(call.call_args_list[1].args[0][call.call_args_list[1].args[0].index('-vf')+1], r'select=eq(n\,3)')
    def test_invalid_json_missing_stream_na_zero_and_ffprobe_fail(self):
        for stdout in ('not-json', json.dumps({}), json.dumps({'streams':[]}), json.dumps({'streams':[{}]}), json.dumps({'streams':[{'nb_read_frames':'N/A'}]}), json.dumps({'streams':[{'nb_read_frames':'0'}]})):
            with self.subTest(stdout=stdout), tempfile.TemporaryDirectory() as d, patch('subprocess.run', return_value=type('P',(),{'stdout':stdout})()):
                with self.assertRaises(VideoExtractionError): FFmpegVideoAdapter().extract_last_frame(Path(d)/'a.mp4',Path(d)/'x.png')
        with tempfile.TemporaryDirectory() as d, patch('subprocess.run', side_effect=RuntimeError('probe')):
            with self.assertRaises(VideoExtractionError): FFmpegVideoAdapter().extract_last_frame(Path(d)/'a.mp4',Path(d)/'x.png')
    def test_ffmpeg_failure_and_missing_or_empty_output_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            probe=type('P',(),{'stdout':json.dumps({'streams':[{'nb_read_frames':'2'}]})})()
            with patch('subprocess.run', side_effect=[probe,RuntimeError('ffmpeg')]):
                with self.assertRaises(VideoExtractionError): FFmpegVideoAdapter().extract_last_frame(Path(d)/'a.mp4',Path(d)/'x.png')
            with patch('subprocess.run', side_effect=[probe,type('P',(),{})()]):
                with self.assertRaises(VideoExtractionError): FFmpegVideoAdapter().extract_last_frame(Path(d)/'a.mp4',Path(d)/'y.png')
    def test_fail_closed_probe_and_existing(self):
        with tempfile.TemporaryDirectory() as d:
            with patch('subprocess.run', return_value=type('P',(),{'stdout':'{"streams":[]}'} )()):
                self.assertRaises(VideoExtractionError, FFmpegVideoAdapter().extract_last_frame, 'a', Path(d)/'x')
            p=Path(d)/'x'; p.write_bytes(b'x')
            self.assertRaises(VideoExtractionError, FFmpegVideoAdapter().extract_last_frame, 'a', p)
