"""Exercise the real CLI entry point in isolated subprocesses with fake I/O."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


REPOSITORY = Path(__file__).resolve().parents[1]
RUNNER = textwrap.dedent('''\
    import os
    from pathlib import Path
    import runpy
    import socket

    import dotenv
    dotenv.load_dotenv = lambda *args, **kwargs: False

    def forbid_network(*args, **kwargs):
        Path("network_attempted").write_text("unexpected network access")
        raise AssertionError("Network disabled in CLI regression tests")
    socket.socket.connect = forbid_network
    socket.create_connection = forbid_network

    from src.api import factory
    from src.core.audio_compiler import AudioCompiler

    class FakeClient:
        model = factory.DEFAULT_TTS_MODELS["mistral"]
        voice_sample_bytes = None

        def set_voice_id(self, voice_id):
            pass

        async def generate_audio(self, text, output_path):
            Path("api_called").write_text(text)
            if os.getenv("CLI_TEST_FAILURE") == "generation":
                raise RuntimeError("simulated generation failure")
            output_path.write_bytes(b"fake chunk audio" * 20)

    def compile_audio(self, chunk_files, output_path):
        Path("compile_called").write_text(str(len(chunk_files)))
        if os.getenv("CLI_TEST_FAILURE") == "compilation":
            raise RuntimeError("simulated compilation failure")
        output_path.write_bytes(b"fake compiled audiobook")
        return {"output_duration": 1.0, "expected_duration": 1.0}

    factory.get_tts_client = lambda engine, key: FakeClient()
    AudioCompiler.compile = compile_audio
    runpy.run_module("src.cli", run_name="__main__")
''')


@pytest.fixture
def invoke_cli(tmp_path):
    runner = tmp_path / 'run_cli.py'
    runner.write_text(RUNNER, encoding='utf-8')

    def invoke(arguments, *, failure='', settings=None):
        # No inherited API credentials, dotenv files or application storage.
        environment = {name: os.environ[name] for name in ('PATH', 'SYSTEMROOT', 'WINDIR') if name in os.environ}
        environment.update(PYTHONPATH=str(REPOSITORY), PYTHONIOENCODING='utf-8', CLI_TEST_FAILURE=failure)
        environment['PYTHONPATH'] = os.environ.get('PYTHONPATH', str(REPOSITORY))
        environment['BOOKSMITH_ENV_FILE'] = str(tmp_path / '.env')
        environment.update(settings or {})
        result = subprocess.run([sys.executable, str(runner), *arguments], cwd=tmp_path,
                                env=environment, capture_output=True, text=True, encoding='utf-8', timeout=20)
        assert not (tmp_path / 'network_attempted').exists()
        return result
    return invoke


def arguments(path):
    return ['--text', str(path), '--output', 'audiobook.mp3', '--api-key', 'dummy-key']


def test_missing_input_exits_one_before_generation(invoke_cli, tmp_path):
    result = invoke_cli(arguments(tmp_path / 'missing.txt'))
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'Error:' in result.stdout
    assert not (tmp_path / 'api_called').exists()
    assert not (tmp_path / 'compile_called').exists()
    assert not (tmp_path / 'audiobook.mp3').exists()


def test_completed_pipeline_exits_zero(invoke_cli, tmp_path):
    source = tmp_path / 'book.txt'
    source.write_text('Complete book with trailing text', encoding='utf-8')
    result = invoke_cli(arguments(source))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Success!' in result.stdout
    assert (tmp_path / 'api_called').read_text() == source.read_text()
    assert (tmp_path / 'compile_called').exists()
    assert (tmp_path / 'audiobook.mp3').read_bytes() == b'fake compiled audiobook'


@pytest.mark.parametrize('failure', ['generation', 'compilation'])
def test_pipeline_failure_exits_one(invoke_cli, tmp_path, failure):
    source = tmp_path / 'book.txt'
    source.write_text('Input text', encoding='utf-8')
    result = invoke_cli(arguments(source), failure=failure)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'Error:' in result.stdout
    assert f'simulated {failure} failure' in result.stdout
    assert 'Success!' not in result.stdout
    assert not (tmp_path / 'audiobook.mp3').exists()


def test_initialization_error_exits_one_with_readable_error(invoke_cli, tmp_path):
    result = invoke_cli(arguments(tmp_path / 'book.txt'), settings={'AUDIO_PROCESS_TIMEOUT_SECONDS': 'invalid'})
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'Error:' in result.stdout
    assert 'Traceback' not in result.stderr
    assert not (tmp_path / 'api_called').exists()


def test_argument_error_keeps_argparse_exit_two(invoke_cli):
    result = invoke_cli(['--api-key', 'dummy-key'])
    assert result.returncode == 2
    assert '--text, --output' in result.stderr


def test_help_exits_zero_without_generation(invoke_cli, tmp_path):
    result = invoke_cli(['--help'])
    assert result.returncode == 0
    assert 'usage:' in result.stdout
    assert not (tmp_path / 'api_called').exists()


def test_cli_api_key_argument_warns_about_process_list(invoke_cli, tmp_path):
    source = tmp_path / 'book.txt'
    source.write_text('Input text', encoding='utf-8')
    result = invoke_cli(arguments(source))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'visible in the process' in result.stdout
    assert 'shell history' in result.stdout


def test_no_cli_key_argument_means_no_warning(invoke_cli, tmp_path):
    source = tmp_path / 'book.txt'
    source.write_text('Input text', encoding='utf-8')
    result = invoke_cli(['--text', str(source), '--output', 'audiobook.mp3'],
                        settings={'MISTRAL_API_KEY': 'env-key'})
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'shell history' not in result.stdout
