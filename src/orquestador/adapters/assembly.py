"""Fail-closed FFmpeg/FFprobe boundary for final video assembly."""
from pathlib import Path
import json, subprocess, tempfile, os

class AssemblyError(RuntimeError):
    pass

class FFmpegAssemblyAdapter:
    def __init__(self, ffprobe='ffprobe', ffmpeg='ffmpeg'):
        self.ffprobe, self.ffmpeg = ffprobe, ffmpeg

    def _probe(self, path):
        try:
            p = subprocess.run([self.ffprobe, '-v','error','-show_streams','-show_format','-of','json',str(path)], capture_output=True, text=True, check=True, shell=False)
            data=json.loads(p.stdout); streams=data.get('streams')
            if not isinstance(streams,list) or not streams: raise AssemblyError('missing streams')
            video=[s for s in streams if s.get('codec_type')=='video']
            if len(video)!=1: raise AssemblyError('exactly one video stream required')
            audio=tuple(tuple(s.get(k) for k in ('codec_type','codec_name','sample_rate','channels','sample_fmt','channel_layout','profile','level')) for s in streams if s.get('codec_type')=='audio')
            v=video[0]
            return tuple(v.get(k) for k in ('codec_name','codec_tag_string','profile','level','width','height','pix_fmt','sample_fmt','r_frame_rate','time_base')) + (audio,)
        except AssemblyError: raise
        except Exception as exc: raise AssemblyError(f'ffprobe failed: {exc}') from exc

    def assemble(self, sources, destination, *, reencode=False):
        srcs=tuple(Path(s) for s in sources); dst=Path(destination)
        if len(srcs)<2: raise AssemblyError('at least two chunks required')
        if dst.suffix.lower() != '.mp4': raise AssemblyError('destination must have .mp4 suffix')
        if dst.exists(): raise AssemblyError('destination already exists')
        for s in srcs:
            if not s.is_file() or s.stat().st_size==0: raise AssemblyError('missing or empty chunk')
        signatures=[self._probe(s) for s in srcs]
        if not reencode and any(sig != signatures[0] for sig in signatures[1:]): raise AssemblyError('incompatible chunk streams')
        dst.parent.mkdir(parents=True, exist_ok=True)
        fd, list_name=tempfile.mkstemp(prefix='.orq-concat-', suffix='.txt', dir=dst.parent)
        os.close(fd); list_path=Path(list_name)
        fd, temp_name=tempfile.mkstemp(prefix='.'+dst.stem+'-', suffix=dst.suffix or '.mp4', dir=dst.parent)
        os.close(fd); temp_out=Path(temp_name)
        try:
            list_path.write_text(''.join(("file '" + str(s).replace("'", "'\\''") + "'" + "\n") for s in srcs), encoding='utf-8')
            args=[self.ffmpeg,'-v','error','-f','concat','-safe','0','-i',str(list_path)]
            args += ['-c:v','libx264','-c:a','aac'] if reencode else ['-c','copy']
            args += ['-y',str(temp_out)]
            subprocess.run(args,capture_output=True,text=True,check=True,shell=False)
            if not temp_out.is_file() or temp_out.stat().st_size==0: raise AssemblyError('assembly output missing or empty')
            # Validate the exact bytes/inode that will be published.  Publication
            # is then a single non-overwriting link operation with no fallible
            # post-publication probe or cleanup of another process's destination.
            self._probe(temp_out)
            try: os.link(temp_out,dst)
            except FileExistsError as exc: raise AssemblyError('destination appeared during assembly') from exc
            except OSError as exc: raise AssemblyError(f'non-overwriting publication unavailable: {exc}') from exc
            return dst
        except AssemblyError: raise
        except subprocess.CalledProcessError as exc: raise AssemblyError(f'ffmpeg assembly failed: {exc.stderr or exc}') from exc
        except Exception as exc: raise AssemblyError(f'ffmpeg assembly failed: {exc}') from exc
        finally:
            for p in (list_path,temp_out):
                try: p.unlink()
                except FileNotFoundError: pass
