"""Isolate collection, every test and spawned Python processes from user state."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

import pytest


REPOSITORY = Path(__file__).resolve().parents[1]
APP_PREFIXES = ('MISTRAL_', 'OPENAI_', 'APP_', 'SESSION_', 'LOGIN_', 'API_',
                'AUDIO_', 'MAX_', 'STORAGE_', 'CACHE_LOCK_', 'WEB_CONCURRENCY',
                'INPUT_TEXT_ENCODING', 'BOOKSMITH_ENV_FILE')


def _clean_app_environment(*, keep_env_file=False):
    for name in list(os.environ):
        if name.startswith(APP_PREFIXES) and not (keep_env_file and name == 'BOOKSMITH_ENV_FILE'):
            del os.environ[name]


def _static_files(destination):
    shutil.copytree(REPOSITORY / 'src/web/static', destination / 'src/web/static', dirs_exist_ok=True)


def pytest_configure(config):
    # Runs before collection: tests import web.db and clients at module scope.
    original_cwd, original_environment = Path.cwd(), dict(os.environ)
    if config.option.xmlpath:
        config.option.xmlpath = str(Path(config.option.xmlpath).absolute())
    sandbox = tempfile.TemporaryDirectory(prefix='booksmith-pytest-')
    root = Path(sandbox.name)
    (root / 'pytest-temp').mkdir()
    os.environ['PYTEST_DEBUG_TEMPROOT'] = str(root / 'pytest-temp')
    _clean_app_environment()
    os.environ['BOOKSMITH_ENV_FILE'] = str(root / '.env')
    guard = root / 'python-guard'
    guard.mkdir()
    shutil.copyfile(REPOSITORY / 'tests/network_guard.py', guard / 'sitecustomize.py')
    os.environ['PYTHONPATH'] = os.pathsep.join((str(guard), str(REPOSITORY)))
    sys.path.insert(0, str(REPOSITORY))
    import network_guard  # noqa: F401 - installs the same guard in the pytest process
    _static_files(root)
    os.chdir(root)

    def restore():
        os.chdir(original_cwd)
        os.environ.clear()
        os.environ.update(original_environment)
        sandbox.cleanup()
    config.add_cleanup(restore)


@pytest.fixture(scope='session')
def test_password_hash():
    from src.core.auth import hash_password
    return hash_password('test-only-password')


@pytest.fixture(autouse=True)
def isolated_state(tmp_path_factory, monkeypatch, test_password_hash):
    from src import web
    from src.core import task_store
    original_environment = dict(os.environ)
    _clean_app_environment(keep_env_file=True)
    application = tmp_path_factory.mktemp('application')
    monkeypatch.chdir(application)
    monkeypatch.setenv('BOOKSMITH_ENV_FILE', str(application / '.env'))
    _static_files(application)
    # Keep the DB object's identity: older tests import `db` directly from web.
    (application / 'storage').mkdir()
    monkeypatch.setattr(web.db, 'db_path', application / 'storage/state.db')
    web.db._init_db()
    monkeypatch.setattr(web.global_log_handler, 'database', web.db)
    monkeypatch.setattr(task_store, 'TASK_ROOT', application / 'storage/tasks')
    monkeypatch.setattr(web, 'AUTH_FILE', application / 'storage/auth.json')
    monkeypatch.setattr(web, 'APP_USERNAME', 'admin')
    monkeypatch.setattr(web, 'APP_PASSWORD', None)
    monkeypatch.setattr(web, 'APP_PASSWORD_HASH', test_password_hash)
    sessions = web.active_sessions
    sessions.clear()
    monkeypatch.setattr(web, 'active_sessions', sessions)
    monkeypatch.setattr(web, 'login_limiter', web.LoginLimiter())
    monkeypatch.setattr(web, 'job_controller', web.JobController(2, 2))
    monkeypatch.setattr(web.app, 'dependency_overrides', {})
    web.configure_sessions()
    yield
    sessions.clear()
    os.environ.clear()
    os.environ.update(original_environment)


@pytest.fixture
def authenticated_web(isolated_state):
    """Opt-in bypass for endpoint logic tests; auth tests still use real auth."""
    from src import web
    web.active_sessions['session-id'] = time.monotonic() + 3600
    web.app.dependency_overrides[web.verify_session] = lambda: 'session-id'
    return web.app


@pytest.fixture
def anyio_backend():
    # The application uses asyncio APIs; Trio is not an alternative runtime here.
    return 'asyncio'
