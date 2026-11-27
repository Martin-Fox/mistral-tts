"""Strict reference-audio decoding, separate from long audiobook compilation."""
import io
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import wave

try:
    import resource
except ImportError:  # Windows has no resource module.
    resource = None

from src.core.ffmpeg_utils import get_ffmpeg_path
from src.core.process_runner import process_budget, run_process_async
from src.core.resource_limits import ResourceLimits, ResourceLimitExceeded


PCM_CODECS = 'pcm_u8,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_f64le'


def reference_format(path: Path, limit: int) -> str:
    """Reject other containers before launching any native parser."""
    if not 0 < path.stat().st_size <= limit:
        raise ResourceLimitExceeded('Voice sample is empty or exceeds MAX_VOICE_UPLOAD_BYTES')
    with path.open('rb') as stream:
        header = stream.read(12)
    extension = path.suffix.lower()
    if extension == '.wav' and header[:4] == b'RIFF' and header[8:12] == b'WAVE':
        return 'wav'
    if extension == '.mp3' and (header[:3] == b'ID3' or (
            len(header) >= 2 and header[0] == 255 and header[1] & 0xe0 == 0xe0)):
        return 'mp3'
    raise ValueError('Voice reference must be MP3 or PCM WAV with matching file contents')


def reference_environment(directory):
    # No API keys, proxy credentials, dotenv discovery or FFREPORT/loader hooks.
    env = {key: os.environ[key] for key in ('PATH', 'SystemRoot', 'WINDIR', 'SYSTEMDRIVE')
           if key in os.environ}
    env.update(TMPDIR=str(directory), TMP=str(directory), TEMP=str(directory),
               HOME=str(directory), USERPROFILE=str(directory), LANG='C.UTF-8',
               OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    return env


def reference_command(binary, source, destination, fmt, limits, timeout, output_limit):
    command = [binary, '-nostdin', '-hide_banner', '-loglevel', 'error', '-xerror', '-y',
               '-max_alloc', str(16 * 1024 * 1024), '-threads', '1', '-filter_threads', '1',
               '-protocol_whitelist', 'file', '-format_whitelist', fmt,
               '-codec_whitelist', 'mp3,mp3float' if fmt == 'mp3' else PCM_CODECS,
               '-f', fmt, '-i', str(source), '-map', '0:a:0', '-vn', '-sn', '-dn',
               '-t', str(limits.max_voice_seconds + 1), '-af', 'afftdn',
               '-ar', '24000', '-ac', '1', '-c:a', 'pcm_s16le', '-f', 'wav',
               '-fs', str(output_limit), str(destination)]
    if sys.platform.startswith('linux'):
        limiter = shutil.which('prlimit')
        if limiter is None:
            raise RuntimeError('Voice decoding on Linux requires prlimit (util-linux)')
        command = [limiter, f'--as={limits.max_voice_process_memory_bytes}',
                   f'--fsize={output_limit}', f'--cpu={math.ceil(timeout)}',
                   '--core=0', '--', *command]
    return command


def apply_reference_rlimits(limits, timeout, output_limit):
    """Hard rlimits inside the decoder child; only used via preexec_fn on POSIX."""
    address_space = limits.max_voice_process_memory_bytes
    resource.setrlimit(resource.RLIMIT_AS, (address_space, address_space))
    if hasattr(resource, 'RLIMIT_FSIZE'):
        resource.setrlimit(resource.RLIMIT_FSIZE, (output_limit, output_limit))
    if hasattr(resource, 'RLIMIT_CPU'):
        cpu = math.ceil(timeout)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    if hasattr(resource, 'RLIMIT_CORE'):
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def reference_preexec(limits, timeout, output_limit):
    """preexec_fn applying the same hard limits on POSIX platforms without prlimit.

    Linux keeps the util-linux prlimit wrapper in reference_command; every other
    POSIX platform gets at least the RLIMIT_AS address-space budget here.
    """
    if resource is None or not hasattr(resource, 'RLIMIT_AS'):
        return None
    if sys.platform.startswith('linux'):
        return None
    return lambda: apply_reference_rlimits(limits, timeout, output_limit)


async def prepare_reference(path: Path) -> bytes:
    """Return only validated normalized audio; never fall back to the original."""
    path = path.resolve(strict=True)
    limits = ResourceLimits.from_env()
    fmt = reference_format(path, limits.max_voice_upload_bytes)
    binary = get_ffmpeg_path()
    binary = shutil.which(binary) or str(Path(binary).resolve())
    timeout = process_budget()
    # 24 kHz mono s16 PCM plus a small header; decode one extra second to
    # detect overlong input instead of silently accepting a truncated sample.
    output_limit = min(limits.max_voice_upload_bytes, (limits.max_voice_seconds + 1) * 48000 + 4096)
    with tempfile.TemporaryDirectory(prefix='booksmith-voice-') as directory:
        destination = Path(directory) / 'reference.wav'
        command = reference_command(binary, path, destination, fmt, limits, timeout, output_limit)
        try:
            await run_process_async(command, timeout=timeout, env=reference_environment(directory),
                                    cwd=directory, max_output_bytes=65536,
                                    preexec_fn=reference_preexec(limits, timeout, output_limit))
        except subprocess.CalledProcessError:
            raise ValueError('Voice reference could not be decoded as supported MP3/PCM WAV') from None
        if not destination.is_file() or not 0 < destination.stat().st_size < output_limit:
            raise ResourceLimitExceeded('Decoded voice sample is empty or exceeds its output budget')
        with destination.open('rb') as stream:
            data = stream.read(output_limit + 1)
        if len(data) >= output_limit:
            raise ResourceLimitExceeded('Decoded voice sample exceeds its output budget')
        try:
            with wave.open(io.BytesIO(data)) as audio:
                frames = audio.getnframes()
                if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (24000, 1, 2):
                    raise ValueError('Unexpected decoded voice format')
                if frames <= 0 or frames > limits.max_voice_seconds * 24000:
                    raise ResourceLimitExceeded('Voice duration exceeds MAX_VOICE_SECONDS or is empty')
                if len(audio.readframes(frames)) != frames * 2:
                    raise ValueError('Decoded voice sample is truncated')
        except (wave.Error, EOFError):
            raise ValueError('Invalid decoded voice sample') from None
        return data
