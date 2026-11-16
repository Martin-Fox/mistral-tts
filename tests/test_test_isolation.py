"""Exercise the test harness in fresh interpreters, including collection and teardown."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

import pytest

from src.core.config import get_env_path, get_translation_model, load_environment


REPOSITORY = Path(__file__).resolve().parents[1]


def test_explicit_env_file_does_not_discover_another_file(tmp_path, monkeypatch):
    other = tmp_path / 'other'
    other.mkdir()
    (other / '.env').write_text('MISTRAL_TRANSLATION_MODEL=must-not-load\n')
    monkeypatch.chdir(other)
    selected = tmp_path / 'controlled' / '.env'
    monkeypatch.setenv('BOOKSMITH_ENV_FILE', str(selected))
    monkeypatch.delenv('MISTRAL_TRANSLATION_MODEL', raising=False)
    assert get_env_path() == selected
    assert not load_environment()
    assert get_translation_model() == 'ministral-8b-latest'
    selected.parent.mkdir()
    selected.write_text('MISTRAL_TRANSLATION_MODEL=mistral-small-latest\n')
    assert load_environment()
    assert get_translation_model() == 'mistral-small-latest'
    monkeypatch.delenv('BOOKSMITH_ENV_FILE')
    monkeypatch.delenv('MISTRAL_TRANSLATION_MODEL')
    assert get_env_path() == other / '.env'
    assert get_translation_model() == 'must-not-load'


def test_real_network_and_dns_are_disabled():
    with pytest.raises(AssertionError, match='disabled'):
        socket.getaddrinfo('example.com', 443)
    with socket.socket() as connection:
        with pytest.raises(AssertionError, match='disabled'):
            connection.connect(('192.0.2.1', 443))
        with pytest.raises(AssertionError, match='disabled'):
            connection.connect_ex(('192.0.2.1', 443))
    result = subprocess.run([sys.executable, '-c',
                             'import socket; socket.create_connection(("192.0.2.1",443))'],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode != 0
    assert 'disabled in tests' in result.stderr


def test_collection_and_individual_tests_leave_user_files_unchanged(tmp_path):
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    shutil.copytree(REPOSITORY / 'src', checkout / 'src', ignore=shutil.ignore_patterns('__pycache__'))
    tests = checkout / 'tests'
    tests.mkdir()
    for name in ('conftest.py', 'network_guard.py'):
        shutil.copyfile(REPOSITORY / 'tests' / name, tests / name)
    shutil.copyfile(REPOSITORY / 'pytest.ini', checkout / 'pytest.ini')
    user_storage = checkout / 'storage'
    user_storage.mkdir()
    sentinels = [checkout / '.env', user_storage / 'state.db', user_storage / 'auth.json']
    for path in sentinels:
        path.write_bytes(b'untouched user fixture: not a database or credentials')
    (checkout / '.env').write_text('MISTRAL_API_KEY=synthetic-file-key\n'
                                 'MISTRAL_TRANSLATION_MODEL=synthetic-file-model\n')
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in sentinels}
    (tests / 'test_probe.py').write_text('''\
import os
from pathlib import Path
from src.web import db, active_sessions
from src.core.config import get_translation_model, save_translation_model

# These assertions run during collection, before per-test fixtures.
assert os.getenv("MISTRAL_API_KEY") is None
assert Path.cwd().name.startswith("booksmith-pytest-")

def test_first():
    db.create_task("same-id")
    active_sessions["leftover"] = 123
    save_translation_model("mistral-large-latest")

def test_second():
    assert db.get_task("same-id") is None
    assert "leftover" not in active_sessions
    assert get_translation_model() == "ministral-8b-latest"
''')
    environment = dict(os.environ)
    environment.update(PYTHONPATH=str(checkout), MISTRAL_API_KEY='synthetic-user-key',
                       BOOKSMITH_ENV_FILE=str(checkout / '.env'))
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '--junitxml=results.xml'],
                            cwd=checkout, env=environment, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '2 passed' in result.stdout
    assert (checkout / 'results.xml').is_file()
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in sentinels} == before


def test_timeout_reports_the_hanging_test_and_exits(tmp_path):
    hanging = tmp_path / 'test_hanging.py'
    hanging.write_text('import time\ndef test_intentional_hang():\n    time.sleep(10)\n')
    result = subprocess.run([sys.executable, '-m', 'pytest', '-c', str(REPOSITORY / 'pytest.ini'),
                             '--confcutdir', str(tmp_path), '--timeout=0.2', '-vv', str(hanging)],
                            cwd=tmp_path, env=dict(os.environ), capture_output=True, text=True, timeout=5)
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert 'test_intentional_hang' in output
    assert 'Timeout' in output
