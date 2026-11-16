"""Private, immutable resume inputs. API credentials are deliberately excluded."""
import hashlib
import json
import os
from pathlib import Path
import uuid

from src.api.factory import DEFAULT_TTS_MODELS
from src.core.cache_io import staged_file, save_json_atomic
from src.core.config import get_translation_model
from src.core.cache_identity import VOICE_PREPROCESS_VERSION
from src.core.text_splitter import SPLITTER_VERSION
from src.core.resource_limits import ResourceLimits


TASK_ROOT = Path("storage/tasks")

PARAMETERS = ('voice_preset', 'voice_manual_id', 'source_lang', 'target_lang',
              'output_filename', 'engine', 'translation_model', 'input_encoding')


def task_directory(task_id):
    # Older internal tests use non-UUID IDs; hash arbitrary IDs into safe paths.
    return TASK_ROOT / hashlib.sha256(task_id.encode()).hexdigest()


def save_job(task_id, arguments):
    directory = task_directory(task_id)
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    if (directory / 'spec.json').exists():
        return
    params = {name: arguments.get(name) for name in PARAMETERS}
    params['input_encoding'] = params['input_encoding'] or os.getenv('INPUT_TEXT_ENCODING', 'auto')
    if arguments.get('text_file_data') is None:
        params['input_encoding'] = 'utf-8'
    params['engine'] = (params['engine'] or 'mistral').strip().lower()
    if params['engine'] not in DEFAULT_TTS_MODELS:
        raise ValueError('Unknown TTS engine')
    if params['target_lang']:
        params['translation_model'] = params['translation_model'] or get_translation_model()
    assets = {}
    for kind in ('text', 'voice'):
        uploaded = arguments.get(f'{kind}_file_data')
        if kind == 'text' and uploaded is None:
            uploaded = ('input.txt', (arguments.get('text_content') or '').encode('utf-8'))
        if uploaded is None:
            continue
        filename, content = uploaded
        name = kind + (Path(filename or 'input.txt').suffix or '.txt')
        destination = directory / name
        with staged_file(destination) as temporary:
            temporary.write_bytes(content)
            temporary.replace(destination)
        assets[kind] = {'name': name, 'sha256': hashlib.sha256(content).hexdigest()}
    save_json_atomic(directory / 'spec.json', {
        'version': 1, 'parameters': params, 'assets': assets,
        'tts_model': DEFAULT_TTS_MODELS[params['engine']],
        'splitter_version': SPLITTER_VERSION, 'max_chars': 1000,
        'voice_preprocess_version': VOICE_PREPROCESS_VERSION if 'voice' in assets else None,
    })


def load_job(task_id):
    directory = task_directory(task_id)
    spec_path = directory / 'spec.json'
    if spec_path.stat().st_size > 65536:
        raise ValueError('Saved task specification is too large')
    spec = json.loads(spec_path.read_text())
    params = spec['parameters']
    if (spec['version'] != 1 or spec['splitter_version'] != SPLITTER_VERSION
            or spec['max_chars'] != 1000
            or spec['tts_model'] != DEFAULT_TTS_MODELS.get(params['engine'])):
        raise ValueError('Saved task is incompatible with current models/segmentation')
    if 'voice' in spec['assets'] and spec.get('voice_preprocess_version') != VOICE_PREPROCESS_VERSION:
        raise ValueError('Saved voice preprocessing version is incompatible')
    result = {name: params.get(name) for name in PARAMETERS}
    result.update(text_content=None, text_file_data=None, voice_file_data=None)
    limits = ResourceLimits.from_env()
    for kind, asset in spec['assets'].items():
        if kind not in ('text', 'voice') or Path(asset['name']).name != asset['name']:
            raise ValueError('Invalid saved task asset')
        path = directory / asset['name']
        if path.is_symlink():
            raise ValueError('Invalid saved task asset')
        limit = limits.max_text_upload_bytes if kind == 'text' else limits.max_voice_upload_bytes
        with path.open('rb') as stream:
            content = stream.read(limit + 1)
        if len(content) > limit or hashlib.sha256(content).hexdigest() != asset['sha256']:
            raise ValueError('Saved task input changed or exceeds current limits')
        result[f'{kind}_file_data'] = (asset['name'], content)
    if result['text_file_data'] is None:
        raise ValueError('Saved task has no text input')
    return result


def validate_task_id(task_id):
    return str(uuid.UUID(task_id))


def save_cache_reference(task_id, cache_key):
    """Pin audio needed by a durable task before touching the shared cache."""
    save_json_atomic(task_directory(task_id) / 'cache.json', {'cache_key': cache_key})


def load_translation(task_id):
    directory = task_directory(task_id)
    marker = directory / 'translation.json'
    if not marker.exists():
        return None
    asset = json.loads(marker.read_text())
    if Path(asset['name']).name != asset['name']:
        raise ValueError('Invalid saved translation')
    path = directory / asset['name']
    if (path.is_symlink() or path.stat().st_size > ResourceLimits.from_env().max_text_upload_bytes
            or hashlib.sha256(path.read_bytes()).hexdigest() != asset['sha256']):
        raise ValueError('Saved translation changed')
    return path


def save_translation(task_id, source):
    destination = task_directory(task_id) / ('translated' + source.suffix)
    data = source.read_bytes()
    with staged_file(destination) as temporary:
        temporary.write_bytes(data)
        temporary.replace(destination)
    save_json_atomic(task_directory(task_id) / 'translation.json',
                     {'name': destination.name, 'sha256': hashlib.sha256(data).hexdigest()})
    return destination
