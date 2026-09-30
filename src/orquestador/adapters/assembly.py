"""Fail-closed FFmpeg/FFprobe boundary for final video assembly."""
from pathlib import Path
from dataclasses import dataclass
import hashlib, json, subprocess, tempfile, os
from uuid import uuid4

class AssemblyError(RuntimeError):
    pass

@dataclass(frozen=True)
class StagedAssemblyOutput:
    path: Path
    sha256: str
    probe_signature: tuple

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

    @staticmethod
    def _sha256(path):
        digest=hashlib.sha256()
        with Path(path).open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):
                digest.update(block)
        return digest.hexdigest()

    def inspect(self, path):
        """Validate a nonempty MP4 with FFprobe and return its byte identity."""
        target=Path(path)
        if target.suffix.lower()!='.mp4' or not target.is_file() or target.stat().st_size==0:
            raise AssemblyError('final assembly is missing, empty, or not MP4')
        return self._sha256(target), self._probe(target)

    def stage(self, sources, staging_destination, *, reencode=False):
        """Create and validate a durable staged MP4 without publishing over anything."""
        srcs=tuple(Path(source) for source in sources); staged=Path(staging_destination)
        if len(srcs)<2: raise AssemblyError('at least two chunks required')
        if staged.suffix.lower()!='.mp4': raise AssemblyError('staging destination must have .mp4 suffix')
        if staged.exists(): raise AssemblyError('staging destination already exists')
        for source in srcs:
            if not source.is_file() or source.stat().st_size==0: raise AssemblyError('missing or empty chunk')
        signatures=[self._probe(source) for source in srcs]
        if not reencode and any(signature!=signatures[0] for signature in signatures[1:]): raise AssemblyError('incompatible chunk streams')
        staged.parent.mkdir(parents=True,exist_ok=True)
        fd,list_name=tempfile.mkstemp(prefix='.orq-concat-',suffix='.txt',dir=staged.parent); os.close(fd)
        list_path=Path(list_name)
        try:
            list_path.write_text(''.join(("file '"+str(source).replace("'","'\\''")+"'\n") for source in srcs),encoding='utf-8')
            args=[self.ffmpeg,'-v','error','-n','-f','concat','-safe','0','-i',str(list_path)]
            args += ['-c:v','libx264','-c:a','aac'] if reencode else ['-c','copy']
            args += [str(staged)]
            subprocess.run(args,capture_output=True,text=True,check=True,shell=False)
            sha,signature=self.inspect(staged)
            return StagedAssemblyOutput(staged,sha,signature)
        except AssemblyError: raise
        except subprocess.CalledProcessError as exc: raise AssemblyError(f'ffmpeg assembly failed: {exc.stderr or exc}') from exc
        except Exception as exc: raise AssemblyError(f'ffmpeg assembly failed: {exc}') from exc
        finally:
            try:list_path.unlink()
            except FileNotFoundError:pass

    def publish(self, staged, destination, *, expected_sha256):
        """Atomically link a previously verified stage without replacing a destination."""
        source=Path(staged); target=Path(destination)
        if target.suffix.lower()!='.mp4' or source.suffix.lower()!='.mp4': raise AssemblyError('assembly publication paths must be MP4')
        if target.exists(): raise AssemblyError('destination already exists')
        sha,_=self.inspect(source)
        if sha!=expected_sha256: raise AssemblyError('staged output identity mismatch')
        target.parent.mkdir(parents=True,exist_ok=True)
        try:os.link(source,target)
        except FileExistsError as exc:raise AssemblyError('destination appeared during assembly') from exc
        except OSError as exc:raise AssemblyError(f'non-overwriting publication unavailable: {exc}') from exc
        return target

    def assemble(self, sources, destination, *, reencode=False):
        srcs=tuple(Path(s) for s in sources); dst=Path(destination)
        if len(srcs)<2: raise AssemblyError('at least two chunks required')
        if dst.suffix.lower() != '.mp4': raise AssemblyError('destination must have .mp4 suffix')
        if dst.exists(): raise AssemblyError('destination already exists')
        staged=dst.with_name(f'.{dst.stem}-{uuid4().hex}.mp4')
        try:
            result=self.stage(srcs,staged,reencode=reencode)
            self.publish(staged,dst,expected_sha256=result.sha256)
            return dst
        except AssemblyError: raise
        except Exception as exc: raise AssemblyError(f'assembly publication failed: {exc}') from exc
        finally:
            try:staged.unlink()
            except FileNotFoundError:pass
