"""Run portable regressions in a disposable Unicode checkout, without real keys."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


REPOSITORY = Path(__file__).resolve().parents[1]


def main():
    # Copy only source/tests, never the user's dotenv, database or recordings.
    with tempfile.TemporaryDirectory(prefix='booksmith-platform-') as temporary:
        checkout = Path(temporary) / "Reader's książki with spaces"
        checkout.mkdir()
        for name in ('src', 'tests'):
            shutil.copytree(REPOSITORY / name, checkout / name,
                            ignore=shutil.ignore_patterns('__pycache__', '.env', '.env.*'))
        shutil.copyfile(REPOSITORY / 'pytest.ini', checkout / 'pytest.ini')
        (checkout / 'scripts').mkdir()
        shutil.copyfile(REPOSITORY / 'scripts/build_ffmpeg.sh', checkout / 'scripts/build_ffmpeg.sh')
        environment = dict(os.environ)
        for name in list(environment):
            if name.startswith(('MISTRAL_', 'OPENAI_', 'APP_', 'SESSION_', 'LOGIN_',
                                'API_', 'AUDIO_', 'REQUEST_', 'MAX_', 'STORAGE_', 'CACHE_LOCK_',
                                'WEB_CONCURRENCY', 'INPUT_TEXT_ENCODING', 'BOOKSMITH_ENV_FILE')):
                del environment[name]
        environment['BOOKSMITH_ENV_FILE'] = str(checkout / '.env')
        # Test fixture strings/files use UTF-8 on all platforms. The process-output
        # regression separately tests malformed bytes, independent of this setting.
        environment['PYTHONUTF8'] = '1'
        environment['PYTHONPATH'] = str(checkout)
        return subprocess.run([
            sys.executable, '-m', 'pytest', '-q', '--durations=5',
            'tests/test_platform_smoke.py', 'tests/test_ffmpeg_utils.py',
            'tests/test_audio_publication.py',
            'tests/test_cache_io.py', 'tests/test_process_runner.py',
            'tests/test_media_security.py',
            'tests/test_web_security.py',
            'tests/test_sdk_contract.py',
            'tests/test_storage_retention.py', 'tests/test_auth.py',
        ], cwd=checkout, env=environment, timeout=180).returncode


if __name__ == '__main__':
    raise SystemExit(main())
