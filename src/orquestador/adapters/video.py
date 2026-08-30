"""Small, shell-free FFprobe/FFmpeg boundary for transition-frame extraction."""
from dataclasses import dataclass
from pathlib import Path
import json
import subprocess

@dataclass(frozen=True)
class VideoFrame:
    path: Path
    frame_index: int
    frame_count: int

class VideoExtractionError(RuntimeError):
    pass

class FFmpegVideoAdapter:
    def __init__(self, ffprobe='ffprobe', ffmpeg='ffmpeg'):
        self.ffprobe, self.ffmpeg = ffprobe, ffmpeg
    def extract_last_frame(self, source, destination):
        src, dst = Path(source), Path(destination)
        try:
            p = subprocess.run([self.ffprobe,'-v','error','-count_frames','-select_streams','v:0','-show_entries','stream=nb_read_frames','-of','json',str(src)], capture_output=True, text=True, check=True, shell=False)
            streams = json.loads(p.stdout).get('streams')
            if not isinstance(streams, list) or not streams:
                raise VideoExtractionError('missing video stream')
            raw_count = streams[0].get('nb_read_frames')
            if raw_count in (None, 'N/A'):
                raise VideoExtractionError('frame count unavailable')
            count = int(raw_count)
        except Exception as exc: raise VideoExtractionError(f'ffprobe failed: {exc}') from exc
        if count <= 0: raise VideoExtractionError('video has no decodable frames')
        if dst.exists():
            raise VideoExtractionError('destination already exists')
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run([self.ffmpeg,'-v','error','-i',str(src),'-vf',rf"select=eq(n\,{count-1})",'-frames:v','1','-y',str(dst)], capture_output=True, text=True, check=True, shell=False)
        except Exception as exc: raise VideoExtractionError(f'ffmpeg failed: {exc}') from exc
        if not dst.is_file() or dst.stat().st_size == 0: raise VideoExtractionError('extracted frame is missing or empty')
        return VideoFrame(dst, count-1, count)
