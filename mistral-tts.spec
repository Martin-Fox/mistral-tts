# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

try:
    from PyInstaller.utils.hooks import collect_submodules
except ImportError:
    def collect_submodules(name: str):
        return []

block_cipher = None

datas = [
    ('src/web/static', 'src/web/static'),
]

# Include bin directory with ffmpeg / ffprobe if present at build time
bin_dir = Path('bin')
if bin_dir.exists() and bin_dir.is_dir():
    datas.append(('bin', 'bin'))

hiddenimports = [
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'fastapi',
    'starlette',
    'starlette.routing',
    'starlette.responses',
    'starlette.middleware',
    'starlette.staticfiles',
    'pydantic',
    'mistralai',
    'openai',
    'textual',
    'anyio',
    'anyio._backends._asyncio',
    'multipart',
    'dotenv',
]

for mod in ['uvicorn', 'fastapi', 'starlette', 'mistralai', 'textual', 'pydantic', 'anyio', 'multipart']:
    try:
        hiddenimports.extend(collect_submodules(mod))
    except Exception:
        pass

hiddenimports = sorted(list(set(hiddenimports)))

a = Analysis(
    ['src/desktop.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='mistral-tts',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='mistral-tts',
)
