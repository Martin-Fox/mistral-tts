"""HTTP checks executed inside the network-isolated runtime container."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('auth', 'generate', 'persist'))
    parser.add_argument('--task')
    parser.add_argument('--sha256')
    args = parser.parse_args()
    # docker exec's user and PID 1 must both have dropped root privileges.
    assert os.getuid() == 1000
    uid = next(line for line in Path('/proc/1/status').read_text().splitlines() if line.startswith('Uid:'))
    assert [int(value) for value in uid.split()[1:]] == [1000] * 4
    with httpx.Client(headers={'X-Requested-With': 'Booksmith'}, base_url='http://127.0.0.1:8000', timeout=20, trust_env=False) as client:
        deadline = time.monotonic() + 25
        while True:
            try:
                ready = client.get('/api/auth/status', timeout=0.5)
                if ready.status_code == 200:
                    break
            except httpx.TransportError:
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError('WebUI did not become ready within 25 seconds')
            time.sleep(0.1)
        assert client.get('/').status_code == 200
        assert client.get('/api/tasks').status_code == 401
        assert client.post('/api/auth/login', json={'username': 'docker-smoke', 'password': 'wrong'}).status_code == 401
        response = client.post('/api/auth/login', json={
            'username': 'docker-smoke', 'password': os.environ['SMOKE_PASSWORD'],
        })
        assert response.status_code == 200
        assert 'httponly' in response.headers['set-cookie'].lower()
        assert client.cookies.get('session_id')
        assert client.get('/api/tasks').status_code == 200
        result = {'uid': os.getuid(), 'mode': args.mode}
        if args.mode != 'auth':
            task = args.task
            if args.mode == 'generate':
                response = client.post('/api/generate', data={
                    'api_key': 'synthetic-docker-api-key', 'voice_preset': 'en_paul_neutral',
                    'output_filename': 'smoke.mp3',
                }, files={'text_file': ('book.txt', 'Zażółć gęślą jaźń. Synthetic upload.'.encode())})
                assert response.status_code == 200
                task = response.json()['task_id']
            completed = None
            with client.stream('GET', '/api/progress', params={'task_id': task}) as stream:
                assert stream.status_code == 200
                for line in stream.iter_lines():
                    if line.startswith('data: '):
                        completed = json.loads(line[6:])
                        if completed['completed'] or completed['status'] in ('Failed', 'Interrupted'):
                            break
            assert completed and completed['completed'], completed
            filename = completed['audio_file']
            audio = client.get('/api/audio/' + filename)
            assert audio.status_code == 200 and len(audio.content) > 100
            destination = Path('/app/storage/output') / filename
            assert audio.content == destination.read_bytes()
            checksum = hashlib.sha256(audio.content).hexdigest()
            if args.sha256:
                assert checksum == args.sha256
            probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                    '-of', 'default=nw=1:nk=1', str(destination)],
                                   capture_output=True, text=True, check=True, timeout=10)
            assert float(probe.stdout) > 0.7
            specs = list(Path('/app/storage/tasks').glob('*/spec.json'))
            assert specs and all(b'synthetic-docker-api-key' not in path.read_bytes() for path in specs)
            result.update(task=task, sha256=checksum)
        assert client.post('/api/auth/logout').status_code == 200
        assert client.get('/api/tasks').status_code == 401
    auth = Path('/app/storage/auth.json')
    assert stat.S_IMODE(auth.stat().st_mode) == 0o600
    assert 'password' not in json.loads(auth.read_text())
    for directory in ('cache', 'output', 'translations'):
        path = Path('/app/storage') / directory
        probe = path / 'write-check'
        probe.write_bytes(b'writable by appuser')
        probe.unlink()
    print(json.dumps(result))


if __name__ == '__main__':
    main()
