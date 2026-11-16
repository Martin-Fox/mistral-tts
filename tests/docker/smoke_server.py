"""Test bootstrap: real WebUI and FFmpeg, with only the paid TTS client replaced."""
import asyncio
import subprocess

import uvicorn

from src import web
from src.api.factory import DEFAULT_TTS_MODELS


class LocalTTS:
    voice_sample_bytes = None

    def __init__(self, engine):
        self.model = DEFAULT_TTS_MODELS[engine]

    def set_voice_id(self, voice_id):
        self.voice_id = voice_id

    async def generate_audio(self, text, output_path):
        await asyncio.to_thread(subprocess.run, [
            'ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
            'sine=frequency=440:duration=0.7', '-q:a', '9', str(output_path),
        ], check=True, capture_output=True, timeout=15)


web.get_tts_client = lambda engine, key: LocalTTS(engine)

if __name__ == '__main__':
    uvicorn.run(web.app, host='127.0.0.1', port=8000, log_level='warning')
