#!/usr/bin/env python3
"""Build and test the runtime image using disposable Docker-owned fixtures."""
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
PASSWORD = 'synthetic-docker-password'


def docker(*arguments, timeout=60, check=True):
    result = subprocess.run(['docker', *map(str, arguments)], capture_output=True,
                            text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f'Docker {arguments[0]} failed:\n{result.stdout[-4000:]}\n{result.stderr[-4000:]}')
    return result


class DockerSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        docker('info', '--format', '{{.ServerVersion}}', timeout=15)
        cls.temporary = tempfile.TemporaryDirectory(prefix='booksmith-docker-smoke-')
        cls.addClassCleanup(cls.temporary.cleanup)
        context = Path(cls.temporary.name) / 'context'
        context.mkdir()
        for name in ('Dockerfile', 'docker-entrypoint.sh', 'requirements.txt', '.dockerignore',
                     'scripts/build_ffmpeg.sh'):
            (context / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, context / name)
        for name in ('src', 'tests'):
            shutil.copytree(ROOT / name, context / name,
                            ignore=shutil.ignore_patterns('__pycache__', '.env', '.env.*'))
        cls.canary = 'build-only-canary-' + uuid.uuid4().hex
        for name in ('.env', '.env.local', 'src/.env', 'src/core/.env.local', 'tests/.env', 'storage/auth.json'):
            path = context / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('DOCKER_BUILD_CANARY=' + cls.canary)
        cls.image = 'mistral-tts:smoke-' + uuid.uuid4().hex[:12]
        cls.addClassCleanup(lambda: docker('image', 'rm', cls.image, check=False))
        docker('build', '--force-rm', '--tag', cls.image, context, timeout=600)
        cls.volume = 'booksmith-smoke-' + uuid.uuid4().hex
        docker('volume', 'create', cls.volume)
        cls.addClassCleanup(lambda: docker('volume', 'rm', cls.volume, check=False))
        cls.mountpoint = json.loads(docker('volume', 'inspect', cls.volume).stdout)[0]['Mountpoint']
        cls.fixture = 'booksmith-fixture-' + uuid.uuid4().hex[:12]
        cls.addClassCleanup(lambda: docker('rm', '--force', cls.fixture, check=False))
        docker('run', '--detach', '--name', cls.fixture, '--network', 'none', '--user', '0',
               '--entrypoint', 'python', '--mount', f'type=volume,source={cls.volume},target=/fixtures',
               cls.image, '-c', 'import time; time.sleep(300)')
        cls.fixture_python('from pathlib import Path; Path("/fixtures/helpers").mkdir(mode=0o755)')
        docker('cp', str(ROOT / 'tests/docker') + '/.', cls.fixture + ':/fixtures/helpers/')

    @classmethod
    def fixture_python(cls, code, *arguments):
        return docker('exec', cls.fixture, 'python', '-c', code, *arguments)

    def prepare(self, *, legacy=True, private=False, readonly_db=False):
        name = uuid.uuid4().hex
        self.fixture_python('''
import json,os,sqlite3,sys
from pathlib import Path
root=Path('/fixtures')/sys.argv[1]
storage=root/'storage'
for name in ('cache','output','translations'):
    (storage/name).mkdir(parents=True,exist_ok=True)
(storage/'preserve.bin').write_bytes(b'preserve data and mode')
(storage/'preserve.bin').chmod(0o640)
outside=root/'outside'
outside.mkdir()
(outside/'untouched').write_bytes(b'outside storage')
(outside/'untouched').chmod(0o640)
if sys.argv[2]=='yes':
    (storage/'auth.json').write_text(json.dumps({'username':'docker-smoke','password':sys.argv[3]}))
if sys.argv[4]=='yes':
    storage.chmod(0o700)
if sys.argv[5]=='yes':
    with sqlite3.connect(storage/'state.db') as connection:
        connection.execute('CREATE TABLE sentinel (value TEXT)')
    (storage/'state.db').chmod(0o444)
''', name, 'yes' if legacy else 'no', PASSWORD, 'yes' if private else 'no', 'yes' if readonly_db else 'no')
        return name

    def options(self, case, *, readonly=False, user=None, credentials=True):
        options = ['--network', 'none', '--mount',
                   f'type=bind,source={self.mountpoint}/{case}/storage,target=/app/storage' + (',readonly' if readonly else ''),
                   '--mount', f'type=bind,source={self.mountpoint}/helpers,target=/smoke,readonly',
                   '--mount', f'type=bind,source={self.mountpoint}/{case}/outside,target=/outside']
        if user:
            options += ['--user', user]
        if credentials:
            # Persisted auth must take precedence over this intentionally different password.
            options += ['--env', 'APP_USERNAME=docker-smoke', '--env', 'APP_PASSWORD=ignored-environment-password',
                        '--env', 'SMOKE_PASSWORD=' + PASSWORD]
        return options

    @contextmanager
    def server(self, case, *, fake=False, user=None):
        name = 'booksmith-server-' + uuid.uuid4().hex[:12]
        command = ['python', '/smoke/smoke_server.py'] if fake else []
        try:
            docker('run', '--detach', '--name', name, *self.options(case, user=user), self.image, *command)
            yield name
        except Exception:
            print(docker('logs', name, check=False).stdout[-4000:])
            print(docker('logs', name, check=False).stderr[-4000:])
            raise
        finally:
            docker('rm', '--force', name, check=False)

    def client(self, name, mode, *arguments):
        result = docker('exec', '--user', '1000:1000', name, 'python', '/smoke/smoke_client.py', mode, *arguments)
        return json.loads(result.stdout)

    def test_default_command_and_explicit_nonroot_user(self):
        case = self.prepare()
        with self.server(case) as server:
            self.assertEqual(self.client(server, 'auth')['uid'], 1000)
        with self.server(case, user='1000:1000') as server:
            self.assertEqual(self.client(server, 'auth')['uid'], 1000)
        self.fixture_python('''
import os,stat,sys
from pathlib import Path
root=Path('/fixtures')/sys.argv[1]
path=root/'storage/preserve.bin'
assert path.read_bytes()==b'preserve data and mode'
assert stat.S_IMODE(path.stat().st_mode)==0o640
assert path.stat().st_uid==1000
outside=root/'outside/untouched'
assert outside.stat().st_uid==0 and stat.S_IMODE(outside.stat().st_mode)==0o640
''', case)

    def test_upload_compile_download_and_restart_on_same_bind_mount(self):
        case = self.prepare()
        with self.server(case, fake=True) as server:
            result = self.client(server, 'generate')
        with self.server(case) as server:
            persisted = self.client(server, 'persist', '--task', result['task'], '--sha256', result['sha256'])
        self.assertEqual(result['sha256'], persisted['sha256'])

    def run_expected_failure(self, case, **settings):
        name = 'booksmith-negative-' + uuid.uuid4().hex[:12]
        try:
            return docker('run', '--rm', '--name', name, *self.options(case, **settings),
                          self.image, check=False, timeout=30)
        finally:
            # Also remove a server if a regression made it start instead of failing.
            docker('rm', '--force', name, check=False)

    def assert_storage_failure(self, case, **settings):
        result = self.run_expected_failure(case, **settings)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Storage initialization failed', result.stderr)
        self.assertIn('/app/storage', result.stderr)

    def test_readonly_bind_mount_is_rejected(self):
        self.assert_storage_failure(self.prepare(), readonly=True)

    def test_nonroot_unwritable_storage_is_rejected(self):
        self.assert_storage_failure(self.prepare(private=True), user='1000:1000')

    def test_unwritable_database_is_rejected(self):
        self.assert_storage_failure(self.prepare(readonly_db=True))

    def test_unsafe_default_credentials_do_not_start_server(self):
        result = self.run_expected_failure(self.prepare(legacy=False), credentials=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unsafe WebUI credentials', result.stderr)

    def test_build_canary_is_absent_from_all_image_layers(self):
        docker('run', '--rm', '--network', 'none', '--entrypoint', 'python', self.image, '-c',
               'from pathlib import Path; assert not Path("/app/tests").exists()')
        archive_path = Path(self.temporary.name) / 'image.tar'
        docker('save', '--output', archive_path, self.image, timeout=120)
        needle = self.canary.encode()
        with tarfile.open(archive_path) as image:
            for entry in image:
                if not entry.name.endswith('/layer.tar'):
                    continue
                with tarfile.open(fileobj=image.extractfile(entry), mode='r|*') as layer:
                    for member in layer:
                        if not member.isfile():
                            continue
                        stream = layer.extractfile(member)
                        tail = b''
                        while block := stream.read(1024 * 1024):
                            if needle in tail + block:
                                self.fail(f'Build-only configuration leaked into image layer file: {member.name}')
                            tail = block[-len(needle):]
        archive_path.unlink()


if __name__ == '__main__':
    unittest.main(verbosity=2)
